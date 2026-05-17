"""Logical-date clock — PRD §2.7.

The ClockState singleton carries only a `current_date` (YYYY-MM-DD). Tests
advance it via POST /_clock/advance. All date-based business decisions read
this value rather than the host wall clock.
"""
from datetime import date, timedelta

from .errors import APIError
from .store import get_store


def parse_date(value) -> date:
    """Parse a YYYY-MM-DD string into a date. Raises ERR_VALIDATION on failure."""
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", "date must be a string in YYYY-MM-DD format")
    s = value.strip()
    # Accept strictly YYYY-MM-DD; fromisoformat tolerates broader inputs but we want strict.
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise APIError("ERR_VALIDATION", f"invalid date: {value}")
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise APIError("ERR_VALIDATION", f"invalid date: {value}") from exc


def format_date(d: date) -> str:
    return d.isoformat()


def clock_today() -> date:
    return parse_date(get_store().clock["current_date"])


def clock_today_iso() -> str:
    return get_store().clock["current_date"]


def set_clock(target_iso: str) -> None:
    """Set ClockState.current_date. Caller is responsible for the monotonicity check."""
    d = parse_date(target_iso)
    get_store().clock["current_date"] = format_date(d)


def add_days(base_iso: str, days: int) -> str:
    d = parse_date(base_iso) + timedelta(days=days)
    return format_date(d)
