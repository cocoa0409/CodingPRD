"""Logical UTC clock. Startup default 2026-05-01T00:00:00Z, never wall-clock."""
from datetime import datetime, timezone, timedelta

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def reset(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, iso_string):
        dt = parse_iso(iso_string)
        self._now = dt
        return self

    def now_iso(self):
        return to_iso_millis(self._now)


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("bad iso")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso_millis(dt):
    # ISO 8601 UTC with exactly three fractional digits, trailing Z
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


clock = Clock()
