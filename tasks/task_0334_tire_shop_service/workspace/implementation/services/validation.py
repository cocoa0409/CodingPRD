"""Reusable validation helpers.

Field-level input validity (enum domain, numeric ranges, quantity >= 1, required
fields) is the lowest-priority validation (scaffold §1.4 priority 18) and surfaces
ERR_INVALID_REQUEST at HTTP 422.

Existence checks come in two flavours (PRD §2.6):
  - path-segment existence  -> ERR_NOT_FOUND (404)
  - body-FK existence       -> ERR_REFERENCE_NOT_FOUND (404)
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
)


# ---- primitive type/range checks --------------------------------------------


def require_fields(body: Dict[str, Any], fields: Iterable[str]) -> None:
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 422, f"Required field missing: {f}")


def require_string(value: Any, field_name: str, *, max_len: Optional[int] = None,
                   min_len: int = 1) -> str:
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field_name} must be a string")
    if len(value) < min_len:
        raise APIError(ERR_INVALID_REQUEST, 422,
                       f"{field_name} must be at least {min_len} characters")
    if max_len is not None and len(value) > max_len:
        raise APIError(ERR_INVALID_REQUEST, 422,
                       f"{field_name} must be at most {max_len} characters")
    return value


def require_enum(value: Any, choices: Iterable[str], field_name: str) -> str:
    if value not in choices:
        raise APIError(
            ERR_INVALID_REQUEST,
            422,
            f"Invalid value for {field_name}: {value!r}",
        )
    return value


def require_int(
    value: Any,
    field_name: str,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field_name} must be an integer")
    if min_value is not None and value < min_value:
        raise APIError(
            ERR_INVALID_REQUEST, 422, f"{field_name} must be >= {min_value}"
        )
    if max_value is not None and value > max_value:
        raise APIError(
            ERR_INVALID_REQUEST, 422, f"{field_name} must be <= {max_value}"
        )
    return value


def require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field_name} must be a boolean")
    return value


def optional_bool(value: Any, field_name: str, default: bool = False) -> bool:
    if value is None:
        return default
    return require_bool(value, field_name)


def optional_int(value: Any, field_name: str, default: int, *,
                 min_value: Optional[int] = None,
                 max_value: Optional[int] = None) -> int:
    if value is None:
        return default
    return require_int(value, field_name, min_value=min_value, max_value=max_value)


# ---- FK / existence helpers -------------------------------------------------


def lookup_path_or_404(
    store: Dict[str, Dict[str, Any]], rid: Optional[str], kind: str
) -> Dict[str, Any]:
    """Path-segment existence -> ERR_NOT_FOUND (404)."""
    if not isinstance(rid, str) or not rid:
        raise APIError(ERR_NOT_FOUND, 404, f"{kind} not found: {rid!r}")
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{kind} not found: {rid}")
    return obj


def lookup_fk_or_404(
    store: Dict[str, Dict[str, Any]], rid: Optional[str], kind: str
) -> Dict[str, Any]:
    """Body-FK existence -> ERR_REFERENCE_NOT_FOUND (404)."""
    if not isinstance(rid, str) or not rid:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, f"{kind} reference not found: {rid!r}")
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, f"{kind} reference not found: {rid}")
    return obj
