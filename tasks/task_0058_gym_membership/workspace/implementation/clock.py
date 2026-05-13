"""Logical clock for deterministic time-gated transitions.

By default returns wall clock. Tests advance via POST /_clock/advance.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta


_clock_override: datetime | None = None


def now() -> datetime:
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


def set_clock(dt: datetime):
    global _clock_override
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _clock_override = dt


def reset_clock():
    global _clock_override
    _clock_override = None


def to_iso_ms(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def from_iso(s: str) -> datetime:
    """Parse ISO 8601 timestamp. Accepts trailing Z, fractional seconds."""
    if s is None:
        raise ValueError("None timestamp")
    s = str(s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def end_of_day(dt: datetime) -> datetime:
    """Truncate/anchor a datetime at 23:59:59.999Z UTC of the same calendar day."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return datetime(dt.year, dt.month, dt.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def end_of_day_after_days(start: datetime, days: int) -> datetime:
    """activation_date + validity_days, anchored at end of that day, UTC."""
    return end_of_day(add_days(start, days))


def whole_days_between(later: datetime, earlier: datetime) -> int:
    """Floor of the difference in days. Result can be negative."""
    delta = later - earlier
    total_seconds = delta.total_seconds()
    # Use integer floor division by 86400 — but for negative durations Python's //
    # already floors. We want truncation toward zero? PRD says "in days" generally
    # meaning floor. We'll use floor of total seconds / 86400.
    import math
    return math.floor(total_seconds / 86400)


def ceil_days(seconds: float) -> int:
    import math
    return math.ceil(seconds / 86400)
