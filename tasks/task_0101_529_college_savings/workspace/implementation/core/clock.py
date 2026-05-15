"""Logical clock for the system. Time only moves forward when advanced via /_clock/advance."""

from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def now_iso(self) -> str:
        """ISO 8601 UTC with 3 fractional digits and trailing Z."""
        n = self._now
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"

    def advance_to(self, target: datetime) -> bool:
        """Advance forward. Returns False if target <= current."""
        if target <= self._now:
            return False
        self._now = target
        return True

    def tick(self):
        """Used internally on each mutation to ensure created_at/updated_at differ uniquely."""
        # Don't actually advance — test harness controls time via /_clock/advance.
        # But sequence-ordering for created_at uses a monotonic seq instead.
        pass


CLOCK = Clock()
