"""Logical UTC clock (PRD §2.4 and §1).

The server starts at 2026-01-01T00:00:00Z. Before any clock-set call every
timestamp the platform stamps reads exactly that default; it never falls back
to wall-clock time. Administrators advance the clock via POST
/_clock/set_current_utc.

Datetimes are represented internally as timezone-aware datetime objects; the
canonical string form is ISO 8601 UTC with three fractional digits (matching
the record timestamp format of PRD §2.4).
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

SECONDS_PER_DAY = 86400


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def reset(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt

    def iso(self):
        return to_iso(self.now)


def to_iso(dt):
    """Format a timezone-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns a tz-aware UTC datetime or raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
