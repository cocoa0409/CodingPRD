"""Server-side logical clock and ISO 8601 helpers per PRD §2.5."""
from datetime import datetime, timezone


# Server logical clock. Tests advance via POST /_clock/advance.
# Default to current wall time at process start.
_logical_now: datetime = datetime.now(tz=timezone.utc)


def now() -> datetime:
    """Return the current server logical-clock instant as an aware UTC datetime."""
    return _logical_now


def now_unix() -> int:
    """Return the current server logical-clock instant as integer unix seconds."""
    return int(_logical_now.timestamp())


def now_iso() -> str:
    return iso(_logical_now)


def set_now(dt: datetime) -> None:
    global _logical_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _logical_now = dt


def set_now_unix(seconds: int) -> None:
    set_now(datetime.fromtimestamp(int(seconds), tz=timezone.utc))


def reset_now() -> None:
    global _logical_now
    _logical_now = datetime.now(tz=timezone.utc)


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional-digit milliseconds, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
