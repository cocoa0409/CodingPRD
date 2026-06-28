"""Logical clock (PRD §2.4).

The entire platform reads time from a single logical clock rather than wall-clock
time, so test scenarios are deterministic. On server startup the clock reads
exactly 2026-01-01T00:00:00Z and stays there until explicitly set; it never falls
back to real wall-clock time.
"""
from datetime import datetime, timezone, timedelta

# Default startup instant: exactly 2026-01-01T00:00:00Z (PRD §2.4).
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _DEFAULT


def reset():
    """Reset the logical clock to its startup default. Called at module load so
    every fresh process boots at the default instant."""
    global _now
    _now = _DEFAULT


def now() -> datetime:
    """Current logical-clock instant (timezone-aware UTC)."""
    return _now


def set_now(dt: datetime) -> None:
    global _now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _now = dt.astimezone(timezone.utc)


def iso_now() -> str:
    """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    return format_iso(_now)


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC with milliseconds and a trailing 'Z' (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 instant; returns a timezone-aware UTC datetime.

    Raises ValueError if the value cannot be parsed.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)
