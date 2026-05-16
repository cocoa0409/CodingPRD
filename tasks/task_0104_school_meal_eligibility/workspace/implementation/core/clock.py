"""Logical server clock. PRD §2.8. Advanced only via POST /_clock/advance."""

from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def now_iso(self) -> str:
        """ISO 8601 UTC with 3 fractional digits and trailing Z."""
        n = self._now
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"

    def today_midnight(self) -> datetime:
        """UTC midnight of the current day per the logical clock."""
        n = self._now
        return datetime(n.year, n.month, n.day, tzinfo=timezone.utc)

    def advance_to(self, target: datetime) -> bool:
        """Advance forward only. Returns False if target <= current."""
        if target <= self._now:
            return False
        self._now = target
        return True

    def set_to(self, target: datetime):
        """Privileged reset; used only by test reset endpoint."""
        self._now = target


CLOCK = Clock()
