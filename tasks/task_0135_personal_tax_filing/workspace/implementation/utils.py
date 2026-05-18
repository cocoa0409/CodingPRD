"""Shared utilities: ids, timestamps, math helpers."""
from __future__ import annotations

import re
import secrets
import string
import uuid
from datetime import datetime, timezone


# ── ID helpers ──────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def new_submission_id() -> str:
    """Server-minted IRS submission identifier."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(16))
    return f"sub_{suffix}"


# ── Timestamp formatting ────────────────────────────────────────────────────


def iso_now(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with milliseconds + Z (three fractional digits)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 string into a UTC-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"Expected datetime string, got {type(value).__name__}")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_to_midnight_utc(value):
    """Parse YYYY-MM-DD into a UTC midnight datetime."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected YYYY-MM-DD, got {type(value).__name__}")
    s = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError(f"Invalid date format (need YYYY-MM-DD): {value}")
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value}") from exc
    return dt.replace(tzinfo=timezone.utc)


# ── Math helpers (integer cents arithmetic per PRD §2.5) ────────────────────


def ceil_div(numerator: int, denominator: int) -> int:
    """Integer ceiling of numerator / denominator (positive denominator)."""
    if denominator == 0:
        raise ZeroDivisionError("denominator is zero")
    q, r = divmod(numerator, denominator)
    if r != 0 and ((numerator > 0) == (denominator > 0)):
        q += 1
    return q


def trunc_div(numerator: int, denominator: int) -> int:
    """Integer division truncating toward zero (PRD §2.5 default rounding)."""
    if denominator == 0:
        raise ZeroDivisionError("denominator is zero")
    # Truncation toward zero — for positive operands matches Python //;
    # for mixed-sign operands diverges from // (which floors).
    q = abs(numerator) // abs(denominator)
    if (numerator < 0) ^ (denominator < 0):
        q = -q
    return q


# Alias: when both inputs are non-negative this is what the PRD calls
# "floor division on non-negative inputs".
def floor_div_pos(numerator: int, denominator: int) -> int:
    """Floor division, assumed non-negative inputs."""
    return numerator // denominator


# ── Field validators ────────────────────────────────────────────────────────


def is_nonneg_int(value) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) and value >= 0


def is_int(value) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int)


def is_nonempty_str(value) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def coerce_optional_int(value, *, allow_negative: bool = False):
    """Return value as int if it's a valid int; raise ValueError otherwise."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("bool is not a valid int")
    if not isinstance(value, int):
        raise ValueError("not an integer")
    if not allow_negative and value < 0:
        raise ValueError("must be non-negative")
    return value
