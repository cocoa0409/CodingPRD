"""Logical clock for date-dependent rules.

At startup the clock reads exactly 2026-04-01T00:00:00Z and never falls back to
wall-clock time. A coordinator may advance it via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def reset(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def iso(self):
        # ISO 8601 UTC with three fractional digits.
        return self._now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{self._now.microsecond // 1000:03d}Z"


clock = Clock()
