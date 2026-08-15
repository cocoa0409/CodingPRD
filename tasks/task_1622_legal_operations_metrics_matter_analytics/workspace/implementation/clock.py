"""Logical clock. Defaults to 2026-08-01T00:00:00Z; never falls back to wall clock."""
from datetime import datetime, timezone

DEFAULT_ISO = "2026-08-01T00:00:00Z"


def iso_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_display(dt):
    if dt.microsecond:
        return iso_ms(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso8601(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def iso_ms(self):
        return iso_ms(self._now)

    def display(self):
        return iso_display(self._now)


CLOCK = LogicalClock()
