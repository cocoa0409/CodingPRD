"""Datetime parsing/formatting and calendar-month arithmetic.

Timestamps are ISO 8601 UTC with three fractional digits (PRD 2.2 / 2.5).
"""
import calendar
import re
from datetime import datetime, timezone

from errors import err

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value, error_id="ERR_INVALID_REQUEST"):
    """Parse an ISO-8601 datetime string into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset; naive inputs are treated
    as UTC. Raises the given error on a malformed value.
    """
    if not isinstance(value, str) or not _ISO_RE.match(value.strip()):
        raise err(error_id, "Invalid ISO 8601 datetime: %r" % (value,))
    s = value.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Normalise +HHMM to +HH:MM for fromisoformat.
    m = re.search(r"([+-]\d{2})(\d{2})$", s)
    if m:
        s = s[: m.start()] + m.group(1) + ":" + m.group(2)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(error_id, "Invalid ISO 8601 datetime: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def add_months(dt, months):
    """Add a whole number of calendar months to a datetime (clamping day)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start, end):
    """Count complete (floored) whole calendar months from start to end.

    A month is "complete" only once the day-of-month/time has been reached or
    passed. Never less than zero. Used by provisional depreciation.
    """
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # Subtract one if the day/time-of-month boundary has not yet been reached.
    anchor = add_months(start, months)
    if anchor > end:
        months -= 1
    return max(0, months)


def ceil_months_between(start, end):
    """Count whole months from start to end, rounding a partial month UP.

    Used by the disposal (final) depreciation variant: a partial final month
    counts as a whole month (PRD 3.6).
    """
    if end <= start:
        return 0
    floor = whole_months_between(start, end)
    # If end is exactly on a whole-month boundary, no partial remainder.
    if add_months(start, floor) == end:
        return floor
    return floor + 1
