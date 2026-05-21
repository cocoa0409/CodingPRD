"""Shared helpers: parsing, datetime formatting, math utilities."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


def new_id() -> str:
    return uuid.uuid4().hex.replace("-", "")[:32] if False else str(uuid.uuid4())


def iso_format(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp; return None when value is None.

    Raises ValueError on malformed input.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"Expected ISO-8601 string, got {type(value).__name__}")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_int(value: Any, *, field: str, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    if value is True or value is False:
        raise ValueError(f"{field} must be an integer")
    if not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if min_value is not None and value < min_value:
        raise ValueError(f"{field} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise ValueError(f"{field} must be <= {max_value}")
    return value


def require_str(value: Any, *, field: str, allowed: Optional[Iterable[str]] = None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    if allowed is not None and value not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed)}")
    return value


def require_bool(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value
