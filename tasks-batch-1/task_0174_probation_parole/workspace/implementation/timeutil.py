"""ISO 8601 UTC datetime helpers.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional-second digits.
"""
from datetime import datetime, timezone


def iso_now(dt):
    """Format a datetime as ISO 8601 UTC with milliseconds and a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset; assumes UTC when naive.
    Returns None if the value cannot be parsed.
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try plain date.
        try:
            dt = datetime.strptime(value.strip(), "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_months_between(start, end):
    """Whole calendar months elapsed from start to end, floored, never < 0.

    Counts the number of completed month-anniversaries of `start` that have
    occurred on or before `end`.  Two-and-a-half months old -> 2.
    """
    if start is None or end is None:
        return 0
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # If we haven't yet reached the day-of-month/time-of-day anniversary in the
    # final month, that month is not yet complete: subtract one.
    if months > 0:
        anchor_day = start.day
        # Compare the calendar position within the month.
        if (end.day, end.hour, end.minute, end.second, end.microsecond) < (
            anchor_day,
            start.hour,
            start.minute,
            start.second,
            start.microsecond,
        ):
            months -= 1
    return max(months, 0)
