"""Logical clock. Starts at 2026-04-01T00:00:00Z and never falls back to wall time."""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt


clock = Clock()


def parse_iso8601(value):
    """Parse an ISO 8601 UTC timestamp into an aware datetime (UTC).

    Accepts a trailing 'Z' or an explicit offset. Returns None on failure.
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits and Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)
