"""Shared helpers: pagination, body parsing, datetime parsing, ownership."""
from datetime import datetime, timezone

from flask import request

import errors
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_body():
    if request.data is None or request.data == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be an object.")
    return data


def parse_pagination():
    """Return (limit, offset). Raises ERR_INVALID_PAGINATION on out-of-bounds."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_INVALID_PAGINATION, 400, "Invalid limit.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(errors.ERR_INVALID_PAGINATION, 400, "limit out of bounds.")

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_INVALID_PAGINATION, 400, "Invalid offset.")
        if offset < 0:
            raise ApiError(errors.ERR_INVALID_PAGINATION, 400, "offset out of bounds.")

    return limit, offset


def paginate(items, limit, offset):
    """items already sorted. Returns (page_items, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


def parse_dt(value):
    """Parse an ISO 8601 datetime string to aware UTC datetime. Raises on bad input."""
    if not isinstance(value, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Invalid datetime.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Invalid datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_int(body, field, minimum=None):
    v = body.get(field)
    if not is_int(v):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {field} must be >= {minimum}.")
    return v


def opt_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not is_int(v):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {field} must be >= {minimum}.")
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {field} must be a boolean.")
    return v


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"Field {field} must be a non-empty string.")
    return v
