"""Shared field-shape validation helpers (scaffold §1.4 priority 14, PRD §2.11).

These raise ERR_INVALID_REQUEST (400) for missing/malformed/out-of-range fields.
They are invoked AFTER auth, existence, state, and the higher-priority business
checks per the §2.11 ordering — each route calls them at the appropriate point.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from errors import APIError, ERR_INVALID_REQUEST


def require_present(body: dict, field: str) -> Any:
    if field not in body or body[field] is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {field}")
    return body[field]


def require_str(body: dict, field: str, allow_empty: bool = False) -> str:
    v = require_present(body, field)
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be a string")
    if not allow_empty and v == "":
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must not be empty")
    return v


def require_int(body: dict, field: str, minimum: Optional[int] = None,
                maximum: Optional[int] = None) -> int:
    v = require_present(body, field)
    # Reject bools (bool is a subclass of int) and non-integers.
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be <= {maximum}")
    return v


def require_number(body: dict, field: str, minimum=None, maximum=None) -> float:
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be a number")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be <= {maximum}")
    return v


def require_enum(body: dict, field: str, members: Iterable[str]) -> str:
    v = require_str(body, field)
    if v not in set(members):
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"{field} must be one of {sorted(set(members))}")
    return v


def require_datetime(body: dict, field: str):
    """Validate that a field is a parseable ISO-8601 datetime string."""
    from db import parse_iso_dt
    v = require_str(body, field)
    try:
        dt = parse_iso_dt(v)
    except (ValueError, TypeError):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO-8601 datetime")
    if dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO-8601 datetime")
    return dt
