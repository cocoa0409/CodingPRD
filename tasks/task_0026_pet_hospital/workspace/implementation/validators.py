"""Shared validation helpers — regex, ranges, ISO 8601 parsing."""
from __future__ import annotations

import re
from datetime import datetime, date, timezone
from typing import Any, Optional

from errors import err


_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PHONE_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_DRUG_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
_VACCINE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
_BATCH_ID_RE = re.compile(r"^[A-Z0-9-]{4,32}$")
_EXT_LAB_REF_RE = re.compile(r"^[A-Z0-9-]{6,40}$")
_DIAGNOSIS_CODE_RE = re.compile(r"^[A-Z][A-Z0-9.]{1,15}$")
_CAGE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9-]{1,15}$")


def require_str(payload: dict, field: str, *, min_len: int = 1, max_len: int | None = None,
                pattern: re.Pattern | None = None) -> str:
    v = payload.get(field)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION_FAILED", f"{field} must be a string")
    s = v.strip() if min_len > 0 else v
    if min_len > 0 and len(s) < min_len:
        raise err("ERR_VALIDATION_FAILED", f"{field} below minimum length {min_len}")
    if max_len is not None and len(v) > max_len:
        raise err("ERR_VALIDATION_FAILED", f"{field} exceeds maximum length {max_len}")
    if pattern and not pattern.match(v):
        raise err("ERR_VALIDATION_FAILED", f"{field} fails format check")
    return v


def require_int(payload: dict, field: str, *, min_v: int | None = None,
                max_v: int | None = None) -> int:
    v = payload.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION_FAILED", f"{field} must be an integer")
    if min_v is not None and v < min_v:
        raise err("ERR_VALIDATION_FAILED", f"{field} below minimum {min_v}")
    if max_v is not None and v > max_v:
        raise err("ERR_VALIDATION_FAILED", f"{field} above maximum {max_v}")
    return v


def require_number(payload: dict, field: str, *, min_v: float | None = None,
                   max_v: float | None = None) -> float:
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION_FAILED", f"{field} must be a number")
    fv = float(v)
    if min_v is not None and fv < min_v:
        raise err("ERR_VALIDATION_FAILED", f"{field} below minimum {min_v}")
    if max_v is not None and fv > max_v:
        raise err("ERR_VALIDATION_FAILED", f"{field} above maximum {max_v}")
    return fv


def require_bool(payload: dict, field: str) -> bool:
    v = payload.get(field)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION_FAILED", f"{field} must be a boolean")
    return v


def parse_iso8601(s: str) -> datetime:
    if not isinstance(s, str) or not _ISO8601_RE.match(s):
        raise err("ERR_VALIDATION_FAILED", f"Invalid ISO 8601 timestamp: {s!r}")
    s2 = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s2)
    except Exception:
        raise err("ERR_VALIDATION_FAILED", f"Invalid ISO 8601 timestamp: {s!r}")


def parse_date(s: str) -> date:
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise err("ERR_VALIDATION_FAILED", f"Invalid date: {s!r}")
    try:
        return date.fromisoformat(s)
    except Exception:
        raise err("ERR_VALIDATION_FAILED", f"Invalid date: {s!r}")


def validate_phone_e164(s: str) -> str:
    if not isinstance(s, str) or not _PHONE_E164_RE.match(s):
        raise err("ERR_VALIDATION_FAILED", f"Invalid phone_e164: {s!r}")
    return s


def validate_email(s: str) -> str:
    if not isinstance(s, str) or len(s) > 320 or not _EMAIL_RE.match(s):
        raise err("ERR_VALIDATION_FAILED", f"Invalid email: {s!r}")
    return s.lower()


def validate_pagination(args) -> tuple[int, int]:
    """Read limit (default 10, 1..100) and offset (default 0) from query args."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_FAILED", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_FAILED", "limit out of range [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_FAILED", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION_FAILED", "offset must be >= 0")
    return limit, offset


# Re-export regex patterns
__all__ = [
    "_DRUG_CODE_RE", "_VACCINE_CODE_RE", "_BATCH_ID_RE",
    "_EXT_LAB_REF_RE", "_DIAGNOSIS_CODE_RE", "_CAGE_CODE_RE",
    "require_str", "require_int", "require_number", "require_bool",
    "parse_iso8601", "parse_date",
    "validate_phone_e164", "validate_email", "validate_pagination",
]
