"""Server logical clock.

Time-based lifecycle transitions (offer expiry, grace, lapse, termination,
contestability flip) are observed lazily against this clock. An Admin advances
it via POST /_clock/set_current_utc. State is process-local and reset on every
boot, satisfying the per-test-server isolation contract.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        # Default to real wall-clock UTC until a test sets it explicitly.
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)


clock = Clock()
