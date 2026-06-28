"""Server-controlled logical clock (PRD §2.4).

At server startup the clock reads exactly 2026-01-01T00:00:00Z, and until it is
explicitly set it never falls back to real time. POST /_clock/set_current_utc
sets it to an arbitrary UTC instant. All timestamps the server stamps
(signed_at, cycle_anchor_at, expires_at, invoice created_at, and resource
created_at/updated_at) are taken from this clock.
"""

import math
from datetime import datetime, timezone, timedelta

DEFAULT_INSTANT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_INSTANT

    def now(self):
        return self._now

    def set(self, instant):
        self._now = instant


clock = LogicalClock()


def parse_iso8601(value):
    """Parse an ISO 8601 instant. Accepts trailing 'Z'. Returns tz-aware UTC.

    Raises ValueError on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s == "":
        raise ValueError("timestamp must be a non-empty string")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601_ms(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits + 'Z'."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)


def floor_days_between(start, end):
    """Whole (floored) days from start to end. Can be negative if end < start."""
    delta = end - start
    return int(math.floor(delta.total_seconds() / 86400.0))


def floor_minutes_between(start, end):
    """Whole (floored) minutes from start to end. Can be negative if end < start."""
    delta = end - start
    return int(math.floor(delta.total_seconds() / 60.0))
