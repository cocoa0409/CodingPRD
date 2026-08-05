"""Datetime / date parsing and rendering.

PRD 2.4 pins ONE emission rule for every datetime the API emits, whether the
value was minted by the server (created_at, updated_at, requested_at, issued_at,
current_utc), echoed from caller input (started_at, scheduled_start,
scheduled_end) or derived from either (ends_at, due_at):

    ISO 8601 UTC with exactly three fractional-second digits and a trailing Z
    e.g. 2026-06-18T00:00:00.000Z

Inbound datetimes are accepted with or without fractional digits and are
normalised to that form before persisting, so a caller value of
`2026-03-01T00:00:00Z` round-trips as `2026-03-01T00:00:00.000Z` exactly like a
server stamp.  Calendar-date fields are always bare `YYYY-MM-DD`.
"""
import re
from datetime import date, datetime, timedelta

from constants import WEEKDAY_NAMES

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(Z|z|\+00:?00|-00:?00)$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_datetime(value):
    """Return a naive UTC datetime, or None when the value is not ISO 8601 UTC."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, _tz = m.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    try:
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second), micro
        )
    except ValueError:
        return None


def parse_date(value):
    """Return a date, or None when the value is not a bare YYYY-MM-DD string."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_datetime(dt):
    """Render a datetime with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def normalize_datetime(dt):
    """Truncate to millisecond precision, which is the persisted resolution."""
    if dt is None:
        return None
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def weekday_name(d):
    return WEEKDAY_NAMES[d.weekday()]


def last_day_of_month(d):
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def days_in_month(d):
    return last_day_of_month(d).day


def add_days(d, n):
    return d + timedelta(days=n)


def day_diff(later, earlier):
    return (later - earlier).days


def minute_of_day(dt):
    return dt.hour * 60 + dt.minute
