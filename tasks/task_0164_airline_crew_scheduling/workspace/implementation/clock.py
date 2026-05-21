"""Logical clock — only advanced via /_clock/advance."""
from datetime import datetime, timezone


_now: datetime = datetime.now(timezone.utc)


def get_now() -> datetime:
    return _now


def set_now(value: datetime) -> None:
    global _now
    _now = value


def format_iso(dt: datetime) -> str:
    """Render datetime in ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse ISO 8601 timestamps. Supports trailing 'Z' and offsets."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string.")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"Invalid ISO 8601 timestamp: {value}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
