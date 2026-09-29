"""Logical clock and date arithmetic (PRD §2.5)."""

import calendar
from datetime import datetime, timedelta, timezone

from config import DEFAULT_LOGICAL_CLOCK


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


_state = {"now": parse_instant(DEFAULT_LOGICAL_CLOCK)}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    """Calendar-month arithmetic: same day-of-month, clamped, time preserved."""
    if dt is None:
        return None
    total = (dt.year * 12) + (dt.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
