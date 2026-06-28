"""Logical clock. PRD §3.9: server starts fixed at 2026-04-01T00:00:00Z; before
any set call the clock reads exactly this default (never wall-clock)."""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


def _parse_iso(s):
    # Accept trailing Z and optional fractional seconds.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock:
    def __init__(self):
        self._now = _parse_iso(DEFAULT_CLOCK_ISO)

    def reset(self):
        self._now = _parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, iso_str):
        self._now = _parse_iso(iso_str)

    def now(self):
        """Return the current logical clock as a tz-aware UTC datetime."""
        return self._now

    def now_iso(self):
        """ISO 8601 UTC with three fractional digits."""
        dt = self._now
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


clock = Clock()


def parse_iso(s):
    return _parse_iso(s)
