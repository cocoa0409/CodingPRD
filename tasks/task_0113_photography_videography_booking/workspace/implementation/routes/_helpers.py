"""Shared route helpers: serialization, pagination, body parsing, validation,
ownership (PRD §2.3, §2.7, §2.8)."""
from __future__ import annotations

from typing import Any, List
from flask import request, g

from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import ROLE_STUDIO_ADMIN, ROLE_CLIENT, ROLE_PHOTOGRAPHER

# internal-only keys never exposed in API responses
_INTERNAL_KEYS = {"_seq"}


def serialize(entity: dict) -> dict:
    return {k: v for k, v in entity.items() if k not in _INTERNAL_KEYS}


def serialize_list(entities: List[dict]) -> List[dict]:
    return [serialize(e) for e in entities]


# ---- pagination (PRD §2.3) --------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    limit_i = 10
    offset_i = 0
    if limit is not None:
        try:
            limit_i = int(limit)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 422, "limit must be an integer")
        if limit_i < 1:
            limit_i = 1
        if limit_i > 100:
            limit_i = 100
    if offset is not None:
        try:
            offset_i = int(offset)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 422, "offset must be an integer")
        if offset_i < 0:
            offset_i = 0
    return limit_i, offset_i


def order_by_created_at(items: List[dict]) -> List[dict]:
    """Oldest first (PRD §2.3). Ties broken by insertion sequence."""
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


def paginate(items: List[dict], limit: int, offset: int):
    total = len(items)
    return items[offset:offset + limit], total


# ---- body parsing -----------------------------------------------------------
def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 422, "Body must be a JSON object")
    return body


def require_fields(body: dict, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 422, f"Missing required field: {f}")


def require_str(body: dict, field: str) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a non-empty string")
    return v


def require_enum(body: dict, field: str, allowed) -> str:
    v = body.get(field)
    if v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be one of {sorted(allowed)}")
    return v


def require_int(body: dict, field: str, *, min_value=None, gt=None) -> int:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be an integer")
    if gt is not None and not (v > gt):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be > {gt}")
    if min_value is not None and v < min_value:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be >= {min_value}")
    return v


def require_number(body: dict, field: str, *, gt=None, min_value=None, le=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a number")
    if gt is not None and not (v > gt):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be > {gt}")
    if min_value is not None and v < min_value:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be >= {min_value}")
    if le is not None and not (v <= le):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be <= {le}")
    return v


def optional_bool(body: dict, field: str, default: bool) -> bool:
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a boolean")
    return v


# ---- ownership (PRD §2.1, §2.7 priority 4) ----------------------------------
def assert_client_owns(booking: dict) -> None:
    """Client owns a Booking via client_id. StudioAdmin is exempt."""
    if g.user_role == ROLE_CLIENT and g.user_id != booking["client_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this booking")


def assert_photographer_owns(booking: dict) -> None:
    """Photographer owns ShootSchedule/Gallery via Booking.lead_photographer_id.
    StudioAdmin is exempt."""
    if g.user_role == ROLE_PHOTOGRAPHER and g.user_id != booking["lead_photographer_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")
