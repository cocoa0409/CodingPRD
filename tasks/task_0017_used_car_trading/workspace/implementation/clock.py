"""Virtual clock used by the test driver. All timestamps come from here."""

from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = None  # None means use real time

    def now(self) -> datetime:
        if self._now is not None:
            return self._now
        return datetime.now(timezone.utc)

    def set(self, dt: datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)


CLOCK = Clock()


def now() -> datetime:
    return CLOCK.now()


def iso(dt: datetime) -> str:
    """Return ISO 8601 UTC with millisecond precision and 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Truncate microseconds to milliseconds
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into a UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
