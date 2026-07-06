"""Logical clock (PRD §2.4).

All business time is measured against this logical clock, never the wall
clock. At server startup the clock reads exactly 2026-03-01T00:00:00Z, and
until an administrator advances it the system treats that instant as "now".
"""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime.

    Returns None on failure.
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


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt.astimezone(timezone.utc)

    def plus_minutes(self, dt, minutes):
        return dt + timedelta(minutes=minutes)

    def plus_days(self, dt, days):
        return dt + timedelta(days=days)
