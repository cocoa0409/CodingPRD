"""Server logical clock (PRD 3.13).

At server startup the clock reads exactly 2026-04-01T00:00:00Z and never falls
back to wall-clock time before it is first set. The clock is advanced only by
POST /_clock/set_current_utc. Several transitions are time-driven: quote expiry,
warranty expiry, and the gate that an install job may not start before its
scheduled_start.
"""

from datetime import datetime, timezone

# Startup default — exactly 2026-04-01T00:00:00Z.
_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
