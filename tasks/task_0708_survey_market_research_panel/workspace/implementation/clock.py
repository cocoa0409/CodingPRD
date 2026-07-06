"""Logical clock (PRD §2.4).

At startup the clock reads exactly 2026-03-01T00:00:00Z and before any
clock-setting call it stays at that default and never falls back to real time.
The clock is set via POST /_clock/set_current_utc with `to_iso8601`.
"""
from datetime import datetime, timezone

# Startup default per PRD §2.4
_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _DEFAULT


def parse_iso8601(value):
    """Parse an ISO 8601 UTC string into an aware datetime (UTC)."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_now(value):
    """Set the logical clock from an ISO 8601 string. Returns the new datetime."""
    global _now
    _now = parse_iso8601(value)
    return _now


def now():
    """Current logical-clock instant (aware UTC datetime)."""
    return _now


def format_iso8601(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return format_iso8601(_now)
