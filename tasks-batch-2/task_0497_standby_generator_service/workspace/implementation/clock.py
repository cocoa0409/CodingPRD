"""Logical clock. Authoritative 'now' for all time-dependent rules.

On startup the clock reads exactly 2026-01-01T00:00:00Z and never falls back to
wall-clock time. The only way it moves is POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

# Default logical "now". Module-level so it resets on every fresh process boot.
DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_CLOCK


def get_now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def reset():
    global _now
    _now = DEFAULT_CLOCK


def parse_iso8601(s):
    """Parse an ISO8601 instant. Returns an aware UTC datetime or raises ValueError."""
    if not isinstance(s, str) or not s:
        raise ValueError("invalid iso8601")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso8601(dt):
    """Format an aware datetime as ISO8601 UTC with three fractional digits + Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, three fractional digits
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
