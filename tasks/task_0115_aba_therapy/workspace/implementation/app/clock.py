"""Per-clinic logical clock helpers and ISO 8601 utilities.

PRD §2.5: each Clinic carries a logical clock field `now_ts` advanced only via
POST /_clock/advance. The deterministic epoch is 2025-01-01T00:00:00.000Z.
"""
from datetime import datetime, timedelta, timezone

from .errors import APIError


DETERMINISTIC_EPOCH = "2025-01-01T00:00:00.000Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 instant; returns aware UTC datetime."""
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


def add_seconds(base_iso: str, seconds: int) -> str:
    dt = parse_iso(base_iso) + timedelta(seconds=seconds)
    return format_iso(dt)


def add_days(base_iso: str, days: int) -> str:
    dt = parse_iso(base_iso) + timedelta(days=days)
    return format_iso(dt)


def diff_minutes(start_iso: str, end_iso: str) -> int:
    """Whole-minute difference end - start (truncating any sub-minute fraction)."""
    delta = parse_iso(end_iso) - parse_iso(start_iso)
    return int(delta.total_seconds() // 60)


def diff_seconds(start_iso: str, end_iso: str) -> float:
    return (parse_iso(end_iso) - parse_iso(start_iso)).total_seconds()
