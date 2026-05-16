"""Simulated test clock + ISO 8601 utilities.

PRD §3.10 makes the system clock test-driven: the only way it advances is via
the POST /_clock/advance endpoint. The default value is the Unix epoch.
"""
from datetime import datetime, timedelta, timezone

from .errors import APIError
from .store import get_store


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 instant. Returns an aware UTC datetime."""
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", "timestamp must be a string in ISO 8601 format")
    s = value.strip()
    if s.endswith("Z"):
        s_norm = s[:-1] + "+00:00"
    else:
        s_norm = s
    try:
        dt = datetime.fromisoformat(s_norm)
    except ValueError as exc:
        raise APIError("ERR_VALIDATION", f"invalid timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now_dt() -> datetime:
    return parse_iso(get_store().clock["now"])


def clock_now_iso() -> str:
    return get_store().clock["now"]


def set_clock(target_now: str) -> None:
    dt = parse_iso(target_now)
    get_store().clock["now"] = format_iso(dt)


def add_hours(base_iso: str, hours: float) -> str:
    dt = parse_iso(base_iso) + timedelta(hours=hours)
    return format_iso(dt)


def add_days(base_iso: str, days: int) -> str:
    dt = parse_iso(base_iso) + timedelta(days=days)
    return format_iso(dt)
