"""Datetime parsing and interval helpers.

All datetimes in the system are ISO 8601 UTC. Inputs may carry a trailing 'Z'
or an explicit +00:00 offset; we normalise to timezone-aware UTC datetimes.
"""
from datetime import datetime, timezone, timedelta

ONE_DAY = timedelta(days=1)


def parse_dt(value):
    """Parse an ISO 8601 datetime string to a tz-aware UTC datetime.

    Returns None if value is not a parseable string. Accepts a trailing 'Z'.
    """
    if not isinstance(value, str) or not value.strip():
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
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def rental_days(event_start: datetime, event_end: datetime) -> int:
    """Inclusive whole-day span (PRD §3.3 / scaffold RentalOrder.rental_days):
    floor((event_end - event_start)/1 day) + 1, always >= 1 for a valid window.
    """
    delta = event_end - event_start
    return (delta // ONE_DAY) + 1


def windows_overlap_inclusive_days(a_start: datetime, a_end: datetime,
                                   b_start: datetime, b_end: datetime) -> bool:
    """Inclusive day-span overlap test (PRD §2.7).

    "Two day-spans overlap when each begins on or before the other ends; a
    reservation that ends on the very day another begins is treated as
    overlapping, since both occupy that shared day." This is the closed
    interval test: a_start <= b_end AND b_start <= a_end.
    """
    return a_start <= b_end and b_start <= a_end
