"""Station logical clock (PRD 2.4).

Before the clock has ever been set it reads exactly 2026-08-01T00:00:00Z; the
server never falls back to real wall-clock time for server-stamped fields.
"""
from datetime import datetime, timezone, timedelta

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self._current = DEFAULT_INSTANT

    def reset(self):
        self._current = DEFAULT_INSTANT

    def now(self):
        return self._current

    def set(self, instant):
        self._current = instant

    def now_iso(self):
        return format_instant(self._current)


clock = LogicalClock()


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(text):
    """Parse an ISO 8601 instant. Raises ValueError when unparseable."""
    if not isinstance(text, str):
        raise ValueError("not a string")
    s = text.strip()
    if not s:
        raise ValueError("empty")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    # normalise a bare '+0000' style offset
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def real_now_iso():
    return format_instant(datetime.now(timezone.utc))
