"""The logical clock (PRD §2.9).

At server startup the logical clock reads exactly 2026-01-01T00:00:00Z, and
until it is explicitly set it remains at that default and never falls back to
wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def parse_iso8601(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    Returns None if the value cannot be parsed.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
