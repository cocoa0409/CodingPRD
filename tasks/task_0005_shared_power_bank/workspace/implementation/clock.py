from datetime import datetime, timezone, timedelta


class LogicalClock:
    def __init__(self):
        self._now = datetime.now(tz=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, instant: datetime) -> None:
        self._now = instant

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)

    def reset(self) -> None:
        self._now = datetime.now(tz=timezone.utc)


clock = LogicalClock()
