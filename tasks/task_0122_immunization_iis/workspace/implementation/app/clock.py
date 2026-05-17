"""Logical clock — drives current time for the entire system.

The clock is mutable through the POST /_clock/advance test-only endpoint, so all
time-dependent logic (rolling compliance window, age computations against
administered_at, VAERS lag boundary) must read from here rather than from the
wall clock.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Optional


_lock = RLock()
_logical_offset_seconds: float = 0.0  # offset applied to wall clock to derive logical time
_pinned: Optional[datetime] = None    # if set, logical time = _pinned regardless of wall clock


def _wall_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def now() -> datetime:
    """Return the current logical UTC datetime."""
    with _lock:
        if _pinned is not None:
            return _pinned
        return _wall_now()


def reset_clock() -> None:
    """Unpin the logical clock — used by the test reset endpoint."""
    global _pinned
    with _lock:
        _pinned = None


def advance_to(target: datetime) -> datetime:
    """Pin the logical clock to the supplied target instant."""
    global _pinned
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    else:
        target = target.astimezone(timezone.utc)
    with _lock:
        _pinned = target
        return _pinned


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional second digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # microseconds -> milliseconds with rounding-toward-zero (truncation is fine for tests)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def current_iso_timestamp() -> str:
    return format_iso(now())


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts both 'Z' and explicit offsets, with or without fractional seconds.
    """
    if not isinstance(value, str):
        raise ValueError("expected ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Python <3.11 doesn't accept arbitrary fractional precision in fromisoformat,
    # but 3.12 does. We rely on 3.12 in the Dockerfile.
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_iso_date(value: str):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD) into a datetime.date."""
    from datetime import date
    if not isinstance(value, str):
        raise ValueError("expected ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
