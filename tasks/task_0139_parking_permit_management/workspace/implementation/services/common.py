"""Shared route helpers: existence lookups, field validation, ownership,
list helpers, normalization."""
from __future__ import annotations

from typing import Any, Dict, Optional

from flask import g

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
)
from response import ok_array, paginate_params, slice_page
from services.serialize import public_list

# ---- field validation (well-formedness, PRD §2.9) --------------------------


def require_fields(body: Dict[str, Any], *names: str) -> None:
    for n in names:
        if n not in body or body[n] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {n}")


def require_string(body: Dict[str, Any], name: str, required: bool = True) -> Optional[str]:
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be a non-empty string")
    return v


def require_int(body: Dict[str, Any], name: str, required: bool = True, minimum: Optional[int] = None,
                default: Optional[int] = None) -> Optional[int]:
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {minimum}")
    return v


def require_number(body: Dict[str, Any], name: str, required: bool = True, minimum=None, default=None):
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be a number")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {minimum}")
    return v


def require_enum(body: Dict[str, Any], name: str, allowed, required: bool = True,
                 default: Optional[str] = None) -> Optional[str]:
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be one of {sorted(allowed)}")
    return v


def require_datetime(body: Dict[str, Any], name: str, required: bool = True) -> Optional[str]:
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be an ISO-8601 datetime string")
    try:
        parsed = db.parse_iso_dt(v)
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} is not a valid ISO-8601 datetime")
    if parsed is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} is not a valid ISO-8601 datetime")
    return v


def normalize_plate(plate: str) -> str:
    """Normalize a license plate: uppercase, remove spaces (PRD §3.3)."""
    return "".join(plate.split()).upper()


# ---- existence lookups (ERR_NOT_FOUND, PRD §2.5) ---------------------------


def lookup(store: Dict[str, Dict[str, Any]], rid: Any) -> Dict[str, Any]:
    if not isinstance(rid, str) or rid not in store:
        raise APIError(ERR_NOT_FOUND, 404, "Referenced resource does not exist")
    return store[rid]


# ---- ownership (PRD §2.1 / §2.9 priority 5) --------------------------------


def require_owner_motorist(resource_motorist_id: Optional[str]) -> None:
    """Motorist ownership check. FacilityAdmin is never subject to it."""
    if g.user_role != "Motorist":
        return
    if resource_motorist_id != g.user_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Motorist does not own this resource")


def require_owner_merchant(resource_merchant_id: Optional[str]) -> None:
    if g.user_role != "Merchant":
        return
    if resource_merchant_id != g.user_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Merchant does not own this resource")


# ---- list / pagination helper ----------------------------------------------


def sorted_by_created(items) -> list:
    """Default list ordering: creation timestamp ascending (PRD §2.3).

    _seq is a monotonic insertion counter, a stable proxy for created_at order.
    """
    return sorted(items, key=lambda o: o["_seq"])


def list_response(items, args, presorted: bool = False):
    """Paginate + envelope a list of raw entity dicts."""
    limit, offset = paginate_params(args)
    if not presorted:
        items = sorted_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)
