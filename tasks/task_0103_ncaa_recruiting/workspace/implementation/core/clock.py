"""Logical clock. Time only advances via /_clock/advance."""

from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def now_iso(self) -> str:
        return iso_format(self._now)

    def advance_to(self, target: datetime) -> bool:
        if target <= self._now:
            return False
        self._now = target
        return True


def iso_format(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse ISO 8601 string. Accepts trailing Z. Returns aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


CLOCK = Clock()
