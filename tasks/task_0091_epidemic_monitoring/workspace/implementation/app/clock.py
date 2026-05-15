"""Logical clock — advanced via POST /_clock/advance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def parse_iso(value) -> datetime:
    """Parse an ISO-8601 timestamp; raises ValueError on failure."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"Invalid timestamp type: {type(value).__name__}")
    v = value.strip()
    try:
        if v.endswith("Z"):
            return datetime.fromisoformat(v[:-1] + "+00:00")
        return datetime.fromisoformat(v)
    except ValueError:
        raise ValueError(f"Unparseable timestamp: {value!r}")


def format_iso(dt: Optional[datetime]) -> Optional[str]:
    """ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class _Clock:
    def __init__(self) -> None:
        self._offset: timedelta = timedelta(0)

    @property
    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc) + self._offset

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._offset = dt - datetime.now(tz=timezone.utc)

    def advance(self, seconds: float) -> None:
        self._offset = self._offset + timedelta(seconds=float(seconds))

    def reset(self) -> None:
        self._offset = timedelta(0)


CLOCK = _Clock()


def now_dt() -> datetime:
    return CLOCK.now


def now_iso_ms() -> str:
    return format_iso(CLOCK.now)  # type: ignore[return-value]


def add_hours(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)


def add_days(dt: datetime, days: float) -> datetime:
    return dt + timedelta(days=days)


def floor_days_between(later: datetime, earlier: datetime) -> int:
    """Whole-day count via floor((later-earlier).total_seconds() / 86400)."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)
