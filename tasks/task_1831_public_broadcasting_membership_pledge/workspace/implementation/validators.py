"""Request body validation helpers (priority 0: ERR_INVALID_REQUEST)."""

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def invalid(msg):
    raise ApiError(ERR_INVALID_REQUEST[0], msg, ERR_INVALID_REQUEST[1])


def get_json_body(required=True):
    body = None
    try:
        body = db_flask_get_json()
    except Exception:
        invalid("Request body must be valid JSON")
    if body is None:
        if required:
            invalid("Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        invalid("Request body must be a JSON object")
    return body


def db_flask_get_json():
    from flask import request
    return request.get_json(silent=True)


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        invalid(f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        invalid(f"Field '{field}' must be a string")
    return v


def req_int(body, field, min_val=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        invalid(f"Field '{field}' is required and must be an integer")
    if min_val is not None and v < min_val:
        invalid(f"Field '{field}' must be >= {min_val}")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        invalid(f"Field '{field}' must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        invalid(f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_dt(body, field):
    v = body.get(field)
    if v is None:
        invalid(f"Field '{field}' is required")
    dt = db.parse_dt(v)
    if dt is None:
        invalid(f"Field '{field}' must be a valid ISO 8601 datetime")
    return dt


def parse_pagination(args):
    """Parse limit/offset query params with scaffold defaults."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer")
        if offset < 0:
            invalid("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted by created_at ASC. Returns (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def not_found(msg="Referenced resource id does not exist"):
    raise ApiError(ERR_NOT_FOUND[0], msg, ERR_NOT_FOUND[1])


def sort_created(items):
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
