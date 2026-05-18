"""Shared utilities: ids, timestamps, rounding, decimal helpers."""
from __future__ import annotations

import math
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP


# ── ID helpers ──────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ── Timestamp formatting ────────────────────────────────────────────────────


def iso_now(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with three fractional digits + Z."""
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


def parse_iso_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD) into a date object."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        raise ValueError(f"Expected date string, got {type(value).__name__}")
    s = value.strip()
    return date.fromisoformat(s)


def floor_date_utc(dt: datetime) -> date:
    """Return the UTC calendar date corresponding to dt."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return date(dt.year, dt.month, dt.day)


def whole_years_between(earlier: date, later: date) -> int:
    """Floor whole years (e.g., used for client age calc)."""
    if later is None or earlier is None:
        return 0
    years = later.year - earlier.year
    if (later.month, later.day) < (earlier.month, earlier.day):
        years -= 1
    return max(years, 0)


# ── Rounding helpers ────────────────────────────────────────────────────────


def round_half_up_to_int(value) -> int:
    """Round a numeric value half-up to the nearest whole integer."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    """Round a numeric value half-up to two decimal places, returned as float."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def truncate_to_4dp(value) -> float:
    """Truncate (not round) a numeric value to 4 decimal places."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    # Truncate towards zero.
    scaled = int(d * Decimal("10000"))
    return float(Decimal(scaled) / Decimal("10000"))
