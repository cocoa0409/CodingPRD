"""Server-maintained logical clock (PRD §2.4).

Default logical time is exactly 2026-05-01T00:00:00Z and never falls back
to wall-clock time. Only the Court-only endpoint /trustee/_clock/set_current_utc
moves it.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = dt.astimezone(timezone.utc)


CLOCK = LogicalClock()
