"""Datetime parsing/formatting and calendar-month arithmetic.

All datetimes are normalized to UTC and truncated to second precision
(datetime comparisons in the system are made at second precision).
Output format is ISO 8601 UTC with three fractional digits.
"""
from datetime import datetime, timezone, timedelta


def parse_iso(value):
    """Parse an ISO-8601 datetime for ordinary entity fields.
    Accepts 'Z' or numeric offsets; naive values are treated as UTC.
    Returns an aware UTC datetime truncated to seconds, or None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    norm = s[:-1] + "+00:00" if s[-1] in ("Z", "z") else s
    try:
        dt = datetime.fromisoformat(norm)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def parse_iso_strict_utc(value):
    """For the logical-clock endpoint: must be valid ISO 8601 and explicitly
    UTC ('Z' suffix or +00:00 offset); anything else is rejected (None)."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    norm = s[:-1] + "+00:00" if s[-1] in ("Z", "z") else s
    try:
        dt = datetime.fromisoformat(norm)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    off = dt.utcoffset()
    if off is None or off != timedelta(0):
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Calendar-month arithmetic: preserves day-of-month, clamps to the last
    day of the target month when shorter, preserves time-of-day."""
    total = dt.month - 1 + months
    y = dt.year + total // 12
    m = total % 12 + 1
    if m == 12:
        first_next = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        first_next = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    last_day = (first_next - timedelta(days=1)).day
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)
