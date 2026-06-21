"""Reusable validation helpers used across route handlers."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable

from datetime import datetime

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)


def require_fields(body: Dict[str, Any], fields: Iterable[str]) -> None:
    """Raise ERR_INVALID_REQUEST if any required field is missing (None) or absent."""
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Required field missing: {f}")


def require_enum(value: Any, choices: Iterable[str], field_name: str) -> None:
    if value not in choices:
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"Invalid value for {field_name}: {value}"
        )


def require_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a non-empty string")


def require_int(value: Any, field_name: str, *, min_value=None, max_value=None) -> int:
    """Validate integer (rejects bools). Optional bounds inclusive."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an integer")
    if min_value is not None and value < min_value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be <= {max_value}")
    return value


def require_number(value: Any, field_name: str, *, min_value=None, max_value=None):
    """Validate numeric (int or float, but not bool). Optional bounds inclusive."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a number")
    if min_value is not None and value < min_value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be <= {max_value}")
    return value


def require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a boolean")
    return value


def lookup_or_404(store: Dict[str, Dict[str, Any]], rid: str, kind: str) -> Dict[str, Any]:
    """Raise ERR_NOT_FOUND if the id is missing or absent in the store."""
    if not isinstance(rid, str) or not rid:
        raise APIError(ERR_NOT_FOUND, 404, f"{kind} not found: {rid}")
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{kind} not found: {rid}")
    return obj


# Time helpers ---------------------------------------------------------------


def parse_clock_dt() -> datetime:
    """Return the server's logical clock as a tz-aware UTC datetime."""
    dt = db.parse_iso_dt(db.get_current_utc())
    assert dt is not None
    return dt


def parse_request_dt(value: Any, field_name: str) -> datetime:
    """Parse an ISO-8601 datetime from a request payload."""
    if not isinstance(value, str) or not value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an ISO 8601 timestamp")
    try:
        dt = db.parse_iso_dt(value)
    except (ValueError, TypeError, AttributeError):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an ISO 8601 timestamp")
    if dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an ISO 8601 timestamp")
    return dt


# Email -----------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def require_email(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _EMAIL_RE.match(value):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a valid email")
    return value


# Package code constraint (uppercase A-Z, 3..16) -------------------------------

_CODE_RE = re.compile(r"^[A-Z]{3,16}$")


def require_package_code(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _CODE_RE.match(value):
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"{field_name} must be uppercase A-Z, 3..16 chars",
        )
    return value
