"""Logical clock. Starts at 2026-08-01T00:00:00Z; never falls back to wall time."""
from datetime import datetime, timezone

_INITIAL = "2026-08-01T00:00:00Z"


def _parse_iso(s):
    if s is None:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_INITIAL)

    def now(self):
        return self._now

    def now_iso(self):
        return _fmt(self._now)

    def set(self, to_iso8601):
        target = _parse_iso(to_iso8601)
        # clock moves forward only
        if target > self._now:
            self._now = target
        return self._now


def _fmt(dt):
    """ISO 8601 UTC with three fractional digits, Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


CLOCK = LogicalClock()


def now():
    return CLOCK.now()


def now_iso():
    return CLOCK.now_iso()


def fmt(dt):
    return _fmt(dt)


def parse(s):
    return _parse_iso(s)
