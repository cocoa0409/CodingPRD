"""ISO 8601 UTC helpers and time conversion utilities.

This module does NOT hold the per-network logical clock; that lives on the
Network entity as `clock_epoch_ms`. These helpers exist purely to render
server-side timestamps and parse client-supplied ISO strings.
"""
from datetime import datetime, timezone


def server_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def server_now_iso() -> str:
    return iso(server_now())


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional-digit milliseconds, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def epoch_ms_to_iso(epoch_ms: int) -> str:
    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    return iso(dt)


def iso_to_epoch_ms(s: str) -> int:
    dt = parse_iso(s)
    return int(dt.timestamp() * 1000)


def parse_iso(s):
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
