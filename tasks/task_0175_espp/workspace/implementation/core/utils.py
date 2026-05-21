"""Time, ID, decimal, and date helpers."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


_LOCK = threading.RLock()


def lock():
    """Return the global re-entrant lock used to serialize all writes."""
    return _LOCK


def new_id() -> str:
    """Generate a UUIDv4 string without any type prefix."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Server wall-clock for response envelopes (ISO 8601 UTC, ms precision)."""
    return _format_iso(datetime.now(timezone.utc))


def _format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Format with milliseconds.
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def format_iso(dt: datetime) -> str:
    return _format_iso(dt)


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise ValueError("Expected non-empty ISO 8601 string")
    s = value.strip()
    # Accept trailing Z.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    """Add calendar months to a datetime (preserving time-of-day)."""
    if not isinstance(months, int):
        raise TypeError("months must be int")
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    # Clamp day to last day of target month.
    import calendar

    last_day = calendar.monthrange(y, m)[1]
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


def add_years(dt: datetime, years: int) -> datetime:
    return add_months(dt, years * 12)


def round_half_up_int(numerator: int, denominator: int) -> int:
    """Compute round_half_up(numerator / denominator) returning an int."""
    if denominator == 0:
        raise ZeroDivisionError("Denominator must not be zero")
    sign = -1 if (numerator < 0) ^ (denominator < 0) else 1
    n = abs(numerator)
    d = abs(denominator)
    q = (n + d // 2) // d
    return sign * q


def floor_div(numerator: int, denominator: int) -> int:
    """Integer floor division (Python's // already floor-divides, but we wrap for clarity)."""
    if denominator == 0:
        raise ZeroDivisionError("Denominator must not be zero")
    return numerator // denominator


def safe_int(value, *, allow_none: bool = False) -> Optional[int]:
    if value is None:
        if allow_none:
            return None
        raise ValueError("Expected integer, got None")
    if isinstance(value, bool):
        raise ValueError("Expected integer, got bool")
    if isinstance(value, int):
        return value
    raise ValueError(f"Expected integer, got {type(value).__name__}")
