"""The logical clock and the two rendering conventions of PRD section 2.4.

Nothing in this module (or anywhere else in the implementation) reads the
machine's wall clock for a business rule.  The logical clock starts at the
PRD-declared default and moves only through POST /_clock/set_current_utc.
"""

import calendar
import re
from datetime import datetime, date, timedelta

_ISO_INSTANT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def parse_instant(text):
    """Parse an ISO 8601 instant into a naive UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    m = _ISO_INSTANT.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def render_instant(dt):
    """Server-written instant: YYYY-MM-DDTHH:MM:SS.mmmZ, three digits always."""
    if dt is None:
        return None
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def render_date(d):
    """Server-derived calendar date: plain YYYY-MM-DD, no zone, no time."""
    if d is None:
        return None
    return "{:04d}-{:02d}-{:02d}".format(d.year, d.month, d.day)


def render_month(d):
    if d is None:
        return None
    return "{:04d}-{:02d}".format(d.year, d.month)


def parse_date(text):
    """Parse a caller-supplied plain calendar date, or None when malformed."""
    if not isinstance(text, str):
        return None
    m = _ISO_DATE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_month(text):
    """Parse a caller-supplied YYYY-MM month, returning (year, month)."""
    if not isinstance(text, str):
        return None
    m = _ISO_MONTH.match(text.strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if month < 1 or month > 12:
        return None
    return (year, month)


def month_of_date_string(text):
    """The YYYY-MM prefix of a caller-supplied or server-written date string."""
    if not isinstance(text, str):
        return None
    m = _ISO_DATE.match(text.strip())
    if not m:
        return None
    return "{}-{}".format(m.group(1), m.group(2))


def days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


def is_business_day(d):
    return d.isoweekday() <= 5


def add_business_days(d, n):
    """Advance n business days; the starting date itself is not counted."""
    for _ in range(n):
        d = d + timedelta(days=1)
        while not is_business_day(d):
            d = d + timedelta(days=1)
    return d


def roll_to_business_day(d):
    while not is_business_day(d):
        d = d + timedelta(days=1)
    return d
