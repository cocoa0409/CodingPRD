"""Logical UTC clock and the single shared datetime renderer.

The server NEVER reads wall-clock time for any emitted value.  Every
server-stamped instant is produced by ``LOGICAL_CLOCK.now()`` (a datetime) and
rendered by ``render_datetime`` so it carries exactly three fractional-second
digits and a trailing ``Z``.

Input-supplied datetimes (survey window_start / window_end) are stored and
echoed *verbatim* -- they are never re-rendered -- so a plain ``...Z`` comes
back plain and a ``...500Z`` keeps its milliseconds.
"""

import re
from datetime import datetime, date, timedelta, timezone

from constants import DEFAULT_CLOCK_ISO

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class InvalidDateTime(ValueError):
    pass


def parse_datetime(value):
    """Parse an ISO-8601 instant into an aware UTC datetime."""
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


def render_datetime(dt):
    """THE shared renderer for system timestamps: ISO-8601 UTC, 3 frac digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def add_days(dt, days):
    return dt + timedelta(days=days)


class LogicalClock(object):
    def __init__(self):
        self._now = parse_datetime(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


LOGICAL_CLOCK = LogicalClock()
