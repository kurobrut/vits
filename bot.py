import discord
from discord.ext import commands
from discord.ui import View, Button, Select
from PIL import Image
import aiohttp
import io
import math
import random
import string
import numpy as np
import asyncio
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

# ─── CONFIG ─────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

TEMPLATE_PATH = "template.png"
FRAME_BOX = (863, 568, 2893, 2497)
WHITE_THRESH = 15
MAX_IMAGES = 10
# ────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# =======================================================
# 🔥 POT FUNCTION
# =======================================================
def make_pot(image_bytes: bytes) -> bytes:
    template = Image.open(TEMPLATE_PATH).convert("RGBA")

    fx1, fy1, fx2, fy2 = FRAME_BOX
    fw, fh = fx2 - fx1, fy2 - fy1

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    if img.width / img.height > fw / fh:
        nh, nw = fh, int(img.width * fh / img.height)
    else:
        nw, nh = fw, int(img.height * fw / img.width)

    img = img.resize((nw, nh), Image.LANCZOS)
    img = img.crop(((nw - fw) // 2, (nh - fh) // 2,
                    (nw - fw) // 2 + fw, (nh - fh) // 2 + fh))

    result = np.array(template, dtype=np.uint8)
    img_arr = np.array(img.convert("RGBA"), dtype=np.uint8)

    region = result[fy1:fy2, fx1:fx2, :3].astype(np.int16)

    mask = (
        (np.abs(region[:, :, 0] - 235) < WHITE_THRESH) &
        (np.abs(region[:, :, 1] - 235) < WHITE_THRESH) &
        (np.abs(region[:, :, 2] - 235) < WHITE_THRESH)
    )

    for ch in range(3):
        result[fy1:fy2, fx1:fx2, ch][mask] = img_arr[:, :, ch][mask]

    out = io.BytesIO()
    Image.fromarray(result).convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out.read()

# =======================================================
# 📌 POT COMMAND
# =======================================================
@bot.command(name="pot", aliases=["f", "F"])
async def pot(ctx):

    images = []

    # Current message images
    images += [
        a for a in ctx.message.attachments
        if a.content_type and a.content_type.startswith("image/")
    ]

    # Replied message images
    if ctx.message.reference:
        try:
            replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            images += [
                a for a in replied_msg.attachments
                if a.content_type and a.content_type.startswith("image/")
            ]
        except Exception as e:
            print("Reply fetch error:", e)

    if not images:
        await ctx.reply("📎 Attach or reply to **1–10 images** with `!pot`.")
        return

    images = images[:MAX_IMAGES]

    msg = await ctx.reply(f"⏳ Processing {len(images)} image(s)...")

    files = []
    errors = []

    for i, att in enumerate(images):
        try:
            raw = await att.read()
            result = make_pot(raw)

            random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

            file = discord.File(
                io.BytesIO(result),
                filename=f"pot_{random_id}.png"
            )

            files.append(file)

        except Exception as e:
            errors.append(f"{i+1}: {e}")

    if not files:
        await msg.edit(content="❌ Failed to process images.")
        return

    caption = f"✅ {len(files)} POT image(s) ready!"
    if errors:
        caption += "\n⚠️ " + " | ".join(errors)

    await msg.edit(content=caption)

    # 🔥 SEND ONE BY ONE (IMPORTANT FIX)
    for f in files:
        await ctx.send(file=f)
        await asyncio.sleep(0.4)

# =======================================================
# 🧩 COLLAGE FUNCTION
# =======================================================
async def create_collage(images, spacing):

    loaded_images = []

    async with aiohttp.ClientSession() as session:
        for url in images:
            async with session.get(url) as resp:
                data = await resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGB")
                loaded_images.append(img)

    count = len(loaded_images)

    if count < 2:
        raise ValueError("Upload at least 2 images.")

    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)

    BASE_CANVAS = 1500
    cell_size = BASE_CANVAS // max(cols, rows)

    width = cols * cell_size + spacing * (cols + 1)
    height = rows * cell_size + spacing * (rows + 1)

    collage = Image.new("RGB", (width, height), (255, 255, 255))

    def crop_and_resize(img, target_w, target_h):
        img_ratio = img.width / img.height
        target_ratio = target_w / target_h

        if img_ratio > target_ratio:
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        else:
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))

        return img.resize((target_w, target_h), Image.LANCZOS)

    index = 0

    for r in range(rows):
        remaining = count - index
        remaining_rows = rows - r
        current_cols = math.ceil(remaining / remaining_rows)

        cell_w = (width - spacing * (current_cols + 1)) // current_cols
        cell_h = (height - spacing * (rows + 1)) // rows

        for c in range(current_cols):
            if index >= count:
                break

            img = crop_and_resize(loaded_images[index], cell_w, cell_h)

            x = spacing + c * (cell_w + spacing)
            y = spacing + r * (cell_h + spacing)

            collage.paste(img, (x, y))
            index += 1

    collage = collage.convert("RGBA")

    try:
        watermark = Image.open("watermark.png").convert("RGBA")

        scale = 0.5
        wm_width = int(width * scale)
        wm_ratio = wm_width / watermark.width
        wm_height = int(watermark.height * wm_ratio)

        watermark = watermark.resize((wm_width, wm_height), Image.LANCZOS)

        x = (width - wm_width) // 2
        y = (height - wm_height) // 2

        collage.paste(watermark, (x, y), watermark)

    except:
        pass

    buffer = io.BytesIO()
    collage.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer

# =======================================================
# 🎛 COLLAGE COMMAND
# =======================================================
@bot.command()
async def collage(ctx):

    if not ctx.message.attachments:
        await ctx.send("Upload **2–10 images**.")
        return

    attachments = ctx.message.attachments[:10]

    if len(attachments) < 2:
        await ctx.send("Upload at least **2 images**.")
        return

    image_urls = [a.url for a in attachments]

    collage_buffer = await create_collage(image_urls, spacing=20)

    random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

    file = discord.File(
        collage_buffer,
        filename=f"collage_{random_id}.png"
    )

    await ctx.send(file=file)

@bot.command(name="cf")
async def cf(ctx):

    if not ctx.message.attachments:
        await ctx.send("Upload **2–10 images**.")
        return

    attachments = ctx.message.attachments[:10]

    if len(attachments) < 2:
        await ctx.send("Upload at least **2 images**.")
        return

    image_urls = [a.url for a in attachments]

    msg = await ctx.reply("⏳ Creating collage + frame...")

    try:
        # Step 1: create collage
        collage_buffer = await create_collage(image_urls, spacing=20)
        collage_bytes = collage_buffer.getvalue()

        # Step 2: apply frame (reuse your pot function)
        final_image = make_pot(collage_bytes)

        random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

        file = discord.File(
            io.BytesIO(final_image),
            filename=f"cf_{random_id}.png"
        )

        await msg.edit(content="✅ Collage framed successfully!")
        await ctx.send(file=file)

    except Exception as e:
        await msg.edit(content=f"❌ Failed: {e}")

# =======================================================
# ❓ HELP COMMAND
# =======================================================
@bot.command(name="commands")
async def commands_list(ctx):
    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="Here are all available commands:",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="!pot (aliases: !f, !F)",
        value="Apply a decorative pot frame to your image(s).\n**Usage:** `!pot` (attach 1–10 images or reply to a message with images)",
        inline=False
    )

    embed.add_field(
        name="!collage",
        value="Create a collage from multiple images.\n**Usage:** `!collage` (attach 2–10 images)",
        inline=False
    )

    embed.add_field(
        name="!cf",
        value="Create a collage and apply a pot frame to it.\n**Usage:** `!cf` (attach 2–10 images)",
        inline=False
    )

    embed.add_field(
        name="!commands",
        value="Display this commands list.",
        inline=False
    )

    embed.set_footer(text="💡 You can also reply to a message with images when using !pot")

    await ctx.send(embed=embed)

# =======================================================
@bot.event
async def on_ready():
    print(f"✅ {bot.user} online | !collage + !pot ready")

keep_alive()
bot.run(TOKEN)
