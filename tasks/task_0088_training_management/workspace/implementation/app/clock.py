"""Logical clock — advanced via POST /training/_clock/advance and used for time-gated transitions."""
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


class _Clock:
    def __init__(self) -> None:
        self._now: datetime = datetime.now(tz=timezone.utc)

    @property
    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt

    def reset(self) -> None:
        self._now = datetime.now(tz=timezone.utc)


CLOCK = _Clock()


def now_dt() -> datetime:
    return CLOCK.now


def now_iso_ms() -> str:
    return format_iso(CLOCK.now)  # type: ignore[return-value]


def add_months(dt: datetime, months: int) -> datetime:
    """Add a number of months to a datetime, preserving day-of-month when possible."""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    # Handle day overflow (e.g., Jan 31 + 1 month → Feb 28/29)
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day <= 0:
                raise


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_years(dt: datetime, years: int) -> datetime:
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 + 1 year on non-leap year
        return dt.replace(year=dt.year + years, day=dt.day - 1)
