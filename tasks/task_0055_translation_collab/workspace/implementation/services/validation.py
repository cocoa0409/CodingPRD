"""Reusable input validators."""
from __future__ import annotations

import re

from errors import err

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LANG_RE = re.compile(r"^[a-zA-Z]{2}$")

DOMAINS = {"LEGAL", "MEDICAL", "TECH", "MARKETING", "MEDIA", "FINANCE", "GENERAL"}
PRICING_MODES = {"PER_WORD", "PER_SEGMENT", "PER_FILE"}
FILE_FORMATS = {"DOCX", "PDF", "PPTX", "XLSX", "SRT"}
SPLIT_MODES = {"SENTENCE", "PARAGRAPH"}
ASSIGNMENT_ROLES = {"TRANSLATOR", "REVIEWER", "FINAL_REVIEWER"}
GRADES = {"JUNIOR", "INTERMEDIATE", "SENIOR", "EXPERT"}
AVAIL = {"AVAILABLE", "BUSY", "OFFLINE", "SUSPENDED"}
ERR_CATS = {"MISTRANSLATION", "OMISSION", "GRAMMAR", "STYLE", "TERMINOLOGY"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
TERM_SCOPES = {"PROJECT", "CLIENT"}
TARGET_SYSTEMS = {"PAYMENT", "IM", "STORAGE"}
PAYMENT_CYCLES = {0, 7, 15, 30, 45}


def require_field(body: dict, key: str):
    if key not in body or body[key] is None:
        raise err("ERR_VALIDATION_FAILED", f"Missing required field: {key}")
    return body[key]


def require_string(body: dict, key: str, *, min_len: int = 1, max_len: int | None = None):
    v = require_field(body, key)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION_FAILED", f"{key} must be a string.")
    if len(v) < min_len:
        raise err("ERR_VALIDATION_FAILED", f"{key} too short.")
    if max_len is not None and len(v) > max_len:
        raise err("ERR_VALIDATION_FAILED", f"{key} too long.")
    return v


def require_int(body: dict, key: str, *, min_val: int | None = None, max_val: int | None = None):
    v = require_field(body, key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION_FAILED", f"{key} must be an integer.")
    if min_val is not None and v < min_val:
        raise err("ERR_VALIDATION_FAILED", f"{key} below minimum.")
    if max_val is not None and v > max_val:
        raise err("ERR_VALIDATION_FAILED", f"{key} above maximum.")
    return v


def require_enum(body: dict, key: str, allowed: set):
    v = require_field(body, key)
    if v not in allowed:
        raise err("ERR_VALIDATION_FAILED", f"{key} not in allowed set.")
    return v


def validate_email(s: str):
    if not isinstance(s, str) or not EMAIL_RE.match(s):
        raise err("ERR_VALIDATION_FAILED", "Invalid email.")
    return s


def validate_lang(s: str):
    if not isinstance(s, str) or not LANG_RE.match(s):
        raise err("ERR_VALIDATION_FAILED", "Invalid ISO 639-1 language code.")
    return s.lower()
