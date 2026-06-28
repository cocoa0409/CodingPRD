"""Server logical clock.

PRD 2.4: At startup the logical clock reads exactly 2026-01-01T00:00:00Z, and
before any client call it reads precisely this default and never falls back to
wall-clock time. The clock is advanced only by POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone

# Startup default — exactly 2026-01-01T00:00:00Z.
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
