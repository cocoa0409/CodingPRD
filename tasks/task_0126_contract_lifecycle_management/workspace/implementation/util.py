"""Datetime parsing/formatting and calendar-month arithmetic (PRD §2.10, §3.6)."""

import calendar
from datetime import datetime, timezone

from errors import invalid_request


def parse_iso8601(value, field="datetime"):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' as well as explicit offsets. Raises ERR_INVALID_REQUEST
    when the value is not a valid ISO 8601 string.
    """
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be an ISO 8601 string." % field)
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise invalid_request("Field '%s' is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_millis(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and a 'Z'."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_calendar_months(dt, months):
    """Add `months` calendar months to dt, clamping day-of-month to month end.

    PRD §3.6: add term to the month component, carrying into years; if the target
    day does not exist, clamp to the last day of the target month. Time-of-day is
    preserved; all arithmetic is UTC.
    """
    dt = dt.astimezone(timezone.utc)
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)
