"""Authentication, RBAC, and body-validation helpers."""
from flask import request
from envelope import ApiError

VALID_ROLES = {
    "PlatformAdmin", "CatalogManager", "ProductionOperator",
    "SalesAgent", "Wholesaler",
}


def identity():
    """Return (user_id, role) after validating the auth headers (PRD 2.1)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    return uid, role


def require_roles(role, allowed):
    """PlatformAdmin overrides everything; else role must be in allowed."""
    if role == "PlatformAdmin":
        return
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403)


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, f"Missing or invalid field: {key}")
    return v


def req_int(body, key, minimum=None, exclusive_min=None):
    v = body.get(key)
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", 400, f"Missing or invalid integer field: {key}")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be >= {minimum}")
    if exclusive_min is not None and v <= exclusive_min:
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be > {exclusive_min}")
    return v


def req_num(body, key, exclusive_min=None):
    v = body.get(key)
    if not _is_num(v):
        raise ApiError("ERR_VALIDATION", 400, f"Missing or invalid number field: {key}")
    if exclusive_min is not None and v <= exclusive_min:
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be > {exclusive_min}")
    return v


def req_enum(body, key, choices):
    v = body.get(key)
    if v not in choices:
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be one of {sorted(choices)}")
    return v


def opt_enum(body, key, choices, default):
    if key not in body or body.get(key) is None:
        return default
    return req_enum(body, key, choices)


def opt_bool(body, key, default):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be a boolean")
    return v


def opt_int(body, key, default, minimum=None):
    if key not in body or body.get(key) is None:
        return default
    return req_int(body, key, minimum=minimum)


def paginate(items):
    """Apply limit/offset from query params to a list; return (page, limit, offset, total)."""
    total = len(items)
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    page = items[offset:offset + limit]
    return page, limit, offset, total
