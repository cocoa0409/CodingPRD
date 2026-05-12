"""Logical server clock for time-gated transitions."""
from datetime import datetime, timezone


class _Clock:
    def __init__(self):
        # Start at a deterministic baseline; tests will advance via /_clock/advance.
        self._now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set_now(self, new_now: datetime) -> None:
        # Always store as UTC aware
        if new_now.tzinfo is None:
            new_now = new_now.replace(tzinfo=timezone.utc)
        else:
            new_now = new_now.astimezone(timezone.utc)
        self._now = new_now


_clock = _Clock()


def current_clock() -> datetime:
    return _clock.now()


def set_clock(new_now: datetime) -> None:
    _clock.set_now(new_now)


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional digits and 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 timestamp accepting trailing 'Z' or offset."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
