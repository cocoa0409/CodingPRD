"""Logical clock + ISO 8601 helpers.

Tests drive time forward with POST /_clock/advance. now() returns either the
advanced instant (if one was set) or the wall-clock current UTC time, formatted
as an ISO 8601 UTC string with three fractional digits."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


_advanced_clock: Optional[datetime] = None


def set_clock(dt: datetime) -> None:
    global _advanced_clock
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _advanced_clock = dt


def now_dt() -> datetime:
    if _advanced_clock is not None:
        return _advanced_clock
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return format_iso(now_dt())


def format_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with milliseconds and 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # millisecond precision, Z suffix
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if value is None:
        raise ValueError("timestamp is None")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
