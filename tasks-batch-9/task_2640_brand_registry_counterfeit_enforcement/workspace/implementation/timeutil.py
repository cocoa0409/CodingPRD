"""Timestamp formatting/parsing and the business-day deadline walk."""

import re
from datetime import date, datetime, timedelta, timezone

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def iso(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    if isinstance(value, datetime):
        v = value.astimezone(timezone.utc)
        return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
            v.year, v.month, v.day, v.hour, v.minute, v.second,
            v.microsecond // 1000,
        )
    if isinstance(value, date):
        return value.isoformat()
    return value


def parse_datetime(raw):
    """Parse an ISO 8601 instant.  Returns None when the value is not a
    well-formed timestamp."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    m = _TS_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * delta).replace(tzinfo=timezone.utc)


def parse_date(raw):
    """Parse a strict YYYY-MM-DD calendar date."""
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    m = _DATE_RE.match(raw.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def add_business_days(start, count):
    """PRD 2.5: day zero is never counted; the cursor advances one calendar day
    at a time and only Monday-Friday landings decrement the allowance.  The
    time of day is preserved and weekend starts are NOT snapped forward."""
    cursor = start
    remaining = int(count)
    while remaining > 0:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor
