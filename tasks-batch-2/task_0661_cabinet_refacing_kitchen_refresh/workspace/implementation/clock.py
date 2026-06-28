"""The logical clock (PRD §2.8).

The system never reads wall-clock time. At server startup the clock reads
exactly 2026-04-01T00:00:00Z and stays there until a PlatformAdmin sets it.
"""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt


def parse_iso8601(s):
    """Parse an ISO 8601 UTC instant into an aware datetime (UTC)."""
    if not isinstance(s, str) or not s:
        raise ValueError("bad iso8601")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=int(days))
