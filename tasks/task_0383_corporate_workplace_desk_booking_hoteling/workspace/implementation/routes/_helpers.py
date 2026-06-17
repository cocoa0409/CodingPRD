"""Shared route helpers: pagination, body parsing, existence lookups, serialization."""
from __future__ import annotations

from typing import Any, Optional
from flask import request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_PAGINATION,
    ERR_NOT_FOUND,
)


# ---- pagination (PRD §2.3): limit default 10 [1,100], offset default 0 >=0 --

def parse_pagination():
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    limit = 10 if raw_limit is None else raw_limit
    offset = 0 if raw_offset is None else raw_offset
    try:
        limit_i = int(limit)
        offset_i = int(offset)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_PAGINATION, 422, "limit/offset must be integers")
    if limit_i < 1 or limit_i > 100:
        raise APIError(ERR_INVALID_PAGINATION, 422, "limit must be in [1,100]")
    if offset_i < 0:
        raise APIError(ERR_INVALID_PAGINATION, 422, "offset must be >= 0")
    return limit_i, offset_i


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    return items[offset:offset + limit], total


def order_by_created(items: list) -> list:
    """Sort by creation timestamp ascending; ties broken by monotonic _seq."""
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("_seq", 0)))


# ---- body parsing ----------------------------------------------------------

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


def require_str(body: dict, field: str, allow_empty: bool = False, max_len: Optional[int] = None):
    v = body.get(field)
    if not isinstance(v, str) or isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a string")
    if not allow_empty and v.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be non-empty")
    if max_len is not None and len(v) > max_len:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} exceeds max length {max_len}")
    return v


def require_int(body: dict, field: str, minimum: Optional[int] = None, maximum: Optional[int] = None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be <= {maximum}")
    return v


def optional_int(body: dict, field: str, default: int, minimum: Optional[int] = None,
                 maximum: Optional[int] = None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum, maximum)


def optional_bool(body: dict, field: str, default: bool):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a boolean")
    return v


# ---- existence lookups (raise ERR_NOT_FOUND, 404) --------------------------

def _get_or_404(store: dict, ident: str, what: str):
    obj = store.get(ident)
    if obj is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")
    return obj


def get_site(ident: str):
    return _get_or_404(db.sites, ident, "Site")


def get_floor(ident: str):
    return _get_or_404(db.floors, ident, "Floor")


def get_neighborhood(ident: str):
    return _get_or_404(db.neighborhoods, ident, "Neighborhood")


def get_seat(ident: str):
    return _get_or_404(db.seats, ident, "Seat")


def get_room(ident: str):
    return _get_or_404(db.rooms, ident, "Room")


def get_employee(ident: str):
    return _get_or_404(db.employees, ident, "Employee")


def get_reservation(ident: str):
    return _get_or_404(db.reservations, ident, "Reservation")


def get_amenity(ident: str):
    return _get_or_404(db.amenity_requests, ident, "AmenityRequest")


def get_visitor_pass(ident: str):
    return _get_or_404(db.visitor_passes, ident, "VisitorPass")
