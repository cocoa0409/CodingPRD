"""Logical clock (PRD §2.9).

At server startup the clock reads exactly 2026-01-01T00:00:00Z; until an operator
sets it, it stays at that default and never falls back to wall-clock.
"""
from datetime import datetime, timezone, timedelta

from constants import DEFAULT_CLOCK_ISO


def parse_iso(s):
    """Parse an ISO-8601 instant (accepts trailing Z) into a timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO-8601 UTC with exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    def __init__(self):
        self.current = parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        return self.current

    def set(self, iso):
        self.current = parse_iso(iso)


def add_months(dt, months):
    """Advance a datetime by a whole number of calendar months, clamping day to month length."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to last valid day of target month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def whole_months_between(start, end):
    """Number of WHOLE months between start and end, floored (PRD §3.12)."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # If the day-of-month / time of `end` has not yet reached `start`'s, subtract one.
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < (
        start.day,
        start.hour,
        start.minute,
        start.second,
        start.microsecond,
    ):
        months -= 1
    return max(0, months)
