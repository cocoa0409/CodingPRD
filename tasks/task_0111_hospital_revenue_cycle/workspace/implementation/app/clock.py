"""Logical clock - advanced via POST /_clock/advance (PRD §2.11)."""
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


# Initial epoch chosen to be a date in the "current year" range that tests can target.
# Tests typically advance the clock; default reset value is 2026-01-01 UTC so plan_year=2026
# matches by default.
_INITIAL_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


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


def days_between_floor(later: datetime, earlier: datetime) -> int:
    """floor((later - earlier) / 1 day) per scaffold §1.3 bad_debt_writeoff_calc."""
    delta_ms = int((later - earlier).total_seconds() * 1000)
    if delta_ms < 0:
        return 0
    return delta_ms // 86_400_000
