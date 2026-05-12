"""Logical clock and ISO 8601 helpers."""
from datetime import datetime, timezone


_logical_now: datetime = datetime.now(tz=timezone.utc)


def now() -> datetime:
    return _logical_now


def now_iso() -> str:
    return iso(_logical_now)


def set_now(dt: datetime) -> None:
    global _logical_now
    _logical_now = dt


def reset_now() -> None:
    """Reset the logical clock to wall-clock now (used by /_test/reset)."""
    global _logical_now
    _logical_now = datetime.now(tz=timezone.utc)


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional-digit milliseconds, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    if s is None:
        raise ValueError("timestamp is None")
    if not isinstance(s, str):
        raise ValueError("timestamp not a string")
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception as e:
        raise ValueError(f"invalid ISO 8601 timestamp: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
