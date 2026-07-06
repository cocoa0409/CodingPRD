"""Logical clock used for all date/window/expiry math.

Before any call, the clock reads 2026-03-01T00:00:00Z and never falls back to
wall-clock time. It is mutated only via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt


def parse_iso8601(value):
    """Parse an ISO8601 instant into a tz-aware UTC datetime. Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
