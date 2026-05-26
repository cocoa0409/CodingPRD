"""Reusable validation helpers (used across routes).

These functions raise ApiError with the correct error_id/http_status from
the PRD/scaffold catalogue. They centralise the priority order described
in PRD §2.8.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dateutil import parser as dateutil_parser

from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_NOT_FOUND,
    ERR_NOT_FOUND,
)


def require_dict(body: Any) -> Dict[str, Any]:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def require_str(body: Dict[str, Any], field: str, *, min_len: int = 1) -> str:
    v = body.get(field)
    if not isinstance(v, str) or len(v) < min_len:
        raise err(ERR_INVALID_REQUEST, f"{field} must be a non-empty string")
    return v


def require_int(body: Dict[str, Any], field: str) -> int:
    v = body.get(field)
    # bool is a subclass of int in python; explicitly reject.
    if not isinstance(v, int) or isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return v


def require_positive_int(body: Dict[str, Any], field: str, *, max_value: Optional[int] = None) -> int:
    v = require_int(body, field)
    if v <= 0:
        raise err(ERR_INVALID_REQUEST, f"{field} must be strictly positive")
    if max_value is not None and v > max_value:
        raise err(ERR_INVALID_REQUEST, f"{field} must be <= {max_value}")
    return v


def require_enum(body: Dict[str, Any], field: str, allowed: set) -> str:
    v = require_str(body, field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return v


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime."""
    try:
        dt = dateutil_parser.isoparse(value)
    except (ValueError, TypeError) as exc:
        raise err(ERR_INVALID_REQUEST, f"invalid ISO 8601 timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def must_exist(collection: Dict[str, Dict], key: str, *, path: bool):
    """Lookup helper: raise ERR_NOT_FOUND for path params, ERR_REFERENCED_NOT_FOUND for body FKs."""
    obj = collection.get(key)
    if obj is None:
        raise err(ERR_NOT_FOUND if path else ERR_REFERENCED_NOT_FOUND)
    return obj
