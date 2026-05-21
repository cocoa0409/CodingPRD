"""Time, ID, and arithmetic helpers."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone


_LOCK = threading.RLock()


def lock():
    """Global re-entrant lock used to serialize mutating operations."""
    return _LOCK


def new_id() -> str:
    """UUIDv4 string with no type prefix."""
    return str(uuid.uuid4())


def _format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def format_iso(dt: datetime) -> str:
    return _format_iso(dt)


def now_wall_iso() -> str:
    """Wall-clock timestamp used in response meta only."""
    return _format_iso(datetime.now(timezone.utc))


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected non-empty ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value: str) -> datetime:
    """Parse YYYY-MM-DD into a tz-aware UTC datetime at midnight."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected non-empty YYYY-MM-DD string")
    dt = datetime.strptime(value.strip(), "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)
