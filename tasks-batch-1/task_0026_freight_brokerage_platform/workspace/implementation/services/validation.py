"""Reusable validation helpers.

Priority order (scaffold §1.4):
  1 auth headers present       (ERR_UNAUTHENTICATED, 401)
  2 role permitted             (ERR_UNAUTHORIZED, 403)
  3 path-param resources exist (ERR_RESOURCE_NOT_FOUND, 404)
  4 FK references in body      (ERR_FK_NOT_FOUND, 422)
  5 state transitions          (ERR_INVALID_STATE, 409)
  6 OCC version pinning        (ERR_STALE_VERSION, 412)
  7+ domain-specific business rules
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_FK_NOT_FOUND,
)


def require_fields(body: Dict[str, Any], fields: Iterable[str]) -> None:
    """Raise ERR_INVALID_REQUEST if any required field is missing/None."""
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


def require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an integer")
    return value


def require_int_or_str_int(value: Any, field_name: str) -> int:
    """Accept either int or numeric string."""
    if isinstance(value, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an integer")


def require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a number")


def lookup_path_or_404(store: Dict[str, Dict[str, Any]], rid: str, kind: str) -> Dict[str, Any]:
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, 404, f"{kind} not found: {rid}")
    return obj


def lookup_fk_or_422(store: Dict[str, Dict[str, Any]], rid: str, kind: str) -> Dict[str, Any]:
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_FK_NOT_FOUND, 422, f"Referenced {kind} not found: {rid}")
    return obj


def parse_iso_or_400(value: Any, field_name: str):
    try:
        dt = db.parse_iso_dt(value)
    except (ValueError, TypeError, AttributeError):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an ISO 8601 timestamp")
    if dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an ISO 8601 timestamp")
    return dt


def current_utc_dt():
    """Return the logical clock as a tz-aware datetime."""
    return db.parse_iso_dt(db.get_current_utc())
