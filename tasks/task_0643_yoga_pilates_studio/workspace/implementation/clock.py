"""Logical clock and ISO 8601 UTC datetime helpers.

The clock defaults to exactly 2026-01-01T00:00:00Z on every fresh boot (PRD §2.4)
and never falls back to wall-clock time. A StudioManager may move it.
"""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 UTC instant into a tz-aware UTC datetime.

    Raises ValueError on malformed input.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("not a string")
    s = value.strip()
    # Normalize trailing Z to +00:00 for fromisoformat
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_ms(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)
