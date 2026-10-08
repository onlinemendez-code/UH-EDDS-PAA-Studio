# uh_texture_lab.py
"""
UH Texture Lab
==============
Двусторонний конвертер и студия для работы с текстурами проекта UH:

    PNG / JPG / JPEG / TGA / BMP   <->   DDS (.edds)   ->   PAA

Зависимости: PySide6, Pillow, numpy (опционально, для DXT).
Опционально: qtawesome (красивые иконки), шрифт Inter в папке fonts/.
Для PAA: imagetopaa (Snap Store) или ImageToPAA.exe из Arma 3 Tools.
"""

import json
import os
import struct
import sys
import shutil
import subprocess
from pathlib import Path

from PIL import Image

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

qta = None
HAS_QTA = False

from PySide6.QtCore import (
    Qt, QPoint, QSize, QRectF, QTimer, QPropertyAnimation,
    QEasingCurve, Signal, QStandardPaths, QEvent,
)
from PySide6.QtGui import (
    QGuiApplication, QColor, QPainter, QPen, QFont, QPixmap, QImage,
    QIcon, QBrush, QPainterPath, QAction, QKeySequence, QShortcut,
    QFontDatabase,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QFrame, QProgressBar,
    QComboBox, QCheckBox, QSizeGrip, QListWidget, QListWidgetItem,
    QAbstractItemView, QGraphicsDropShadowEffect, QSpinBox, QSystemTrayIcon,
    QMenu, QDialog,
)


# ============================================================ constants
RASTER_EXT = {".png", ".jpg", ".jpeg", ".tga", ".bmp"}
EDDS_EXT = {".edds", ".dds"}
PAA_EXT = {".paa", ".pac"}
ALL_SRC_EXT = RASTER_EXT | EDDS_EXT | PAA_EXT

APP_NAME = "UH EDDS/PAA Studio"
APP_ORG = "UH"
APP_VERSION = "1.0"
SETTINGS_DIR_NAME = "UH EDDS/PAA Studio"
SETTINGS_FILE = "settings.json"

VIEWER_MIN_ZOOM = 0.1
VIEWER_MAX_ZOOM = 8.0
VIEWER_ZOOM_STEP = 1.25

LANGUAGES = [
    ("ru",    "Русский",   "RU"),
    ("en",    "English",   "EN"),
    ("zh_CN", "简体中文",  "中"),
    ("zh_TW", "繁體中文",  "繁"),
    ("es",    "Español",   "ES"),
    ("de",    "Deutsch",   "DE"),
    ("fr",    "Français",  "FR"),
    ("pl",    "Polski",    "PL"),
    ("ja",    "日本語",    "JA"),
    ("ko",    "한국어",    "KO"),
]


# ============================================================ theme
THEME_DARK = {
    "bg": "#1e1e1e", "panel": "#252526", "input_bg": "#3c3c3c",
    "input_border": "#3e3e42", "border": "#3e3e42", "divider": "#2d2d30",
    "text": "#cccccc", "text_dim": "#858585", "text_strong": "#ffffff",
    "accent": "#007acc", "accent_hover": "#1a8cd8", "accent_press": "#0066aa",
    "danger": "#f14c4c", "success": "#4ec9b0", "warning": "#dcdcaa",
    "shadow_alpha": 70, "overlay": "#0f1118",
}

THEME_LIGHT = {
    "bg": "#ffffff", "panel": "#f3f3f3", "input_bg": "#ffffff",
    "input_border": "#cecece", "border": "#dcdcdc", "divider": "#e5e5e5",
    "text": "#1f1f1f", "text_dim": "#6a6a6a", "text_strong": "#000000",
    "accent": "#007acc", "accent_hover": "#1a8cd8", "accent_press": "#0066aa",
    "danger": "#cd3131", "success": "#16825d", "warning": "#b58900",
    "shadow_alpha": 25, "overlay": "#1f1f1f",
}


# ============================================================ resource dirs
def _external_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _internal_dir() -> Path | None:
    if "__compiled__" in globals():
        try:
            return Path(__compiled__.containing_dir)  # type: ignore  # noqa
        except Exception:
            pass
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore
    return None


# ============================================================ translations
_FALLBACK_EN = {
    "app_name": APP_NAME,
    "btn_convert": "Convert", "btn_cancel": "Cancel",
    "btn_add": "Add", "btn_clear": "Clear", "btn_browse": "Browse…",
    "btn_save": "Save", "btn_delete": "Delete", "btn_close": "Close",
    "btn_ok": "OK", "btn_yes": "Yes", "btn_no": "No",
    "status_ready": "Ready",
    "profile_default": "Default", "profile_new": "New…",
    "profile_save_btn": "Save", "profile_delete_btn": "Delete",
    "lang_menu_tooltip": "Change language",
    "window_copyright": "Product © UNDEAD HEAVEN · Not affiliated with Bohemia Interactive a.s.",
    "about_title": "About",
    "about_product": "UH Texture Lab — a texture tool for the DayZ/Arma community.",
    "about_copyright": "Copyright (c) 2026 UNDEAD HEAVEN. All rights reserved.",
    "about_bi_disclaimer": (
        "This tool is not an official product of Bohemia Interactive. "
        "Bohemia Interactive, Arma, DayZ and associated logos are trademarks "
        "or registered trademarks of Bohemia Interactive a.s."
    ),
    "about_eula": (
        "Use of this tool implies acceptance of the End User License Agreement "
        "(EULA) for Bohemia Interactive tools. Non-commercial use only, in "
        "accordance with the Bohemia Interactive community rules."
    ),
    "about_paa_note": (
        "PAA files created with this tool are subject to the BI's Tools EULA "
        "and cannot be sold or commercially exploited."
    ),
}


def load_translations() -> dict[str, dict]:
    result: dict[str, dict] = {}
    internal = _internal_dir()
    external = _external_dir()

    if internal is not None:
        builtin = internal / "langs"
        if builtin.is_dir():
            for f in builtin.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        result[f.stem] = json.load(fp)
                except Exception as e:
                    print(f"[langs] {f.name}: {e}", file=sys.stderr)

    ext_langs = external / "langs"
    if ext_langs.is_dir():
        for f in ext_langs.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    result[f.stem] = json.load(fp)
            except Exception as e:
                print(f"[langs] {f.name}: {e}", file=sys.stderr)

    return result


class Translator:
    def __init__(self, translations: dict[str, dict], lang: str,
                 fallback: str = "en"):
        self._t = translations
        self._fallback = fallback
        self._lang = lang if lang in translations else fallback

    def set_lang(self, lang: str):
        self._lang = lang if lang in self._t else self._fallback

    def current_lang(self) -> str:
        return self._lang

    def __call__(self, key: str, **kwargs) -> str:
        val = self._t.get(self._lang, {}).get(key)
        if val is None:
            val = self._t.get(self._fallback, {}).get(key)
        if val is None:
            val = _FALLBACK_EN.get(key)
        if val is None:
            val = key
        if kwargs:
            try:
                val = val.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return val


TRANSLATIONS: dict[str, dict] = {}
TR: Translator | None = None


def tr(key: str, **kwargs) -> str:
    if TR is None:
        return key
    return TR(key, **kwargs)


# ============================================================ settings
def _settings_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if not base:
        base = str(Path.home() / ".config")
    d = Path(base) / SETTINGS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d / SETTINGS_FILE


DEFAULT_SETTINGS = {
    "theme": "dark",
    "language": "ru",
    "last_open_dir": "",
    "last_save_dir": "",
    "last_mode": "img_to_edds",
    "mips": {"enabled": False, "levels": 0},
    "compression": "none",
    "normalize": {"enabled": False, "mode": "pow2", "w": 1024, "h": 1024},
    "open_folder_after": True,
    "paa_suffix": "_CO",
    "imagetopaa_path": "",
    "profiles": {},
}


def load_settings() -> dict:
    p = _settings_path()
    if not p.exists():
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return json.loads(json.dumps(DEFAULT_SETTINGS))

    def merge(dst, src):
        for k, v in src.items():
            if k not in dst:
                dst[k] = v
            elif isinstance(v, dict) and isinstance(dst[k], dict):
                merge(dst[k], v)
    merge(data, DEFAULT_SETTINGS)
    return data


def save_settings(data: dict):
    p = _settings_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[settings] save failed: {e}", file=sys.stderr)


# ============================================================ PAA finder
def find_imagetopaa() -> str | None:
    for name in ("imagetopaa", "imagetopaa.exe", "ImageToPAA.exe"):
        p = shutil.which(name)
        if p:
            return p
    for sp in ("/snap/bin/imagetopaa", "/var/lib/snapd/snap/bin/imagetopaa"):
        if Path(sp).exists():
            return sp
    win_candidates = [
        r"C:\Program Files (x86)\Steam\steamapps\common\Arma 3 Tools\ImageToPAA\ImageToPAA.exe",
        r"C:\Program Files\Steam\steamapps\common\Arma 3 Tools\ImageToPAA\ImageToPAA.exe",
    ]
    for wc in win_candidates:
        if Path(wc).exists():
            return wc
    return None


def paa_convert(imagetopaa_path: str, src: Path, dst: Path,
                compression: str = "dxt5") -> None:
    if not imagetopaa_path:
        raise RuntimeError(tr("paa_need_tool"))
    cmd = [imagetopaa_path, str(src), str(dst)]
    if compression in ("dxt1", "dxt5"):
        cmd.extend(["--format", compression])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
    except FileNotFoundError:
        raise RuntimeError(f"Not found: {imagetopaa_path}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("imagetopaa timeout (120s)")
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"imagetopaa exit {result.returncode}:\n{err}")


# ============================================================ DDS writer
def _bgra_bytes(im_rgba: Image.Image) -> bytes:
    r, g, b, a = im_rgba.split()
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


def _make_mip_chain(im: Image.Image, extra_levels: int):
    chain = [im]
    cur = im
    for _ in range(extra_levels):
        if cur.width == 1 and cur.height == 1:
            break
        w = max(1, cur.width // 2)
        h = max(1, cur.height // 2)
        cur = cur.resize((w, h), Image.BOX)
        chain.append(cur)
    return chain


def _pack_dds_header(w, h, mip_count, four_cc=None):
    ddsd_caps, ddsd_height, ddsd_width = 0x1, 0x2, 0x4
    ddsd_pitch, ddsd_pixfmt, ddsd_mipcount = 0x8, 0x1000, 0x20000
    ddpf_alpha, ddpf_rgb, ddpf_fourcc = 0x1, 0x40, 0x4
    ddscaps_complex, ddscaps_texture, ddscaps_mipmap = 0x8, 0x1000, 0x400000

    flags = ddsd_caps | ddsd_height | ddsd_width | ddsd_pixfmt
    if four_cc is None:
        flags |= ddsd_pitch
    caps = ddscaps_texture
    if mip_count > 1:
        flags |= ddsd_mipcount
        caps |= ddscaps_complex | ddscaps_mipmap

    pitch = w * 4 if four_cc is None else max(1, w // 4) * (
        8 if four_cc == b"DXT1" else 16
    )
    mip_field = mip_count if mip_count > 1 else 0

    header = struct.pack(
        "<4sIIIIIII",
        b"DDS ", 124, flags, h, w, pitch, 0, mip_field,
    ) + b"\0" * 44

    if four_cc is None:
        pf = struct.pack(
            "<IIIIIIII",
            32, ddpf_rgb | ddpf_alpha, 0, 32,
            0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000,
        )
    else:
        pf = struct.pack(
            "<IIIIIIII",
            32, ddpf_fourcc, int.from_bytes(four_cc, "little"), 0,
            0, 0, 0, 0,
        )

    caps_pack = struct.pack("<IIIII", caps, 0, 0, 0, 0)
    return header + pf + caps_pack


# ============================================================ DXT codecs
def _rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _from_565(c):
    r = ((c >> 11) & 0x1F) * 255 // 31
    g = ((c >> 5) & 0x3F) * 255 // 63
    b = (c & 0x1F) * 255 // 31
    return r, g, b


def _dxt1_color_block(block_rgb):
    flat = block_rgb.reshape(-1, 3).astype(np.int32)
    lum = 0.299 * flat[:, 0] + 0.587 * flat[:, 1] + 0.114 * flat[:, 2]
    i_min = int(np.argmin(lum))
    i_max = int(np.argmax(lum))
    c0 = _rgb565(*flat[i_max])
    c1 = _rgb565(*flat[i_min])
    if c0 < c1:
        c0, c1 = c1, c0
    r0, g0, b0 = _from_565(c0)
    r1, g1, b1 = _from_565(c1)
    pal = np.zeros((4, 3), dtype=np.int32)
    pal[0] = (r0, g0, b0)
    pal[1] = (r1, g1, b1)
    if c0 > c1:
        pal[2] = ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3)
        pal[3] = ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3)
    else:
        pal[2] = ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2)
        pal[3] = (0, 0, 0)
    d = flat[:, None, :] - pal[None, :, :]
    dist = (d * d).sum(axis=2)
    idx = np.argmin(dist, axis=1).astype(np.uint32)
    bits = 0
    for i, v in enumerate(idx):
        bits |= (int(v) & 0x3) << (2 * i)
    return struct.pack("<HHI", c0, c1, bits)


def _dxt5_alpha_block(block_a):
    a = block_a.reshape(-1).astype(np.int32)
    a0 = int(np.max(a))
    a1 = int(np.min(a))
    if a0 == a1:
        return struct.pack("<BB6s", a0, a1, b"\x00" * 6)
    pal = np.zeros(8, dtype=np.int32)
    pal[0] = a0
    pal[1] = a1
    if a0 > a1:
        for i in range(1, 7):
            pal[i + 1] = ((7 - i) * a0 + i * a1) // 7
    else:
        for i in range(1, 5):
            pal[i + 1] = ((5 - i) * a0 + i * a1) // 5
        pal[6] = 0
        pal[7] = 255
    d = np.abs(a[:, None] - pal[None, :])
    idx = np.argmin(d, axis=1).astype(np.uint64)
    bits = 0
    for i, v in enumerate(idx):
        bits |= int(v) << (3 * i)
    return struct.pack("<BB", a0, a1) + bits.to_bytes(6, "little")


def _dxt1_image(im_rgba: Image.Image) -> bytes:
    w, h = im_rgba.size
    arr = np.asarray(im_rgba.convert("RGB"), dtype=np.uint8)
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            block = arr[by:by + 4, bx:bx + 4, :]
            if block.shape[0] < 4 or block.shape[1] < 4:
                pad = np.zeros((4, 4, 3), dtype=np.uint8)
                pad[:block.shape[0], :block.shape[1], :] = block
                block = pad
            out += _dxt1_color_block(block)
    return bytes(out)


def _dxt5_image(im_rgba: Image.Image) -> bytes:
    w, h = im_rgba.size
    arr_rgb = np.asarray(im_rgba.convert("RGB"), dtype=np.uint8)
    arr_a = np.asarray(im_rgba.split()[3], dtype=np.uint8)
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            blk_rgb = arr_rgb[by:by + 4, bx:bx + 4, :]
            blk_a = arr_a[by:by + 4, bx:bx + 4]
            if blk_rgb.shape[0] < 4 or blk_rgb.shape[1] < 4:
                pad = np.zeros((4, 4, 3), dtype=np.uint8)
                pad[:blk_rgb.shape[0], :blk_rgb.shape[1], :] = blk_rgb
                blk_rgb = pad
                pad_a = np.zeros((4, 4), dtype=np.uint8)
                pad_a[:blk_a.shape[0], :blk_a.shape[1]] = blk_a
                blk_a = pad_a
            out += _dxt5_alpha_block(blk_a)
            out += _dxt1_color_block(blk_rgb)
    return bytes(out)


# ============================================================ normalize
def _normalize_image(im: Image.Image, cfg: dict) -> Image.Image:
    if not cfg.get("enabled"):
        return im
    mode = cfg.get("mode", "pow2")
    w, h = im.size

    def _pow2(v):
        return max(1, 1 << (v - 1).bit_length())

    if mode == "pow2":
        nw, nh = _pow2(w), _pow2(h)
    elif mode == "mul4":
        nw = max(4, (w + 3) // 4 * 4)
        nh = max(4, (h + 3) // 4 * 4)
    else:
        nw = max(1, int(cfg.get("w", w)))
        nh = max(1, int(cfg.get("h", h)))

    if (nw, nh) == (w, h):
        return im
    return im.resize((nw, nh), Image.LANCZOS)


# ============================================================ convert
def image_to_edds(src: Path, dst: Path, mip_levels: int = 0,
                  compression: str = "none",
                  normalize: dict | None = None):
    im = Image.open(src).convert("RGBA")
    if normalize:
        im = _normalize_image(im, normalize)
    w, h = im.size

    mips = _make_mip_chain(im, mip_levels)
    mip_count = len(mips)

    if compression == "none":
        header = _pack_dds_header(w, h, mip_count, None)
        body = b"".join(_bgra_bytes(m) for m in mips)
    elif compression in ("dxt1", "dxt5"):
        if not HAS_NUMPY:
            raise RuntimeError("numpy required: pip install numpy")
        four_cc = b"DXT1" if compression == "dxt1" else b"DXT5"
        header = _pack_dds_header(w, h, mip_count, four_cc)
        codec = _dxt1_image if compression == "dxt1" else _dxt5_image
        body = b"".join(codec(m) for m in mips)
    else:
        raise ValueError(f"Unknown compression: {compression}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as f:
        f.write(header)
        f.write(body)

    return w, h, mip_count, compression


def _read_dds_header(path: Path):
    with open(path, "rb") as f:
        head = f.read(128)
    if len(head) < 128 or head[:4] != b"DDS ":
        raise ValueError("Not a DDS file (missing 'DDS ' signature).")
    size, flags, height, width, pitch, depth, mip_count = struct.unpack(
        "<IIIIIII", head[4:32]
    )
    if size != 124:
        raise ValueError(f"Invalid DDS_HEADER size: {size}.")
    pf = struct.unpack("<IIIIIIII", head[76:108])
    _, pf_flags, four_cc, bpp, rmask, gmask, bmask, amask = pf
    four_cc_str = four_cc.to_bytes(4, "little").decode("ascii", "ignore") \
        if four_cc else ""
    return {
        "width": width, "height": height, "mip_count": max(1, mip_count),
        "four_cc": four_cc_str.strip("\x00"), "bpp": bpp,
        "rmask": rmask, "gmask": gmask, "bmask": bmask, "amask": amask,
    }


def edds_to_image(src: Path, dst: Path):
    data = src.read_bytes()
    if len(data) < 128 or data[:4] != b"DDS ":
        raise ValueError("Not a DDS file (missing 'DDS ' signature).")

    info = _read_dds_header(src)
    w, h = info["width"], info["height"]
    four_cc = info["four_cc"]

    if four_cc == "":
        if info["bpp"] != 32 or (
            info["rmask"], info["gmask"], info["bmask"], info["amask"]
        ) != (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000):
            raise ValueError("Only uncompressed BGRA is supported.")
        mip0 = w * h * 4
        raw = data[128:128 + mip0]
        if len(raw) < mip0:
            raise ValueError("File is truncated.")
        b = raw[0::4]; g = raw[1::4]
        r = raw[2::4]; a = raw[3::4]
        rgba = bytearray(mip0)
        rgba[0::4] = r; rgba[1::4] = g
        rgba[2::4] = b; rgba[3::4] = a
        im = Image.frombytes("RGBA", (w, h), bytes(rgba))
    else:
        raise ValueError(
            f"Compressed DDS ({four_cc}) unpacking not supported yet."
        )

    ext = dst.suffix.lower()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if ext in (".jpg", ".jpeg"):
        im.convert("RGB").save(dst, quality=95)
    else:
        im.save(dst)
    return w, h, info["mip_count"]


# ============================================================ helpers
def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def pil_to_pixmap(im: Image.Image) -> QPixmap:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qim = QImage(data, im.width, im.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qim.copy())


def load_fonts(app):
    fonts_dir = _external_dir() / "fonts"
    if not fonts_dir.is_dir():
        internal = _internal_dir()
        if internal is not None:
            fonts_dir = internal / "fonts"
    if not fonts_dir.is_dir():
        return
    for f in fonts_dir.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))


def _ensure_qta():
    global qta, HAS_QTA
    if qta is not None:
        return
    if QApplication.instance() is None:
        HAS_QTA = False
        return
    try:
        import qtawesome as _qta
        qta = _qta
        HAS_QTA = True
    except Exception:
        qta = None
        HAS_QTA = False


# ============================================================ icons
def _qt_ready() -> bool:
    return QApplication.instance() is not None


def _fallback_icon(name: str, color: QColor) -> QIcon:
    s = 18
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    short = name.split(".")[-1]
    if short in ("xmark", "window-close", "times"):
        m = 5
        p.drawLine(m, m, s - m, s - m)
        p.drawLine(s - m, m, m, s - m)
    elif short in ("window-minimize", "minus"):
        p.drawLine(4, s // 2, s - 4, s // 2)
    elif short in ("window-maximize", "square"):
        p.drawRect(4, 4, s - 8, s - 8)
    elif short == "globe":
        p.drawEllipse(3, 3, s - 6, s - 6)
        p.drawLine(s // 2, 3, s // 2, s - 3)
        p.drawEllipse(QRectF(s // 2 - 3, 3, 6, s - 6))
    elif short == "plus":
        p.drawLine(4, s // 2, s - 4, s // 2)
        p.drawLine(s // 2, 4, s // 2, s - 4)
    elif short == "trash":
        p.drawRect(5, 6, s - 10, s - 10)
        p.drawLine(3, 6, s - 3, 6)
    elif short == "check":
        p.drawLine(4, s // 2, s // 2 - 1, s - 5)
        p.drawLine(s // 2 - 1, s - 5, s - 4, 5)
    elif short == "clock":
        p.drawEllipse(3, 3, s - 6, s - 6)
        p.drawLine(s // 2, s // 2, s // 2, 6)
        p.drawLine(s // 2, s // 2, s - 6, s // 2)
    elif short in ("folder-open", "folder"):
        p.drawRect(3, 6, s - 6, s - 10)
        p.drawLine(3, 6, s // 2, 4)
    elif short == "image":
        p.drawRect(3, 4, s - 6, s - 8)
        p.drawEllipse(s - 8, 6, 3, 3)
    elif short == "upload":
        p.drawLine(s // 2, s - 4, s // 2, 5)
        p.drawLine(s // 2, 5, s // 2 - 4, 9)
        p.drawLine(s // 2, 5, s // 2 + 4, 9)
        p.drawLine(4, s - 4, s - 4, s - 4)
    elif short == "gear":
        p.drawEllipse(QRectF(s // 2 - 3, s // 2 - 3, 6, 6))
    elif short == "sun":
        p.drawEllipse(QRectF(s // 2 - 3, s // 2 - 3, 6, 6))
    elif short == "moon":
        path = QPainterPath()
        path.addEllipse(QRectF(3, 3, s - 6, s - 6))
        path.addEllipse(QRectF(7, 1, s - 6, s - 6))
        p.drawPath(path)
    else:
        p.drawEllipse(4, 4, s - 8, s - 8)
    p.end()
    return QIcon(pm)


def ic(name: str, color="#cccccc") -> QIcon:
    if not _qt_ready():
        return QIcon()
    if HAS_QTA and qta is not None:
        try:
            return qta.icon(name, color=color)
        except Exception:
            pass
    return _fallback_icon(name, QColor(color))


def _app_icon(size=64) -> QIcon:
    if not _qt_ready():
        return QIcon()
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(0, 122, 204)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.18, size * 0.18)
    p.setPen(QPen(QColor(255, 255, 255), size * 0.08))
    m = size * 0.22
    p.drawLine(int(m), int(m), int(size - m), int(m))
    p.drawLine(int(m), int(m), int(m), int(size - m))
    p.drawLine(int(m), int(size - m), int(size - m), int(size - m))
    p.drawLine(int(m), int(size / 2), int(size - m - 2), int(size / 2))
    p.end()
    return QIcon(pm)


def status_icon(kind: str, color: QColor) -> QPixmap:
    if not _qt_ready():
        return QPixmap()
    names = {
        "ok": "fa6s.check", "error": "fa6s.xmark",
        "warn": "fa6s.clock", "idle": "fa6s.clock",
        "pending": "fa6s.clock", "running": "fa6s.spinner",
    }
    name = names.get(kind, "fa6s.circle")
    return ic(name, color.name()).pixmap(16, 16)


# ============================================================ overlay
class DropOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._dash_offset = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self):
        self._dash_offset = (self._dash_offset + 1) % 20
        self.update()

    def showEvent(self, e):
        self._timer.start(50)
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(15, 17, 24, 210))
        pen = QPen(QColor(0, 122, 204), 3, Qt.DashLine)
        pen.setDashPattern([6, 4])
        pen.setDashOffset(self._dash_offset)
        p.setPen(pen)
        r = self.rect().adjusted(18, 18, -18, -18)
        p.drawRoundedRect(r, 14, 14)
        p.setPen(QColor(230, 232, 245))
        f = QFont("Inter", 20, QFont.Bold)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, "⤓")


# ============================================================ dialogs
class MessageDialog(QDialog):
    OK = "ok"
    YES_NO = "yes_no"
    YES_NO_CANCEL = "yes_no_cancel"

    def __init__(self, parent, title: str, text: str,
                 buttons: str = OK):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._result = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("dlgContainer")
        outer.addWidget(container)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("dlgTitle")
        lay.addWidget(title_lbl)

        text_lbl = QLabel(text)
        text_lbl.setObjectName("dlgText")
        text_lbl.setWordWrap(True)
        lay.addWidget(text_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        if buttons == self.OK:
            b_ok = QPushButton(tr("btn_ok"))
            b_ok.setObjectName("dlgPrimary")
            b_ok.setCursor(Qt.PointingHandCursor)
            b_ok.clicked.connect(self._on_ok)
            btn_row.addWidget(b_ok)
        elif buttons == self.YES_NO:
            b_no = QPushButton(tr("btn_no"))
            b_no.setObjectName("ghostBtn")
            b_no.setCursor(Qt.PointingHandCursor)
            b_no.clicked.connect(self._on_no)
            b_yes = QPushButton(tr("btn_yes"))
            b_yes.setObjectName("dlgPrimary")
            b_yes.setCursor(Qt.PointingHandCursor)
            b_yes.clicked.connect(self._on_ok)
            btn_row.addWidget(b_no)
            btn_row.addWidget(b_yes)
        else:
            b_cancel = QPushButton(tr("btn_cancel"))
            b_cancel.setObjectName("ghostBtn")
            b_cancel.setCursor(Qt.PointingHandCursor)
            b_cancel.clicked.connect(self._on_cancel)
            b_no = QPushButton(tr("btn_no"))
            b_no.setObjectName("ghostBtn")
            b_no.setCursor(Qt.PointingHandCursor)
            b_no.clicked.connect(self._on_no)
            b_yes = QPushButton(tr("btn_yes"))
            b_yes.setObjectName("dlgPrimary")
            b_yes.setCursor(Qt.PointingHandCursor)
            b_yes.clicked.connect(self._on_ok)
            btn_row.addWidget(b_cancel)
            btn_row.addWidget(b_no)
            btn_row.addWidget(b_yes)

        lay.addLayout(btn_row)

        self.setMinimumWidth(400)
        self.adjustSize()

        dark = parent.is_dark() if hasattr(parent, "is_dark") else True
        t = THEME_DARK if dark else THEME_LIGHT
        self.setStyleSheet(f"""
            #dlgContainer {{
                background: {t['bg']};
                border: 1px solid {t['border']};
                border-radius: 10px;
            }}
            QLabel#dlgTitle {{
                font-size: 15px; font-weight: 700;
                color: {t['text_strong']};
            }}
            QLabel#dlgText {{
                color: {t['text']}; font-size: 13px;
            }}
            QPushButton#dlgPrimary {{
                background: {t['accent']};
                border: none; border-radius: 6px;
                padding: 7px 18px;
                color: #ffffff; font-weight: 600;
            }}
            QPushButton#dlgPrimary:hover {{
                background: {t['accent_hover']};
            }}
            QPushButton#ghostBtn {{
                background: transparent;
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 7px 18px;
                color: {t['text']};
            }}
            QPushButton#ghostBtn:hover {{
                border: 1px solid {t['accent']};
                color: {t['accent']};
            }}
        """)

    def _on_ok(self):
        self._result = "yes"
        self.accept()

    def _on_no(self):
        self._result = "no"
        self.reject()

    def _on_cancel(self):
        self._result = "cancel"
        self.reject()

    def result_str(self) -> str:
        return self._result or "cancel"

    @staticmethod
    def info(parent, title, text):
        d = MessageDialog(parent, title, text, buttons=MessageDialog.OK)
        d.exec()
        return d.result_str()

    @staticmethod
    def warning(parent, title, text):
        d = MessageDialog(parent, title, text, buttons=MessageDialog.OK)
        d.exec()
        return d.result_str()

    @staticmethod
    def critical(parent, title, text):
        d = MessageDialog(parent, title, text, buttons=MessageDialog.OK)
        d.exec()
        return d.result_str()

    @staticmethod
    def question(parent, title, text) -> bool:
        d = MessageDialog(parent, title, text, buttons=MessageDialog.YES_NO)
        d.exec()
        return d.result_str() == "yes"


class InputDialog(QDialog):
    def __init__(self, parent, title: str, label: str, default: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._result = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("dlgContainer")
        outer.addWidget(container)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("dlgTitle")
        lay.addWidget(title_lbl)

        label_lbl = QLabel(label)
        label_lbl.setObjectName("dlgText")
        label_lbl.setWordWrap(True)
        lay.addWidget(label_lbl)

        self.edit = QLineEdit()
        self.edit.setText(default)
        self.edit.setMinimumHeight(34)
        lay.addWidget(self.edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        b_cancel = QPushButton(tr("btn_cancel"))
        b_cancel.setObjectName("ghostBtn")
        b_cancel.setCursor(Qt.PointingHandCursor)
        b_cancel.clicked.connect(self.reject)

        b_ok = QPushButton(tr("btn_ok"))
        b_ok.setObjectName("dlgPrimary")
        b_ok.setCursor(Qt.PointingHandCursor)
        b_ok.clicked.connect(self._on_ok)

        btn_row.addWidget(b_cancel)
        btn_row.addWidget(b_ok)
        lay.addLayout(btn_row)

        self.setMinimumWidth(400)
        self.adjustSize()

        self.edit.returnPressed.connect(self._on_ok)
        self.edit.setFocus()
        self.edit.selectAll()

        dark = parent.is_dark() if hasattr(parent, "is_dark") else True
        t = THEME_DARK if dark else THEME_LIGHT
        self.setStyleSheet(f"""
            #dlgContainer {{
                background: {t['bg']};
                border: 1px solid {t['border']};
                border-radius: 10px;
            }}
            QLabel#dlgTitle {{
                font-size: 15px; font-weight: 700;
                color: {t['text_strong']};
            }}
            QLabel#dlgText {{
                color: {t['text']}; font-size: 13px;
            }}
            QLineEdit {{
                background: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 6px 10px;
                color: {t['text']};
                selection-background-color: {t['accent']};
            }}
            QLineEdit:focus {{
                border: 1px solid {t['accent']};
            }}
            QPushButton#dlgPrimary {{
                background: {t['accent']};
                border: none; border-radius: 6px;
                padding: 7px 18px;
                color: #ffffff; font-weight: 600;
            }}
            QPushButton#dlgPrimary:hover {{
                background: {t['accent_hover']};
            }}
            QPushButton#ghostBtn {{
                background: transparent;
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 7px 18px;
                color: {t['text']};
            }}
            QPushButton#ghostBtn:hover {{
                border: 1px solid {t['accent']};
                color: {t['accent']};
            }}
        """)

    def _on_ok(self):
        self._result = self.edit.text()
        self.accept()

    def result_str(self) -> str:
        return self._result or ""


# ============================================================ titlebar
class TitleBar(QFrame):
    theme_toggled = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("titlebar")
        self.setFixedHeight(42)
        self._drag_pos = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(22, 22)
        # пробуем взять icon.ico
        _ico = _external_dir() / "icon.ico"
        if not _ico.exists():
            _internal = _internal_dir()
            if _internal is not None:
                _ico = _internal / "icon.ico"
        if _ico.exists():
            _pm = QIcon(str(_ico)).pixmap(22, 22)
            if not _pm.isNull():
                icon_lbl.setPixmap(_pm)
            else:
                icon_lbl.setPixmap(_app_icon(22).pixmap(22, 22))
        else:
            icon_lbl.setPixmap(_app_icon(22).pixmap(22, 22))
        title = QLabel(APP_NAME)
        title.setObjectName("titleText")

        lay.addWidget(icon_lbl)
        lay.addWidget(title)
        lay.addStretch(1)

        self.btn_lang = QPushButton()
        self.btn_lang.setObjectName("titleLangBtn")
        self.btn_lang.setFixedSize(52, 30)
        self.btn_lang.setCursor(Qt.PointingHandCursor)
        self.btn_lang.setFlat(True)
        self.btn_lang.setToolTip(tr("lang_menu_tooltip"))
        self.btn_lang.clicked.connect(self._show_language_menu)

        self.btn_about = QPushButton("i")
        self.btn_about.setObjectName("titleBtn")
        self.btn_about.setFixedSize(30, 30)
        self.btn_about.setCursor(Qt.PointingHandCursor)
        self.btn_about.setFlat(True)
        self.btn_about.setToolTip(tr("about_title"))
        self.btn_about.clicked.connect(self.window._show_about)

        self.btn_theme = QPushButton()
        self.btn_theme.setObjectName("titleBtn")
        self.btn_theme.setFixedSize(38, 30)
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.setFlat(True)
        self.btn_theme.setToolTip(tr("theme_toggle"))
        self.btn_theme.clicked.connect(self.theme_toggled.emit)

        self.btn_min = QPushButton(); self.btn_min.setObjectName("titleBtn")
        self.btn_max = QPushButton(); self.btn_max.setObjectName("titleBtn")
        self.btn_close = QPushButton(); self.btn_close.setObjectName("titleBtnClose")
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.setFixedSize(46, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setFlat(True)

        lay.addWidget(self.btn_lang)
        lay.addWidget(self.btn_about)
        lay.addWidget(self.btn_theme)
        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_max)
        lay.addWidget(self.btn_close)

        self.btn_min.clicked.connect(self.window.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(self.window.close)

    def _current_lang_code(self) -> str:
        if TR is None:
            return "RU"
        cur = TR.current_lang()
        for code, _, short in LANGUAGES:
            if code == cur:
                return short
        return cur.upper()

    def refresh_lang_button(self):
        self.btn_lang.setText(self._current_lang_code())

    def _show_language_menu(self):
        menu = QMenu(self)
        current = TR.current_lang() if TR else "en"
        for code, native, short in LANGUAGES:
            act = QAction(f"{native}  ({short})", self)
            act.setCheckable(True)
            act.setChecked(code == current)
            act.triggered.connect(
                lambda _, c=code: self.window.change_language(c)
            )
            menu.addAction(act)
        menu.exec(self.btn_lang.mapToGlobal(
            QPoint(0, self.btn_lang.height())
        ))

    def refresh_icons(self, dark: bool):
        c = "#cccccc" if dark else "#3c3c3c"
        self.btn_min.setIcon(ic("fa6s.window-minimize", c))
        self.btn_max.setIcon(ic("fa6s.window-maximize", c))
        self.btn_close.setIcon(ic("fa6s.xmark", c))
        self.btn_theme.setIcon(ic("fa6s.sun" if dark else "fa6s.moon", c))
        for b in (self.btn_min, self.btn_max, self.btn_close, self.btn_theme):
            b.setIconSize(QSize(18, 18))

    def _toggle_max(self):
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()
        self.refresh_icons(self.window.is_dark())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint()
                - self.window.frameGeometry().topLeft()
            )
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            if self.window.isMaximized():
                self.window.showNormal()
            self.window.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggle_max()


# ============================================================ status bar
class StatusBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("statusBar")
        self.setFixedHeight(28)
        self._dark = True
        self._color_state = "idle"

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.text = QLabel(tr("status_ready"))
        self.text.setObjectName("statusText")
        self.counter = QLabel("0/0")
        self.counter.setObjectName("statusCounter")
        self.copyright_lbl = QLabel(tr("window_copyright"))
        self.copyright_lbl.setObjectName("statusCopyright")
        self.busy = QLabel()
        self.busy.setFixedSize(16, 16)

        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.counter)
        lay.addWidget(self.copyright_lbl)
        lay.addWidget(self.busy)

        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._spin)
        self.set_colors(True)

    def set_state(self, kind: str, text: str):
        self.text.setText(text)
        self._color_state = kind
        self.set_colors(self._dark)

    def set_colors(self, dark: bool):
        self._dark = dark
        c_ok = QColor(78, 201, 176) if dark else QColor(22, 130, 93)
        c_err = QColor(241, 76, 76) if dark else QColor(205, 49, 49)
        c_warn = QColor(220, 220, 170) if dark else QColor(181, 137, 0)
        c_idle = QColor(133, 133, 133)
        col_map = {"ok": c_ok, "error": c_err, "warn": c_warn, "idle": c_idle}
        col = col_map.get(self._color_state, c_idle)
        pm = status_icon(self._color_state, col)
        if not pm.isNull():
            self.icon.setPixmap(pm)

    def set_counter(self, cur: int, total: int):
        self.counter.setText(f"{cur}/{total}")

    def set_busy(self, busy: bool):
        if busy:
            self._timer.start(80)
        else:
            self._timer.stop()
            self.busy.setPixmap(QPixmap())

    def _spin(self):
        self._angle = (self._angle + 30) % 360
        pm = status_icon("running", QColor(0, 122, 204))
        if not pm.isNull():
            self.busy.setPixmap(pm)


# ============================================================ section card
class SectionCard(QFrame):
    def __init__(self, icon_kind: str, title: str, dark: bool = True):
        super().__init__()
        self.setObjectName("card")
        self._icon_kind = icon_kind

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(18, 18)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("cardTitle")
        head.addWidget(self.icon_lbl)
        head.addWidget(self.title_lbl)
        head.addStretch(1)
        outer.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(18)
        self._shadow.setOffset(0, 3)
        self._shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(self._shadow)

        self.refresh(dark)

    def set_title(self, text: str):
        self.title_lbl.setText(text)

    def refresh(self, dark: bool):
        c = "#cccccc" if dark else "#3c3c3c"
        kind_map = {
            "folder": "fa6s.folder-open", "image": "fa6s.image",
            "upload": "fa6s.upload", "gear": "fa6s.gear",
            "sun": "fa6s.sun", "moon": "fa6s.moon", "film": "fa6s.film",
        }
        icon_name = kind_map.get(self._icon_kind, "fa6s.circle")
        pm = ic(icon_name, c).pixmap(18, 18)
        if not pm.isNull():
            self.icon_lbl.setPixmap(pm)
        self._shadow.setColor(QColor(0, 0, 0, 70 if dark else 25))


# ============================================================ preview
class PreviewThumb(QWidget):
    clicked = Signal()

    def __init__(self, size=150):
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._pm = None
        self._placeholder = "—"
        self._bg = QColor("#2a2a2a")
        self._border = QColor("#3e3e42")
        self._text_col = QColor("#858585")

    def set_colors(self, dark: bool):
        self._bg = QColor("#2a2a2a") if dark else QColor("#eeeeee")
        self._border = QColor("#3e3e42") if dark else QColor("#dcdcdc")
        self._text_col = QColor("#858585") if dark else QColor("#6a6a6a")
        self.update()

    def set_pixmap(self, pm):
        self._pm = pm
        self.update()

    def set_placeholder(self, text: str):
        self._placeholder = text
        self._pm = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._pm is not None:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0.5, 0.5, self._size - 1, self._size - 1), 12, 12
        )
        p.fillPath(path, self._bg)
        if self._pm is not None:
            p.save()
            p.setClipPath(path)
            scaled = self._pm.scaled(
                self._size - 8, self._size - 8,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            x = (self._size - scaled.width()) // 2
            y = (self._size - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
            p.restore()
        else:
            p.setPen(self._text_col)
            p.setFont(QFont("Inter", 10))
            p.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
        p.setPen(QPen(self._border, 1))
        p.drawPath(path)


class PreviewPane(SectionCard):
    open_viewer = Signal()

    def __init__(self, dark=True):
        super().__init__("image", tr("card_preview"), dark)
        row = QHBoxLayout()
        row.setSpacing(14)

        self.thumb = PreviewThumb(150)
        self.thumb.clicked.connect(self.open_viewer.emit)
        row.addWidget(self.thumb)

        info = QVBoxLayout()
        info.setSpacing(6)
        self.lbl_name = QLabel("—")
        self.lbl_name.setObjectName("fileName")
        self.lbl_name.setWordWrap(True)
        self.lbl_dims = QLabel("")
        self.lbl_dims.setObjectName("fileMeta")
        self.lbl_size = QLabel("")
        self.lbl_size.setObjectName("fileMeta")
        info.addWidget(self.lbl_name)
        info.addWidget(self.lbl_dims)
        info.addWidget(self.lbl_size)
        info.addStretch(1)
        row.addLayout(info, 1)

        self.body.addLayout(row)
        self._full = None
        self._path: Path | None = None

    def current_path(self):
        return self._path

    def clear(self):
        self._full = None
        self._path = None
        self.thumb.set_placeholder("—")
        self.lbl_name.setText("—")
        self.lbl_dims.setText("")
        self.lbl_size.setText("")

    def load(self, path: Path):
        self.clear()
        self._path = path
        if not path.exists():
            return
        try:
            size_bytes = path.stat().st_size
            self.lbl_size.setText(human_size(size_bytes))
            self.lbl_name.setText(path.name)
            ext = path.suffix.lower()
            if ext in RASTER_EXT:
                im = Image.open(path)
                im.load()
                w, h = im.size
                self.lbl_dims.setText(f"{w} × {h}")
                self._full = pil_to_pixmap(im)
                self.thumb.set_pixmap(self._full)
            elif ext in EDDS_EXT:
                info = _read_dds_header(path)
                w, h = info["width"], info["height"]
                cc = info["four_cc"] or "BGRA"
                self.lbl_dims.setText(
                    f"{w} × {h}  ·  mips: {info['mip_count']}  ·  {cc}"
                )
                if not info["four_cc"]:
                    with open(path, "rb") as f:
                        f.seek(128)
                        raw = f.read(w * h * 4)
                    b = raw[0::4]; g = raw[1::4]
                    r = raw[2::4]; a = raw[3::4]
                    rgba = bytearray(len(raw))
                    rgba[0::4] = r; rgba[1::4] = g
                    rgba[2::4] = b; rgba[3::4] = a
                    im = Image.frombytes("RGBA", (w, h), bytes(rgba))
                    self._full = pil_to_pixmap(im)
                    self.thumb.set_pixmap(self._full)
                else:
                    self.thumb.set_placeholder(f"{cc}")
            elif ext in PAA_EXT:
                self.lbl_dims.setText("PAA")
                self.thumb.set_placeholder("PAA")
            else:
                self.lbl_dims.setText("unsupported")
        except Exception as e:
            self.thumb.set_placeholder("error")
            self.lbl_dims.setText(str(e)[:80])


# ============================================================ file list
class FileListWidget(QListWidget):
    paths_added = Signal(list)
    current_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setMinimumHeight(140)
        self.currentRowChanged.connect(self._emit_current)
        self._dark = True
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._refresh_running)
        self._spin_timer.start(200)

    def set_dark(self, dark: bool):
        self._dark = dark
        self._refresh_all_icons()

    def paths(self):
        return [Path(self.item(i).data(Qt.UserRole))
                for i in range(self.count())]

    def add_paths(self, paths: list[Path]):
        existing = {str(p) for p in self.paths()}
        added = []
        for p in paths:
            if str(p) in existing:
                continue
            item = QListWidgetItem(p.name)
            item.setToolTip(str(p))
            item.setData(Qt.UserRole, str(p))
            item.setData(Qt.UserRole + 1, "pending")
            item.setData(Qt.UserRole + 2, "")
            self.addItem(item)
            self._apply_status(item, "pending")
            added.append(p)
        if self.count() and self.currentRow() < 0:
            self.setCurrentRow(0)
        if added:
            self.paths_added.emit(added)

    def clear_all(self):
        self.clear()

    def mark_status(self, path: Path, status: str, tooltip_extra: str = ""):
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) == str(path):
                it = self.item(i)
                it.setData(Qt.UserRole + 1, status)
                if tooltip_extra:
                    it.setData(Qt.UserRole + 2, tooltip_extra)
                    it.setToolTip(f"{path}\n{tooltip_extra}")
                self._apply_status(it, status)
                break

    def _apply_status(self, item, status: str):
        c_ok = QColor(78, 201, 176) if self._dark else QColor(22, 130, 93)
        c_err = QColor(241, 76, 76) if self._dark else QColor(205, 49, 49)
        c_pend = QColor(133, 133, 133)
        c_run = QColor(0, 122, 204)
        col_map = {"ok": c_ok, "error": c_err, "running": c_run, "pending": c_pend}
        pm = status_icon(status, col_map.get(status, c_pend))
        if not pm.isNull():
            item.setIcon(QIcon(pm))

    def _refresh_all_icons(self):
        for i in range(self.count()):
            it = self.item(i)
            self._apply_status(it, it.data(Qt.UserRole + 1) or "pending")

    def _refresh_running(self):
        for i in range(self.count()):
            it = self.item(i)
            if it.data(Qt.UserRole + 1) == "running":
                self._apply_status(it, "running")

    def _emit_current(self, row: int):
        if row < 0:
            self.current_changed.emit(None)
        else:
            self.current_changed.emit(Path(self.item(row).data(Qt.UserRole)))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if not e.mimeData().hasUrls():
            super().dropEvent(e)
            return
        paths = []
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file():
                paths.append(p)
        if paths:
            self.paths_added.emit(paths)
        e.acceptProposedAction()


# ============================================================ image viewer
class ImageViewer(QDialog):
    def __init__(self, parent, paths: list[Path], start_index: int = 0):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)

        self._paths = [p for p in paths
                       if p.suffix.lower() in RASTER_EXT | EDDS_EXT]
        self._index = max(0, min(start_index, len(self._paths) - 1))
        self._zoom = 1.0
        self._offset = QPoint(0, 0)
        self._drag_origin = None
        self._pm = None

        self._build_ui()
        self.resize(900, 700)
        self._load_current()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("viewerContainer")
        outer.addWidget(self.container)

        lay = QVBoxLayout(self.container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("viewerBar")
        bar.setFixedHeight(40)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 0, 8, 0)
        self.lbl_title = QLabel("")
        self.lbl_title.setObjectName("viewerTitle")
        bl.addWidget(self.lbl_title, 1)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_in = QPushButton("+")
        self.btn_fit = QPushButton(tr("viewer_fit"))
        self.btn_100 = QPushButton("100%")
        self.btn_close = QPushButton()
        self.btn_close.setIcon(ic("fa6s.xmark", "#cccccc"))
        self.btn_close.setIconSize(QSize(16, 16))
        for b in (self.btn_zoom_out, self.btn_zoom_in,
                  self.btn_fit, self.btn_100):
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName("viewerBtn")
        self.btn_close.setFixedSize(38, 28)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setObjectName("titleBtnClose")
        self.btn_close.setFlat(True)

        bl.addWidget(self.btn_zoom_out)
        bl.addWidget(self.btn_zoom_in)
        bl.addWidget(self.btn_fit)
        bl.addWidget(self.btn_100)
        bl.addWidget(self.btn_close)
        lay.addWidget(bar)

        self.canvas = QWidget()
        self.canvas.setObjectName("viewerCanvas")
        self.canvas.setMouseTracking(True)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.installEventFilter(self)
        lay.addWidget(self.canvas, 1)

        footer = QFrame()
        footer.setObjectName("viewerBar")
        footer.setFixedHeight(40)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 0, 12, 0)
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.lbl_counter = QLabel("")
        self.lbl_counter.setObjectName("viewerCounter")
        for b in (self.btn_prev, self.btn_next):
            b.setFixedSize(48, 28)
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName("viewerBtn")
        fl.addWidget(self.btn_prev)
        fl.addWidget(self.btn_next)
        fl.addStretch(1)
        fl.addWidget(self.lbl_counter)
        lay.addWidget(footer)

        self.btn_close.clicked.connect(self.close)
        self.btn_zoom_in.clicked.connect(
            lambda: self._set_zoom(self._zoom * 1.25))
        self.btn_zoom_out.clicked.connect(
            lambda: self._set_zoom(self._zoom / 1.25))
        self.btn_fit.clicked.connect(self._fit)
        self.btn_100.clicked.connect(lambda: self._set_zoom(1.0))
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next.clicked.connect(lambda: self._step(+1))

        QShortcut(QKeySequence(Qt.Key_Escape), self, self.close)
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self._step(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self._step(+1))
        QShortcut(QKeySequence("Ctrl+0"), self, lambda: self._set_zoom(1.0))
        QShortcut(QKeySequence("Ctrl+9"), self, self._fit)

    def _load_current(self):
        if not self._paths:
            self.lbl_title.setText("—")
            self._pm = None
            self.canvas.update()
            return
        p = self._paths[self._index]
        self.lbl_title.setText(p.name)
        self.lbl_counter.setText(f"{self._index + 1} / {len(self._paths)}")
        self.btn_prev.setEnabled(self._index > 0)
        self.btn_next.setEnabled(self._index < len(self._paths) - 1)

        try:
            ext = p.suffix.lower()
            if ext in RASTER_EXT:
                im = Image.open(p)
                im.load()
                self._pm = pil_to_pixmap(im)
            else:
                info = _read_dds_header(p)
                if info["four_cc"]:
                    self._pm = None
                else:
                    w, h = info["width"], info["height"]
                    with open(p, "rb") as f:
                        f.seek(128)
                        raw = f.read(w * h * 4)
                    b = raw[0::4]; g = raw[1::4]
                    r = raw[2::4]; a = raw[3::4]
                    rgba = bytearray(len(raw))
                    rgba[0::4] = r; rgba[1::4] = g
                    rgba[2::4] = b; rgba[3::4] = a
                    im = Image.frombytes("RGBA", (w, h), bytes(rgba))
                    self._pm = pil_to_pixmap(im)
        except Exception as e:
            self.lbl_title.setText(f"{p.name} — error: {e}")
            self._pm = None

        self._fit()

    def _step(self, delta: int):
        if not self._paths:
            return
        ni = self._index + delta
        if 0 <= ni < len(self._paths):
            self._index = ni
            self._load_current()

    def _set_zoom(self, z: float):
        self._zoom = max(VIEWER_MIN_ZOOM, min(VIEWER_MAX_ZOOM, z))
        self.canvas.update()

    def _fit(self):
        if self._pm is None:
            return
        cw = max(1, self.canvas.width() - 20)
        ch = max(1, self.canvas.height() - 20)
        zx = cw / self._pm.width()
        zy = ch / self._pm.height()
        self._zoom = max(VIEWER_MIN_ZOOM, min(VIEWER_MAX_ZOOM, min(zx, zy)))
        self._offset = QPoint(0, 0)
        self.canvas.update()

    def eventFilter(self, obj, e):
        if obj is not self.canvas:
            return super().eventFilter(obj, e)
        if e.type() == QEvent.Paint:
            self._paint_canvas()
            return True
        if e.type() == QEvent.Wheel:
            delta = e.angleDelta().y()
            if delta > 0:
                self._set_zoom(self._zoom * VIEWER_ZOOM_STEP)
            else:
                self._set_zoom(self._zoom / VIEWER_ZOOM_STEP)
            return True
        if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            self._drag_origin = (e.position().toPoint(), QPoint(self._offset))
            self.canvas.setCursor(Qt.ClosedHandCursor)
            return True
        if e.type() == QEvent.MouseMove and self._drag_origin is not None:
            start, off0 = self._drag_origin
            delta = e.position().toPoint() - start
            self._offset = off0 + delta
            self.canvas.update()
            return True
        if e.type() == QEvent.MouseButtonRelease:
            self._drag_origin = None
            self.canvas.unsetCursor()
            return True
        if e.type() == QEvent.Resize:
            self.canvas.update()
            return True
        return super().eventFilter(obj, e)

    def _paint_canvas(self):
        p = QPainter(self.canvas)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.canvas.rect(), QColor(20, 20, 20))
        if self._pm is None:
            p.setPen(QColor(180, 180, 180))
            p.setFont(QFont("Inter", 12))
            p.drawText(self.canvas.rect(), Qt.AlignCenter, "—")
            p.end()
            return
        w = int(self._pm.width() * self._zoom)
        h = int(self._pm.height() * self._zoom)
        x = (self.canvas.width() - w) // 2 + self._offset.x()
        y = (self.canvas.height() - h) // 2 + self._offset.y()
        p.drawPixmap(x, y, w, h, self._pm)
        p.end()


# ============================================================ about dialog
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about_title"))
        self.setFixedSize(600, 520)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("aboutContainer")
        outer.addWidget(container)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(10)

        title = QLabel(f"{APP_NAME}  v{APP_VERSION}")
        title.setObjectName("aboutTitle")
        lay.addWidget(title)

        desc = QLabel(tr("about_product"))
        desc.setObjectName("aboutDesc")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setObjectName("aboutSep")
        lay.addWidget(sep1)

        cr = QLabel(tr("about_copyright"))
        cr.setObjectName("aboutCopyright")
        cr.setWordWrap(True)
        lay.addWidget(cr)

        bi = QLabel(tr("about_bi_disclaimer"))
        bi.setObjectName("aboutBi")
        bi.setWordWrap(True)
        lay.addWidget(bi)

        eula = QLabel(tr("about_eula"))
        eula.setObjectName("aboutEula")
        eula.setWordWrap(True)
        lay.addWidget(eula)

        paa = QLabel(tr("about_paa_note"))
        paa.setObjectName("aboutPaa")
        paa.setWordWrap(True)
        lay.addWidget(paa)

        lay.addStretch(1)

        btn_close = QPushButton(tr("btn_close"))
        btn_close.setObjectName("ghostBtn")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.close)
        lay.addWidget(btn_close, 0, Qt.AlignRight)

        dark = parent.is_dark() if hasattr(parent, "is_dark") else True
        t = THEME_DARK if dark else THEME_LIGHT
        self.setStyleSheet(f"""
            #aboutContainer {{
                background: {t['bg']};
                border: 1px solid {t['border']};
                border-radius: 10px;
            }}
            #aboutTitle {{
                font-size: 18px; font-weight: 700;
                color: {t['text_strong']};
            }}
            #aboutDesc {{ color: {t['text']}; font-size: 12px; }}
            #aboutCopyright {{
                color: {t['text']}; font-size: 12px; font-weight: 600;
            }}
            #aboutBi, #aboutEula, #aboutPaa {{
                color: {t['text_dim']}; font-size: 11px;
            }}
            #aboutSep {{
                background: {t['divider']};
                border: none;
                max-height: 1px;
            }}
            QPushButton#ghostBtn {{
                background: transparent;
                border: 1px solid {t['input_border']};
                border-radius: 6px;
                padding: 6px 16px;
                color: {t['text']};
            }}
            QPushButton#ghostBtn:hover {{
                border: 1px solid {t['accent']};
                color: {t['accent']};
            }}
        """)


# ============================================================ main window
class MainWindow(QWidget):
    MODE_IMG_TO_EDDS = "img_to_edds"
    MODE_EDDS_TO_IMG = "edds_to_img"
    MODE_IMG_TO_PAA = "img_to_paa"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1040, 740)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)

        self.settings = load_settings()
        self._dark = self.settings.get("theme", "dark") == "dark"
        self._mode = self.settings.get("last_mode", "img_to_edds")
        self._paths: list[Path] = []
        self._cancel_requested = False
        self._running = False
        self._force_quit = False

        self._imagetopaa = (self.settings.get("imagetopaa_path", "")
                            or find_imagetopaa())
        if self._imagetopaa:
            self.settings["imagetopaa_path"] = self._imagetopaa

        self._build_tray()
        self._build_ui()
        self._apply_style()
        self._load_settings_to_ui()
        self._update_mode_ui()

    # -------------------------------------------------- tray
    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
    
        # ✅ иконка трея — из icon.ico, если есть
        tray_icon = QIcon()
        ico_path = _external_dir() / "tray.ico"
        if not ico_path.exists():
            ico_path = _external_dir() / "icon.ico"
        if not ico_path.exists():
            internal = _internal_dir()
            if internal is not None:
                ico_path = internal / "icon.ico"
        if ico_path.exists():
            tray_icon = QIcon(str(ico_path))
        if tray_icon.isNull():
            tray_icon = _app_icon(64)   # fallback — нарисованная
    
        self.tray = QSystemTrayIcon(tray_icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        act_show = QAction(tr("tray_show"), self)
        act_show.triggered.connect(self._show_from_tray)
        act_about = QAction(tr("tray_about"), self)
        act_about.triggered.connect(self._show_about)
        act_quit = QAction(tr("tray_quit"), self)
        act_quit.triggered.connect(self._quit_app)
        menu.addAction(act_show)
        menu.addAction(act_about)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self):
        self._force_quit = True
        QApplication.quit()

    def _show_about(self):
        AboutDialog(self).exec()

    def _notify(self, title: str, msg: str):
        if self.tray:
            self.tray.showMessage(title, msg, self.tray.icon(), msecs=4000)
        else:
            self.status.set_state("ok", msg)

    # -------------------------------------------------- UI
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("container")
        outer.addWidget(self.container)

        root = QVBoxLayout(self.container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self)
        self.titlebar.theme_toggled.connect(self.toggle_theme)
        root.addWidget(self.titlebar)

        body = QWidget()
        root.addWidget(body, 1)
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(18, 14, 18, 12)
        body_lay.setSpacing(16)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(12)

        self.btn_mode = QPushButton()
        self.btn_mode.setObjectName("modeToggle")
        self.btn_mode.setMinimumHeight(42)
        self.btn_mode.setCursor(Qt.PointingHandCursor)
        self.btn_mode.clicked.connect(self.toggle_mode)
        left_lay.addWidget(self.btn_mode)

        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setObjectName("subtitle")
        left_lay.addWidget(self.lbl_subtitle)

        self.src_card = SectionCard("folder", tr("card_sources"), self._dark)
        row_src = QHBoxLayout()
        self.src_edit = QLineEdit()
        self.src_edit.setMinimumHeight(34)
        self.src_edit.setReadOnly(True)
        self.src_edit.setAcceptDrops(False)
        self.src_edit.setPlaceholderText(tr("src_placeholder"))
        self.btn_add = QPushButton()
        self.btn_add.setIcon(ic("fa6s.plus", "#cccccc"))
        self.btn_add.setIconSize(QSize(14, 14))
        self.btn_add.setText(" " + tr("btn_add"))
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setObjectName("ghostBtn")
        self.btn_add.clicked.connect(self.pick_src)
        self.btn_clear = QPushButton()
        self.btn_clear.setIcon(ic("fa6s.trash", "#cccccc"))
        self.btn_clear.setIconSize(QSize(14, 14))
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setObjectName("ghostBtn")
        self.btn_clear.clicked.connect(self._clear_sources)
        row_src.addWidget(self.src_edit, 1)
        row_src.addWidget(self.btn_add)
        row_src.addWidget(self.btn_clear)
        self.src_card.body.addLayout(row_src)

        self.file_list = FileListWidget()
        self.file_list.paths_added.connect(self._on_paths_added)
        self.file_list.current_changed.connect(self._on_current_changed)
        self.src_card.body.addWidget(self.file_list)
        left_lay.addWidget(self.src_card)

        self.preview = PreviewPane(self._dark)
        self.preview.open_viewer.connect(self._open_viewer)
        left_lay.addWidget(self.preview)

        left_lay.addStretch(1)

        right = QWidget()
        right.setFixedWidth(380)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(12)

        self.profile_card = SectionCard("gear", tr("card_profile"), self._dark)
        prow = QHBoxLayout()
        self.cmb_profile = QComboBox()
        self.cmb_profile.addItem(tr("profile_default"))
        self.cmb_profile.currentIndexChanged.connect(self._profile_selected)
        prow.addWidget(self.cmb_profile, 1)
        self.profile_card.body.addLayout(prow)

        prow2 = QHBoxLayout()
        self.btn_pnew = QPushButton(tr("profile_new"))
        self.btn_pnew.setCursor(Qt.PointingHandCursor)
        self.btn_pnew.setObjectName("ghostBtn")
        self.btn_pnew.clicked.connect(self._profile_new)
        self.btn_psave = QPushButton(tr("profile_save_btn"))
        self.btn_psave.setCursor(Qt.PointingHandCursor)
        self.btn_psave.setObjectName("ghostBtn")
        self.btn_psave.clicked.connect(self._profile_save)
        self.btn_psave.setEnabled(False)
        self.btn_pdel = QPushButton(tr("profile_delete_btn"))
        self.btn_pdel.setCursor(Qt.PointingHandCursor)
        self.btn_pdel.setObjectName("ghostBtnDanger")
        self.btn_pdel.clicked.connect(self._profile_delete)
        self.btn_pdel.setEnabled(False)
        prow2.addWidget(self.btn_pnew)
        prow2.addWidget(self.btn_psave)
        prow2.addWidget(self.btn_pdel)
        self.profile_card.body.addLayout(prow2)
        right_lay.addWidget(self.profile_card)

        self.mip_card = SectionCard("gear", tr("card_mips"), self._dark)
        mrow = QHBoxLayout()
        self.chk_mips = QCheckBox(tr("chk_mips"))
        self.chk_mips.toggled.connect(self._on_mips_toggled)
        self.cmb_mips = QComboBox()
        self.cmb_mips.addItems(
            ["x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8"]
        )
        self.cmb_mips.currentIndexChanged.connect(self._update_mip_hint)
        self.lbl_mip_hint = QLabel(tr("mips_none"))
        self.lbl_mip_hint.setObjectName("hint")
        self.lbl_mip_hint.setWordWrap(True)
        mrow.addWidget(self.chk_mips)
        mrow.addWidget(self.cmb_mips)
        mrow.addStretch(1)
        self.mip_card.body.addLayout(mrow)
        self.mip_card.body.addWidget(self.lbl_mip_hint)
        right_lay.addWidget(self.mip_card)

        self.comp_card = SectionCard("image", tr("card_compression"), self._dark)
        crow = QHBoxLayout()
        self.cmb_comp = QComboBox()
        self.cmb_comp.addItems([
            tr("comp_none"), tr("comp_dxt1"), tr("comp_dxt5"),
        ])
        if not HAS_NUMPY:
            self.cmb_comp.setToolTip(tr("comp_need_numpy"))
        self.cmb_comp.currentIndexChanged.connect(self._on_comp_changed)
        crow.addWidget(self.cmb_comp, 1)
        self.comp_card.body.addLayout(crow)
        self.lbl_comp_hint = QLabel("")
        self.lbl_comp_hint.setObjectName("hint")
        self.lbl_comp_hint.setWordWrap(True)
        self.comp_card.body.addWidget(self.lbl_comp_hint)
        right_lay.addWidget(self.comp_card)

        self.norm_card = SectionCard(
            "image", tr("card_normalize"), self._dark
        )
        nrow = QHBoxLayout()
        self.chk_norm = QCheckBox(tr("norm_enabled"))
        self.chk_norm.toggled.connect(self._on_norm_toggled)
        self.cmb_norm = QComboBox()
        self.cmb_norm.addItems([
            tr("norm_pow2"), tr("norm_mul4"), tr("norm_custom"),
        ])
        self.cmb_norm.currentIndexChanged.connect(self._on_norm_mode_changed)
        nrow.addWidget(self.chk_norm)
        nrow.addWidget(self.cmb_norm, 1)
        self.norm_card.body.addLayout(nrow)

        nrow2 = QHBoxLayout()
        self.spin_w = QSpinBox()
        self.spin_w.setRange(1, 16384)
        self.spin_h = QSpinBox()
        self.spin_h.setRange(1, 16384)
        self.spin_w.setValue(1024)
        self.spin_h.setValue(1024)
        nrow2.addWidget(QLabel("W"))
        nrow2.addWidget(self.spin_w)
        nrow2.addWidget(QLabel("H"))
        nrow2.addWidget(self.spin_h)
        self.norm_card.body.addLayout(nrow2)
        right_lay.addWidget(self.norm_card)

        self.dst_card = SectionCard("upload", tr("card_destination"), self._dark)
        drow = QHBoxLayout()
        self.dst_edit = QLineEdit()
        self.dst_edit.setMinimumHeight(34)
        self.dst_edit.setAcceptDrops(False)
        self.dst_edit.setPlaceholderText(tr("dst_placeholder"))
        self.btn_dst = QPushButton(tr("btn_browse"))
        self.btn_dst.setCursor(Qt.PointingHandCursor)
        self.btn_dst.setObjectName("ghostBtn")
        self.btn_dst.clicked.connect(self.pick_dst)
        drow.addWidget(self.dst_edit, 1)
        drow.addWidget(self.btn_dst)
        self.dst_card.body.addLayout(drow)
        self.lbl_dst_hint = QLabel("")
        self.lbl_dst_hint.setObjectName("hint")
        self.lbl_dst_hint.setWordWrap(True)
        self.dst_card.body.addWidget(self.lbl_dst_hint)

        self.chk_open_folder = QCheckBox(tr("chk_open_folder"))
        self.chk_open_folder.setChecked(True)
        self.dst_card.body.addWidget(self.chk_open_folder)
        right_lay.addWidget(self.dst_card)

        right_lay.addStretch(1)

        self.btn_convert = QPushButton(tr("btn_convert"))
        self.btn_convert.setObjectName("convert")
        self.btn_convert.setMinimumHeight(48)
        self.btn_convert.setCursor(Qt.PointingHandCursor)
        self.btn_convert.clicked.connect(self.convert_clicked)
        right_lay.addWidget(self.btn_convert)

        body_lay.addWidget(left, 1)
        body_lay.addWidget(right, 0)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        root.addWidget(self.progress)

        self.status = StatusBar()
        root.addWidget(self.status)

        self.overlay = DropOverlay(self)

        self._grip = QSizeGrip(self.container)
        self._grip.setFixedSize(16, 16)
        self._grip.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        g = self._grip
        g.move(self.container.width() - g.width() - 2,
               self.container.height() - g.height() - 2)

    # -------------------------------------------------- style
    def is_dark(self) -> bool:
        return self._dark

    def _t(self) -> dict:
        return THEME_DARK if self._dark else THEME_LIGHT

    def _apply_style(self):
        t = self._t()
        qss = """
            #container {
                background: %(bg)s;
                border: none;
                border-radius: 10px;
            }
            QWidget {
                color: %(text)s;
                font-family: 'Inter', 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            #titlebar {
                background: %(panel)s;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom: 1px solid %(divider)s;
            }
            #titleText { font-weight: 600; color: %(text_strong)s; }
            #titleBtn, #titleBtnClose {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 0;
            }
            #titleBtn:hover { background: %(input_bg)s; }
            #titleBtnClose:hover { background: %(danger)s; }
            #titleLangBtn {
                background: transparent;
                border: 1px solid %(input_border)s;
                border-radius: 4px;
                padding: 0;
                color: %(text)s;
                font-size: 11px;
                font-weight: 700;
            }
            #titleLangBtn:hover {
                background: %(input_bg)s;
                border: 1px solid %(accent)s;
                color: %(accent)s;
            }

            QLabel#subtitle { color: %(text_dim)s; }
            QLabel#cardTitle {
                font-weight: 600;
                font-size: 11px;
                color: %(text_dim)s;
                letter-spacing: 0.5px;
            }
            QLabel#hint { color: %(text_dim)s; font-size: 12px; }
            QLabel#fileName {
                font-size: 14px;
                font-weight: 600;
                color: %(text_strong)s;
            }
            QLabel#fileMeta { color: %(text_dim)s; }

            #card, #statusBar {
                background: %(panel)s;
                border: 1px solid %(border)s;
                border-radius: 10px;
            }
            #statusBar {
                border-radius: 0;
                border-left: none; border-right: none; border-bottom: none;
            }
            QLabel#statusText { color: %(text)s; }
            QLabel#statusCounter { color: %(text_dim)s; }
            QLabel#statusCopyright {
                color: %(text_dim)s;
                font-size: 11px;
                padding-left: 12px;
            }

            QLineEdit, QComboBox, QSpinBox {
                background: %(input_bg)s;
                border: 1px solid %(input_border)s;
                border-radius: 6px;
                padding: 6px 10px;
                color: %(text)s;
                selection-background-color: %(accent)s;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid %(accent)s;
                outline: none;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: %(panel)s;
                border: 1px solid %(border)s;
                selection-background-color: %(accent)s;
                color: %(text)s;
                outline: none;
            }

            QPushButton {
                background: %(input_bg)s;
                border: 1px solid %(input_border)s;
                border-radius: 6px;
                padding: 6px 14px;
                color: %(text)s;
            }
            QPushButton:hover { border: 1px solid %(accent)s; }
            QPushButton:disabled {
                color: %(text_dim)s;
                border-color: %(divider)s;
            }

            QPushButton#ghostBtn {
                background: transparent;
                border: 1px solid %(input_border)s;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton#ghostBtn:hover {
                border: 1px solid %(accent)s;
                color: %(accent)s;
            }
            QPushButton#ghostBtnDanger {
                background: transparent;
                border: 1px solid %(input_border)s;
                border-radius: 6px;
                padding: 6px 12px;
                color: %(danger)s;
            }
            QPushButton#ghostBtnDanger:hover {
                background: %(danger)s;
                color: #ffffff;
                border: 1px solid %(danger)s;
            }
            QPushButton#ghostBtnDanger:disabled {
                color: %(text_dim)s;
                border-color: %(divider)s;
            }

            QPushButton#modeToggle {
                background: %(input_bg)s;
                border: 1px solid %(input_border)s;
                border-left: 3px solid %(accent)s;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 600;
                color: %(text)s;
                text-align: center;
            }
            QPushButton#modeToggle:hover {
                border: 1px solid %(accent)s;
                border-left: 3px solid %(accent)s;
            }

            QPushButton#convert {
                background: %(accent)s;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 700;
                color: #ffffff;
            }
            QPushButton#convert:hover { background: %(accent_hover)s; }
            QPushButton#convert:pressed { background: %(accent_press)s; }
            QPushButton#convert:disabled {
                background: %(input_bg)s;
                color: %(text_dim)s;
            }

            QCheckBox { spacing: 8px; }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                border-radius: 3px;
                border: 1px solid %(input_border)s;
                background: %(input_bg)s;
            }
            QCheckBox::indicator:checked {
                background: %(accent)s;
                border: 1px solid %(accent)s;
            }

            QListWidget {
                background: %(input_bg)s;
                border: 1px solid %(input_border)s;
                border-radius: 6px;
                outline: none;
                padding: 2px;
            }
            QListWidget::item {
                padding: 4px 6px;
                border-radius: 3px;
            }
            QListWidget::item:selected {
                background: %(accent)s;
                color: #ffffff;
            }
            QListWidget::item:hover { background: %(panel)s; }

            QProgressBar {
                background: %(panel)s;
                border: none;
                border-radius: 0;
            }
            QProgressBar::chunk {
                background: %(accent)s;
                border-radius: 0;
            }

            #viewerContainer {
                background: %(bg)s;
                border: 1px solid %(border)s;
                border-radius: 8px;
            }
            #viewerBar {
                background: %(panel)s;
                border-bottom: 1px solid %(divider)s;
            }
            QLabel#viewerTitle {
                color: %(text_strong)s; font-weight: 600;
            }
            QLabel#viewerCounter { color: %(text_dim)s; }
            QPushButton#viewerBtn {
                background: %(input_bg)s;
                border: 1px solid %(input_border)s;
                border-radius: 6px;
                color: %(text)s;
                padding: 2px 10px;
            }
            QPushButton#viewerBtn:hover {
                border: 1px solid %(accent)s;
                color: %(accent)s;
            }

            QMenu {
                background: %(panel)s;
                border: 1px solid %(border)s;
                color: %(text)s;
            }
            QMenu::item { padding: 5px 22px; }
            QMenu::item:selected {
                background: %(accent)s;
                color: #ffffff;
            }
        """ % t
        self.setStyleSheet(qss)
        self.titlebar.refresh_icons(self._dark)
        self.titlebar.refresh_lang_button()
        self.status.set_colors(self._dark)
        self.preview.thumb.set_colors(self._dark)
        self.file_list.set_dark(self._dark)
        for card in (self.src_card, self.preview, self.profile_card,
                     self.mip_card, self.comp_card, self.norm_card,
                     self.dst_card):
            card.refresh(self._dark)

    def toggle_theme(self):
        self._dark = not self._dark
        self.settings["theme"] = "dark" if self._dark else "light"
        save_settings(self.settings)
        self._apply_style()

    def change_language(self, code: str):
        if TR is None:
            return
        TR.set_lang(code)
        self.settings["language"] = code
        save_settings(self.settings)
        self._retranslate_ui()

    def _retranslate_ui(self):
        self.setWindowTitle(APP_NAME)
        self.btn_add.setText(" " + tr("btn_add"))
        self.src_edit.setPlaceholderText(tr("src_placeholder"))
        self.dst_edit.setPlaceholderText(tr("dst_placeholder"))
        self.btn_dst.setText(tr("btn_browse"))
        self.btn_pnew.setText(tr("profile_new"))
        self.btn_psave.setText(tr("profile_save_btn"))
        self.btn_pdel.setText(tr("profile_delete_btn"))
        self.chk_mips.setText(tr("chk_mips"))
        self.chk_norm.setText(tr("norm_enabled"))
        self.chk_open_folder.setText(tr("chk_open_folder"))
        self.cmb_norm.setItemText(0, tr("norm_pow2"))
        self.cmb_norm.setItemText(1, tr("norm_mul4"))
        self.cmb_norm.setItemText(2, tr("norm_custom"))
        self.cmb_comp.setItemText(0, tr("comp_none"))
        self.cmb_comp.setItemText(1, tr("comp_dxt1"))
        self.cmb_comp.setItemText(2, tr("comp_dxt5"))
        if self.cmb_profile.count() > 0:
            self.cmb_profile.setItemText(0, tr("profile_default"))
        self.status.copyright_lbl.setText(tr("window_copyright"))
        self.src_card.set_title(tr("card_sources"))
        self.preview.set_title(tr("card_preview"))
        self.profile_card.set_title(tr("card_profile"))
        self.mip_card.set_title(tr("card_mips"))
        self.comp_card.set_title(tr("card_compression"))
        self.norm_card.set_title(tr("card_normalize"))
        self.dst_card.set_title(tr("card_destination"))
        self.titlebar.btn_lang.setToolTip(tr("lang_menu_tooltip"))
        self.titlebar.btn_about.setToolTip(tr("about_title"))
        self.titlebar.btn_theme.setToolTip(tr("theme_toggle"))
        self._update_mode_ui()
        self._update_mip_hint()
        self._on_comp_changed(self.cmb_comp.currentIndex())
        self.titlebar.refresh_lang_button()
        if self.tray is not None:
            menu = self.tray.contextMenu()
            if menu is not None:
                acts = menu.actions()
                if len(acts) >= 3:
                    acts[0].setText(tr("tray_show"))
                    acts[1].setText(tr("tray_about"))
                    acts[-1].setText(tr("tray_quit"))

    def _load_settings_to_ui(self):
        s = self.settings
        self.dst_edit.setText(s.get("last_save_dir", ""))
        if s.get("last_mode") == self.MODE_EDDS_TO_IMG:
            self._mode = self.MODE_EDDS_TO_IMG
        elif s.get("last_mode") == self.MODE_IMG_TO_PAA:
            self._mode = self.MODE_IMG_TO_PAA
        else:
            self._mode = self.MODE_IMG_TO_EDDS

        m = s.get("mips", {})
        self.chk_mips.setChecked(bool(m.get("enabled")))
        idx = int(m.get("levels", 0)) - 1
        if 0 <= idx < self.cmb_mips.count():
            self.cmb_mips.setCurrentIndex(idx)
        self.cmb_mips.setEnabled(self.chk_mips.isChecked())

        comp = s.get("compression", "none")
        self.cmb_comp.setCurrentIndex(
            {"none": 0, "dxt1": 1, "dxt5": 2}.get(comp, 0)
        )

        n = s.get("normalize", {})
        self.chk_norm.setChecked(bool(n.get("enabled")))
        mode = {"pow2": 0, "mul4": 1, "custom": 2}.get(
            n.get("mode", "pow2"), 0
        )
        self.cmb_norm.setCurrentIndex(mode)
        self.spin_w.setValue(int(n.get("w", 1024)))
        self.spin_h.setValue(int(n.get("h", 1024)))
        self._on_norm_toggled(self.chk_norm.isChecked())
        self._on_norm_mode_changed(self.cmb_norm.currentIndex())

        self.chk_open_folder.setChecked(
            bool(s.get("open_folder_after", True))
        )

        self.cmb_profile.blockSignals(True)
        self.cmb_profile.clear()
        self.cmb_profile.addItem(tr("profile_default"))
        for name in s.get("profiles", {}).keys():
            self.cmb_profile.addItem(name)
        self.cmb_profile.blockSignals(False)

        self._update_mip_hint()
        self._on_comp_changed(self.cmb_comp.currentIndex())

    def _save_ui_to_settings(self):
        s = self.settings
        s["theme"] = "dark" if self._dark else "light"
        s["last_mode"] = self._mode
        s["mips"] = {
            "enabled": self.chk_mips.isChecked(),
            "levels": (self.cmb_mips.currentIndex() + 1)
                      if self.chk_mips.isChecked() else 0,
        }
        comp_map = ["none", "dxt1", "dxt5"]
        s["compression"] = comp_map[self.cmb_comp.currentIndex()]
        norm_mode = ["pow2", "mul4", "custom"][self.cmb_norm.currentIndex()]
        s["normalize"] = {
            "enabled": self.chk_norm.isChecked(),
            "mode": norm_mode,
            "w": self.spin_w.value(),
            "h": self.spin_h.value(),
        }
        s["open_folder_after"] = self.chk_open_folder.isChecked()
        save_settings(s)

    def toggle_mode(self):
        order = [self.MODE_IMG_TO_EDDS, self.MODE_EDDS_TO_IMG,
                 self.MODE_IMG_TO_PAA]
        i = order.index(self._mode) if self._mode in order else 0
        self._mode = order[(i + 1) % len(order)]
        self._clear_sources()
        self._update_mode_ui()
        self._save_ui_to_settings()

    def _update_mode_ui(self):
        hint = "   " + tr("mode_hint")
        if self._mode == self.MODE_IMG_TO_EDDS:
            self.btn_mode.setText(tr("mode_img_to_edds") + hint)
            self.lbl_subtitle.setText(tr("subtitle_img_to_edds"))
            self.btn_convert.setText(tr("btn_convert") + " → EDDS")
            self.mip_card.setVisible(True)
            self.comp_card.setVisible(True)
            self.norm_card.setVisible(True)
        elif self._mode == self.MODE_EDDS_TO_IMG:
            self.btn_mode.setText(tr("mode_edds_to_img") + hint)
            self.lbl_subtitle.setText(tr("subtitle_edds_to_img"))
            self.btn_convert.setText(tr("btn_convert") + " → Image")
            self.mip_card.setVisible(False)
            self.comp_card.setVisible(False)
            self.norm_card.setVisible(False)
        else:
            self.btn_mode.setText(tr("mode_img_to_paa") + hint)
            self.lbl_subtitle.setText(tr("subtitle_img_to_paa"))
            self.btn_convert.setText(tr("btn_convert") + " → PAA")
            self.mip_card.setVisible(False)
            self.comp_card.setVisible(True)
            self.norm_card.setVisible(True)
        self._update_dst_hint()

    def _expected_ext(self):
        if self._mode == self.MODE_IMG_TO_EDDS:
            return RASTER_EXT
        if self._mode == self.MODE_EDDS_TO_IMG:
            return EDDS_EXT
        return RASTER_EXT

    def _on_paths_added(self, paths: list[Path]):
        exts = self._expected_ext()
        good = [p for p in paths if p.suffix.lower() in exts]
        bad = [p for p in paths if p.suffix.lower() not in exts]
        if bad:
            self.status.set_state(
                "warn", tr("status_files_skipped", n=len(bad))
            )
        if good:
            self.file_list.add_paths(good)
        self._paths = self.file_list.paths()
        self.src_edit.setText(
            tr("files_count", n=len(self._paths)) if self._paths else ""
        )
        if self._paths and self.preview.current_path() is None:
            self.preview.load(self._paths[0])
        self._update_dst_hint()

    def _on_current_changed(self, path):
        if path is not None:
            self.preview.load(path)

    def _clear_sources(self):
        self.file_list.clear_all()
        self._paths = []
        self.src_edit.clear()
        self.preview.clear()
        self._update_dst_hint()

    def _update_dst_hint(self):
        if len(self._paths) > 1:
            self.lbl_dst_hint.setText(tr("dst_batch_hint"))
        else:
            self.lbl_dst_hint.setText("")

    def dragEnterEvent(self, e):
        if not e.mimeData().hasUrls():
            return
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.overlay.raise_()
        self.overlay.show()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.overlay.hide()

    def dropEvent(self, e):
        self.overlay.hide()
        paths = []
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file():
                paths.append(p)
        if paths:
            self._on_paths_added(paths)
        e.acceptProposedAction()

    def pick_src(self):
        if self._mode == self.MODE_EDDS_TO_IMG:
            flt = "EDDS/DDS (*.edds *.dds);;All files (*.*)"
        else:
            flt = "Images (*.png *.jpg *.jpeg *.tga *.bmp);;All files (*.*)"
        default = self.settings.get("last_open_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("btn_add"), default, flt
        )
        if paths:
            self.settings["last_open_dir"] = str(Path(paths[0]).parent)
            save_settings(self.settings)
            self._on_paths_added([Path(p) for p in paths])

    def pick_dst(self):
        default = self.dst_edit.text() or self.settings.get("last_save_dir", "")
        path = QFileDialog.getExistingDirectory(
            self, tr("btn_browse"), default
        )
        if path:
            self.dst_edit.setText(path)
            self.settings["last_save_dir"] = path
            save_settings(self.settings)

    def _on_mips_toggled(self, checked):
        self.cmb_mips.setEnabled(checked)
        self._update_mip_hint()

    def _update_mip_hint(self):
        if not self.chk_mips.isChecked():
            self.lbl_mip_hint.setText(tr("mips_none"))
        else:
            n = self.cmb_mips.currentIndex() + 1
            self.lbl_mip_hint.setText(tr("mips_hint", n=n))

    def _on_comp_changed(self, idx):
        hints = ["comp_hint_none", "comp_hint_dxt1", "comp_hint_dxt5"]
        text = tr(hints[idx]) if 0 <= idx < len(hints) else ""
        if not HAS_NUMPY and idx != 0:
            text += "  " + tr("comp_need_numpy")
        self.lbl_comp_hint.setText(text)

    def _on_norm_toggled(self, checked):
        self.cmb_norm.setEnabled(checked)
        custom = checked and self.cmb_norm.currentIndex() == 2
        self.spin_w.setEnabled(custom)
        self.spin_h.setEnabled(custom)

    def _on_norm_mode_changed(self, idx):
        custom = self.chk_norm.isChecked() and idx == 2
        self.spin_w.setEnabled(custom)
        self.spin_h.setEnabled(custom)

    def _profile_selected(self, idx):
        if idx <= 0:
            self._reset_settings_ui()
            self.btn_psave.setEnabled(False)
            self.btn_pdel.setEnabled(False)
            return
        name = self.cmb_profile.currentText()
        prof = self.settings.get("profiles", {}).get(name)
        if not prof:
            return
        self.btn_psave.setEnabled(True)
        self.btn_pdel.setEnabled(True)
        m = prof.get("mips", {})
        self.chk_mips.setChecked(bool(m.get("enabled")))
        if m.get("enabled"):
            i = int(m.get("levels", 1)) - 1
            if 0 <= i < self.cmb_mips.count():
                self.cmb_mips.setCurrentIndex(i)
        self.cmb_comp.setCurrentIndex(
            {"none": 0, "dxt1": 1, "dxt5": 2}.get(
                prof.get("compression", "none"), 0
            )
        )
        n = prof.get("normalize", {})
        self.chk_norm.setChecked(bool(n.get("enabled")))
        self.cmb_norm.setCurrentIndex(
            {"pow2": 0, "mul4": 1, "custom": 2}.get(
                n.get("mode", "pow2"), 0
            )
        )
        self.spin_w.setValue(int(n.get("w", 1024)))
        self.spin_h.setValue(int(n.get("h", 1024)))
        self._on_mips_toggled(self.chk_mips.isChecked())
        self._on_norm_toggled(self.chk_norm.isChecked())
        self._on_norm_mode_changed(self.cmb_norm.currentIndex())
        self._on_comp_changed(self.cmb_comp.currentIndex())

    def _reset_settings_ui(self):
        self.chk_mips.setChecked(False)
        self.cmb_mips.setCurrentIndex(0)
        self.cmb_mips.setEnabled(False)
        self._update_mip_hint()
        self.cmb_comp.setCurrentIndex(0)
        self._on_comp_changed(0)
        self.chk_norm.setChecked(False)
        self.cmb_norm.setCurrentIndex(0)
        self.spin_w.setValue(1024)
        self.spin_h.setValue(1024)
        self._on_norm_toggled(False)
        self._on_norm_mode_changed(0)

    def _profile_new(self):
        dlg = InputDialog(
            self, tr("profile_new_title"), tr("profile_new_label")
        )
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.result_str().strip()
        if not name:
            return
        if name in self.settings.get("profiles", {}):
            MessageDialog.warning(
                self, tr("profile_new_title"), tr("profile_exists")
            )
            return
        self._profile_save_current_as(name)
        self.cmb_profile.blockSignals(True)
        self.cmb_profile.addItem(name)
        self.cmb_profile.setCurrentText(name)
        self.cmb_profile.blockSignals(False)
        self.btn_psave.setEnabled(True)
        self.btn_pdel.setEnabled(True)
        self.status.set_state("ok", tr("profile_saved", name=name))

    def _profile_save(self):
        idx = self.cmb_profile.currentIndex()
        if idx <= 0:
            return
        name = self.cmb_profile.currentText()
        self._profile_save_current_as(name)
        MessageDialog.info(
            self, tr("profile_overwrite_title"),
            tr("profile_overwrite_text", name=name)
        )

    def _profile_save_current_as(self, name: str):
        prof = {
            "mips": {
                "enabled": self.chk_mips.isChecked(),
                "levels": (self.cmb_mips.currentIndex() + 1)
                          if self.chk_mips.isChecked() else 0,
            },
            "compression": ["none", "dxt1", "dxt5"][
                self.cmb_comp.currentIndex()
            ],
            "normalize": {
                "enabled": self.chk_norm.isChecked(),
                "mode": ["pow2", "mul4", "custom"][
                    self.cmb_norm.currentIndex()
                ],
                "w": self.spin_w.value(),
                "h": self.spin_h.value(),
            },
        }
        self.settings.setdefault("profiles", {})[name] = prof
        save_settings(self.settings)

    def _profile_delete(self):
        idx = self.cmb_profile.currentIndex()
        if idx <= 0:
            MessageDialog.info(
                self, tr("profile_delete_title"),
                tr("profile_cannot_delete_default")
            )
            return
        name = self.cmb_profile.currentText()
        if not MessageDialog.question(
            self, tr("profile_delete_title"),
            tr("profile_delete_text", name=name)
        ):
            return
        self.settings.get("profiles", {}).pop(name, None)
        save_settings(self.settings)
        self.cmb_profile.removeItem(idx)
        self.btn_psave.setEnabled(False)
        self.btn_pdel.setEnabled(False)
        self.status.set_state("ok", tr("profile_deleted", name=name))

    def _open_viewer(self):
        paths = self.file_list.paths()
        if not paths:
            return
        cur = self.preview.current_path()
        idx = 0
        if cur is not None and cur in paths:
            idx = paths.index(cur)
        ImageViewer(self, paths, idx).exec()

    def convert_clicked(self):
        if self._running:
            self._cancel_requested = True
            self.status.set_state("warn", tr("status_cancelled"))
            return

        paths = self.file_list.paths()
        if not paths:
            MessageDialog.info(
                self, tr("msg_empty_title"), tr("msg_empty_text")
            )
            return
        dst_dir = self.dst_edit.text().strip().strip('"')
        if not dst_dir:
            MessageDialog.info(
                self, tr("msg_dst_title"), tr("msg_dst_text")
            )
            return
        dst_dir_p = Path(dst_dir)
        dst_dir_p.mkdir(parents=True, exist_ok=True)

        mips = 0
        if (self.chk_mips.isChecked()
                and self._mode == self.MODE_IMG_TO_EDDS):
            mips = self.cmb_mips.currentIndex() + 1

        comp_map = ["none", "dxt1", "dxt5"]
        compression = comp_map[self.cmb_comp.currentIndex()]
        if compression != "none" and not HAS_NUMPY:
            MessageDialog.warning(
                self, tr("msg_numpy_title"), tr("msg_numpy_text")
            )
            return

        if self._mode == self.MODE_IMG_TO_PAA and not self._imagetopaa:
            MessageDialog.warning(
                self, "imagetopaa", tr("paa_need_tool")
            )
            return

        norm_cfg = {
            "enabled": self.chk_norm.isChecked()
                       and self._mode != self.MODE_EDDS_TO_IMG,
            "mode": ["pow2", "mul4", "custom"][
                self.cmb_norm.currentIndex()
            ],
            "w": self.spin_w.value(),
            "h": self.spin_h.value(),
        }

        self._running = True
        self._cancel_requested = False
        self.btn_convert.setText(tr("btn_cancel"))
        self.status.set_busy(True)
        self.progress.setValue(0)

        total = len(paths)
        ok_cnt = 0
        err_cnt = 0
        cancelled = False

        for i, src in enumerate(paths):
            if self._cancel_requested:
                cancelled = True
                break

            self.file_list.mark_status(src, "running")
            self.file_list.setCurrentRow(i)
            self.status.set_state(
                "warn", tr("status_converting", name=src.name)
            )
            self.status.set_counter(i, total)
            QApplication.processEvents()

            try:
                if self._mode == self.MODE_IMG_TO_EDDS:
                    dst = dst_dir_p / (src.stem + ".edds")
                    image_to_edds(src, dst, mips, compression, norm_cfg)
                elif self._mode == self.MODE_EDDS_TO_IMG:
                    dst = dst_dir_p / (src.stem + ".png")
                    edds_to_image(src, dst)
                else:
                    if norm_cfg["enabled"]:
                        tmp_im = Image.open(src).convert("RGBA")
                        tmp_im = _normalize_image(tmp_im, norm_cfg)
                        tmp_src = dst_dir_p / (src.stem + "__paa_tmp.png")
                        tmp_im.save(tmp_src)
                        use_src = tmp_src
                    else:
                        use_src = src
                        tmp_src = None

                    comp_for_paa = "dxt5" if compression == "none" else compression
                    dst = dst_dir_p / (src.stem + ".paa")
                    paa_convert(self._imagetopaa, use_src, dst, comp_for_paa)
                    if tmp_src is not None:
                        try:
                            tmp_src.unlink()
                        except Exception:
                            pass

                self.file_list.mark_status(src, "ok")
                ok_cnt += 1
            except Exception as e:
                self.file_list.mark_status(src, "error", str(e))
                err_cnt += 1

            self._animate_progress(int((i + 1) / total * 100))
            self.status.set_counter(i + 1, total)
            QApplication.processEvents()

        self._running = False
        self.btn_convert.setText(tr("btn_convert"))
        self.status.set_busy(False)

        if cancelled:
            self.status.set_state(
                "warn", tr("status_result_cancel", n=ok_cnt, m=err_cnt)
            )
        elif err_cnt == 0:
            self.status.set_state("ok", tr("status_result_ok", n=ok_cnt))
            self._notify(APP_NAME, tr("notify_done_text", n=ok_cnt))
        else:
            self.status.set_state(
                "error", tr("status_result_err", n=ok_cnt, m=err_cnt)
            )
            self._notify(APP_NAME, tr("notify_err_text", n=ok_cnt, m=err_cnt))

        if self.chk_open_folder.isChecked() and ok_cnt > 0:
            self._open_folder(dst_dir_p)

        self._save_ui_to_settings()

    def _animate_progress(self, value: int):
        anim = QPropertyAnimation(self.progress, b"value", self)
        anim.setDuration(250)
        anim.setStartValue(self.progress.value())
        anim.setEndValue(value)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _open_folder(self, path: Path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # noqa: S606
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        except Exception as e:
            print(f"[open folder] {e}", file=sys.stderr)

    # -------------------------------------------------- close / tray
    def closeEvent(self, e):
        self._save_ui_to_settings()
        e.accept()


# ============================================================ entry
def main():
    global TRANSLATIONS, TR

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    load_fonts(app)
    _ensure_qta()

    TRANSLATIONS = load_translations()
    pre_settings = load_settings()
    lang = pre_settings.get("language", "ru")
    TR = Translator(TRANSLATIONS, lang, fallback="en")

def main():
    global TRANSLATIONS, TR

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    # иконка приложения — для окна и таскбара
    ico_path = _external_dir() / "icon.ico"
    if not ico_path.exists():
        internal = _internal_dir()
        if internal is not None:
            ico_path = internal / "icon.ico"
    if ico_path.exists():
        app.setWindowIcon(QIcon(str(ico_path)))

    load_fonts(app)
    _ensure_qta()

    TRANSLATIONS = load_translations()
    pre_settings = load_settings()
    lang = pre_settings.get("language", "ru")
    TR = Translator(TRANSLATIONS, lang, fallback="en")

    w = MainWindow()
    w.setWindowIcon(app.windowIcon())
    w.show()
    geo = w.frameGeometry()
    geo.moveCenter(
        QGuiApplication.primaryScreen().availableGeometry().center()
    )
    w.move(geo.topLeft())
    sys.exit(app.exec())


if __name__ == "__main__":
    main()