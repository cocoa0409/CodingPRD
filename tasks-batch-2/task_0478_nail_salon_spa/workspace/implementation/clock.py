"""Logical clock (PRD §2.5).

At server startup the clock is fixed at 2026-01-01T00:00:00Z and, until it is
explicitly advanced via POST /_clock/set_current_utc, it reads exactly this
default; it never falls back to real time.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
