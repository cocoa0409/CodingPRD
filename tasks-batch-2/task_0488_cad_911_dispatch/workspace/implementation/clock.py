"""Logical clock (PRD §2.4).

At startup, before any call is processed, the logical clock reads exactly
2026-01-01T00:00:00Z. It is advanced only by POST /_clock/set_current_utc and
never falls back to wall-clock time. Every *business* instant (received_at,
first_dispatch_at, first_onscene_at, enroute/onscene/cleared, closed_at, report
snapshot) is read from this clock so results are reproducible across runs.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
