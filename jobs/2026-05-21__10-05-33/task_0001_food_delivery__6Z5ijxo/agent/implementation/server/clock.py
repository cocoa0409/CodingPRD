from datetime import datetime, timedelta, timezone


class LogicalClock:
    def __init__(self):
        self._offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self._offset

    def advance(self, seconds: float) -> None:
        self._offset += timedelta(seconds=seconds)

    def reset(self) -> None:
        self._offset = timedelta(0)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def is_peak(dt: datetime) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    h = dt.hour
    if 11 <= h < 13:
        return True
    if 18 <= h < 20:
        return True
    return False
