"""Logical UTC clock, the single shared timestamp renderer, and date helpers.

The server NEVER reads wall-clock time for any emitted value.  Every
server-stamped instant is produced by ``LOGICAL_CLOCK.now()`` and rendered by
``render_datetime`` so that every datetime the API emits carries exactly three
fractional-second digits and a trailing ``Z``.
"""

import re
from datetime import datetime, date, timedelta, timezone

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class InvalidDateTime(ValueError):
    pass


def parse_datetime(value):
    """Parse an ISO-8601 instant into an aware UTC datetime.

    Raises InvalidDateTime when the value is not a well-formed instant.
    """
    if isinstance(value, bool) or not isinstance(value, str):
        raise InvalidDateTime("datetime must be a string")
    s = value.strip()
    m = _DT_RE.match(s)
    if not m:
        raise InvalidDateTime("malformed datetime: %r" % value)
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError as exc:
        raise InvalidDateTime(str(exc))
    if offset is None or offset in ("Z", "z"):
        tz = timezone.utc
    else:
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date."""
    if isinstance(value, bool) or not isinstance(value, str):
        raise InvalidDateTime("date must be a string")
    m = _DATE_RE.match(value.strip())
    if not m:
        raise InvalidDateTime("malformed date: %r" % value)
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError as exc:
        raise InvalidDateTime(str(exc))


def render_datetime(dt):
    """THE shared renderer.  ISO-8601 UTC, exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def render_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


class LogicalClock(object):
    def __init__(self):
        self._now = parse_datetime(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def today(self):
        return self._now.date()

    def iso(self):
        return render_datetime(self._now)


LOGICAL_CLOCK = LogicalClock()


def add_days(d, days):
    return d + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def minutes_between(later, earlier):
    return (later - earlier).total_seconds() / 60.0
