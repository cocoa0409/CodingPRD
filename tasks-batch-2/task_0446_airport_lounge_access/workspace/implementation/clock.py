"""Server-side logical clock (PRD §2.4).

On startup the clock reads exactly 2026-01-01T00:00:00Z and never falls back to
wall-clock time. The operator advances it with POST /_clock/set_current_utc.

All timestamps are emitted ISO 8601 UTC with three fractional digits and a 'Z'.
"""
from datetime import datetime, timezone, timedelta

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

# Logical clock state.
_logical_now = _DEFAULT


def reset():
    global _logical_now
    _logical_now = _DEFAULT


def now():
    """Current logical-clock instant as a timezone-aware datetime."""
    return _logical_now


def set_now(dt):
    global _logical_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _logical_now = dt.astimezone(timezone.utc)
    return _logical_now


def to_iso_millis(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso_millis():
    return to_iso_millis(_logical_now)


def parse_iso(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ValueError on failure.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)
