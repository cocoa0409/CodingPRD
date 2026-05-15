"""Simulation clock - server-controlled per PRD §2.6."""
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
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError(f"Unparseable timestamp: {value!r}")


def format_iso(dt: Optional[datetime]) -> Optional[str]:
    """Format as ISO-8601 UTC with 3 fractional digits, suffix 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_INITIAL_EPOCH = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self) -> None:
        self._now: datetime = _INITIAL_EPOCH

    @property
    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt

    def reset(self) -> None:
        self._now = _INITIAL_EPOCH


CLOCK = _Clock()


def now_dt() -> datetime:
    return CLOCK.now


def now_iso_ms() -> str:
    return format_iso(CLOCK.now)  # type: ignore[return-value]


def days_between(later: datetime, earlier: datetime) -> int:
    """Floor of the number of whole days between two timestamps."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def first_of_month_at_or_after(dt: datetime) -> datetime:
    """The first day of the calendar month >= dt, in UTC, at 00:00:00."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # If dt is exactly the first of the month at 00:00:00.000, return dt.
    candidate = datetime(dt.year, dt.month, 1, 0, 0, 0, tzinfo=timezone.utc)
    if dt == candidate:
        return candidate
    # else next month's first
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return datetime(dt.year, dt.month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)
