"""Test-driving logical clock (PRD §2.9).

On startup the logical clock reads exactly 2026-04-01T00:00:00Z and, until it is
explicitly set, never falls back to wall-clock time. A FranchiseAdmin may advance
it via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def reset(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
