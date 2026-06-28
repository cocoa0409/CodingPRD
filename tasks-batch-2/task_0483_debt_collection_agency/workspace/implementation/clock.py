"""Logical clock and ISO 8601 helpers.

The whole system reads time from a single logical clock. At startup the clock
holds 2026-01-01T00:00:00Z and before any clock-setting call it reads exactly
that default (never wall-clock).
"""
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt
        return self.now


clock = Clock()


def parse_iso8601(value):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime.

    Accepts trailing 'Z' and explicit offsets. Returns None on failure.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Python 3.9's fromisoformat does not accept the 'Z' suffix.
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
    """Format a datetime as ISO 8601 UTC with three fractional digits and a 'Z'."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_years(dt, years):
    """Add whole calendar years to an instant, handling Feb 29 -> Feb 28."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 in a non-leap target year.
        return dt.replace(year=dt.year + years, day=28)


def add_days(dt, days):
    return dt + timedelta(days=days)
