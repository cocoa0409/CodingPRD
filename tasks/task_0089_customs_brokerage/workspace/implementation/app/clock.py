"""Logical clock — advanced via POST /customs/_clock/advance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
)


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
        pass
    for fmt in _ISO_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unparseable timestamp: {value!r}")


def format_iso(dt: Optional[datetime]) -> Optional[str]:
    """Format as ISO-8601 UTC with 3 fractional digits, suffix 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_INITIAL_EPOCH = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self) -> None:
        # Initial clock is a well-known fixed epoch (well before any
        # PRD-relevant business window). This makes /customs/_clock/advance
        # idempotent forward-only from a known origin per PRD §2.12.
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


def add_hours(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)


def add_days(dt: datetime, days: float) -> datetime:
    return dt + timedelta(days=days)
