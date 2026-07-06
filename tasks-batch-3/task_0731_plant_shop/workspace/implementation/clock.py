"""Logical clock for the plant shop API.

On process startup the clock reads exactly 2026-03-01T00:00:00Z and remains
at that instant until /_clock/set_current_utc advances it. It NEVER falls
back to the real wall-clock.
"""
from datetime import datetime, timezone

_STARTUP = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _STARTUP


def get_now() -> datetime:
    return _current


def set_now(dt: datetime) -> None:
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _current = dt


def iso_now() -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2026-03-01T00:00:00.000Z."""
    return format_iso(get_now())


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Millisecond precision, Z suffix.
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 UTC timestamp; returns None on failure."""
    if not isinstance(s, str):
        return None
    try:
        # Accept trailing Z or explicit offset.
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
