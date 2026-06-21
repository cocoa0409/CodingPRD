"""Logical system clock and datetime helpers.

The platform exposes test-driving clock endpoints that pin/advance a logical
clock (PRD §3.9). All now() reads resolve through this module so the test
harness can control time deterministically. The store starts with the clock
unset; until it is pinned, now() falls back to real UTC wall-clock time.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._pinned = None  # aware datetime in UTC, or None

    def now(self):
        if self._pinned is not None:
            return self._pinned
        return datetime.now(timezone.utc)

    def set(self, instant):
        self._pinned = instant

    def advance(self, instant):
        self._pinned = instant


def parse_iso8601(value):
    """Parse an ISO 8601 string to an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Accept trailing Z as UTC.
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso8601_millis(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_months(dt, months):
    """Add a whole number of calendar months to an aware datetime.

    Calendar-month arithmetic: 2026-06-01 + 48 months == 2030-06-01. Clamp the
    day to the last valid day of the target month when necessary.
    """
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Last day of target month.
    if month == 12:
        next_month_first = dt.replace(year=year + 1, month=1, day=1)
    else:
        next_month_first = dt.replace(year=year, month=month + 1, day=1)
    from datetime import timedelta
    last_day = (next_month_first - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)
