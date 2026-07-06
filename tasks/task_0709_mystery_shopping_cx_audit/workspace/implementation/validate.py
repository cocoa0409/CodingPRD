"""Body parsing & generic field validation helpers.

Malformed body (missing required field, wrong type, negative where >=0 required,
out-of-range enum) -> ERR_INVALID_REQUEST (PRD 5 / scaffold validation #21).
Pagination per PRD 2.3 (limit default 10, min 1, max 100; offset default 0).
"""
from flask import request

from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_body():
    """Return the JSON body as a dict; non-object bodies -> ERR_INVALID_REQUEST."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_str(body, field):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
    v = body[field]
    if not isinstance(v, str) or not v.strip():
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    return v


def require_int(body, field, minimum=None):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, minimum))
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, minimum))
    return v


def require_number(body, field):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    return float(v)


def require_bool(body, field):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (field, sorted(allowed)))
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (field, sorted(allowed)))
    return v


def require_object(body, field):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % field)
    v = body[field]
    if not isinstance(v, dict):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an object." % field)
    return v


def pagination():
    """Parse limit/offset query params (PRD 2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT:
            limit = PAGINATION_MIN_LIMIT
        elif limit > PAGINATION_MAX_LIMIT:
            limit = PAGINATION_MAX_LIMIT
    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
