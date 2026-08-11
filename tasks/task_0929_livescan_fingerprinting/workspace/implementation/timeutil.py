"""Datetime / date handling.

PRD 2.4: every datetime this API returns is rendered as ISO 8601 UTC with exactly
three fractional-second digits and a trailing Z, regardless of how the value
arrived.  Six fields are plain YYYY-MM-DD dates and one is a plain YYYY-MM
period key; they are never widened into datetimes.

PRD 2.6: every instant comes from the server-held logical clock.  Wall-clock time
is never consulted anywhere in this package.
"""

import datetime as _dt
import re

UTC = _dt.timezone.utc

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_instant(value):
    """Parse a caller supplied ISO 8601 instant into an aware UTC datetime.

    Returns None when the value is not a well formed instant.
    """
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    try:
        naive = _dt.datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second), micro
        )
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = _dt.timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        naive = naive - sign * offset
    return naive.replace(tzinfo=UTC)


def render_instant(value):
    """The single rendering path for every instant this API emits."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    millis = value.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        millis,
    )


def parse_date(value):
    """Parse a plain YYYY-MM-DD string into a date, or None when malformed."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def is_period_key(value):
    if not isinstance(value, str):
        return False
    m = _PERIOD_RE.match(value.strip())
    if not m:
        return False
    return 1 <= int(m.group(2)) <= 12


def render_date(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def add_days(instant, days):
    return instant + _dt.timedelta(days=days)


def add_date_days(date_value, days):
    return date_value + _dt.timedelta(days=days)


def add_minutes(instant, minutes):
    return instant + _dt.timedelta(minutes=minutes)


def add_hours(instant, hours):
    return instant + _dt.timedelta(hours=hours)


def date_of(instant):
    """The UTC date part of an instant -- 'the clock date' of PRD 2.6."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC).date()


def whole_days_between(from_date, to_date):
    return (to_date - from_date).days
