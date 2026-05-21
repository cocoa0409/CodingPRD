"""Logical wall-clock advanced by PlatformAdmin via /api/_clock/advance."""
from datetime import datetime, timezone, timedelta


class LogicalClock:
    def __init__(self):
        self._offset = timedelta(0)
        self._base = datetime.now(timezone.utc)

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self._offset

    def advance(self, seconds: float) -> None:
        self._offset += timedelta(seconds=seconds)

    def iso(self) -> str:
        return format_iso(self.now())


def format_iso(dt: datetime) -> str:
    # ISO 8601 UTC with millisecond precision (3 fractional digits).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
