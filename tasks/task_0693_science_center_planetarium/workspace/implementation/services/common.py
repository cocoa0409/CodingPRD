"""Shared helpers: body parsing, pagination, field validation, serialization."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_PAGINATION_INVALID,
    ERR_VALIDATION,
)


def round_half_up(value):
    """Round a numeric value half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_body():
    """Parse the JSON body; missing body is treated as empty object.

    A body that is present but unparseable is ERR_INVALID_REQUEST.
    """
    if request.data is None or request.data == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    """Each named field must be present (not None). ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_string(body, field):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def require_int(body, field):
    require_fields(body, [field])
    v = body[field]
    # bool is a subclass of int; reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v


def require_enum(body, field, choices):
    v = require_string(body, field)
    if v not in choices:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(choices)}")
    return v


def validate_range(condition, message):
    """Generic semantic numeric/range check (ERR_VALIDATION, 422)."""
    if not condition:
        raise err(ERR_VALIDATION, message)


def parse_pagination():
    """Parse and validate limit/offset query params (PRD §2.3).

    limit defaults 10, range [1,100]; offset defaults 0, must be >= 0.
    Out of range -> ERR_PAGINATION_INVALID (400).
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_INVALID, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_PAGINATION_INVALID, "limit out of range [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_INVALID, "offset must be an integer")
        if offset < 0:
            raise err(ERR_PAGINATION_INVALID, "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (tie-broken by creation sequence), then slice.

    Returns (page_items, pagination_meta).
    """
    ordered = sorted(records, key=lambda r: r["_created_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = offset + limit < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta
