"""The logical clock.

This module is the ONLY place in the implementation permitted to know about
absolute time, and it never reads wall-clock time at all: the clock starts at
CLOCK_DEFAULT_UTC and only ever moves because POST /_clock/set_current_utc
moved it.

It is also the SOLE PRODUCER of server-minted timestamp strings.  Every
server-minted instant in the API is rendered by `render()`, which emits ISO 8601
UTC with exactly three fractional digits and a trailing `Z`.  Caller-supplied
timestamp strings are never re-rendered; they are echoed byte-verbatim.
"""

from datetime import datetime, timedelta, timezone

from .constants import CLOCK_DEFAULT_UTC


def parse(value):
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


def render(dt):
    """The one and only renderer of server-minted timestamp strings."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class LogicalClock:
    def __init__(self):
        self._now = parse(CLOCK_DEFAULT_UTC)

    def now(self):
        return self._now

    def now_iso(self):
        return render(self._now)

    def set(self, dt):
        self._now = dt

    def plus_hours(self, hours):
        return self._now + timedelta(hours=hours)

    def plus_days(self, days):
        return self._now + timedelta(days=days)


CLOCK = LogicalClock()


def now():
    return CLOCK.now()


def now_iso():
    return CLOCK.now_iso()
