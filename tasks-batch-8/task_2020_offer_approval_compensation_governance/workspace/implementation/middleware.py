"""Auth header extraction, role checking, request-shape validation helpers."""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE, ERR_INVALID_REQUEST

ROLES = [
    "HRAdmin", "HiringManager", "Recruiter", "CompAnalyst", "FinanceController",
    "DepartmentDirector", "VPPeople", "BackgroundScreener", "Candidate",
]


def get_actor():
    """Priority 1: headers present, role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, allowed):
    """Priority 3: endpoint role membership."""
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED_ROLE, f"Role {role} is not permitted on this endpoint")


def get_json_body():
    if not request.is_json:
        raise_err(ERR_INVALID_REQUEST, "Request body must be JSON")
    try:
        body = request.get_json(force=False)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None or not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def validate_fields(body, required, optional):
    """Priority 2: required fields present, unknown fields rejected."""
    allowed = set(required) | set(optional)
    for key in body:
        if key not in allowed:
            raise_err(ERR_INVALID_REQUEST, f"Unknown field: {key}")
    for key in required:
        if key not in body or body[key] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")


def req_string(body, key, required=True):
    v = body.get(key)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return None
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be a string")
    return v


def req_enum(body, key, values, required=True, default=None):
    v = body.get(key)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return default
    if not isinstance(v, str) or v not in values:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be one of {values}")
    return v


def req_int(body, key, required=True, min_value=None, allow_zero=False, default=None):
    v = body.get(key)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be an integer")
    if not allow_zero and min_value is not None and v < min_value:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be >= {min_value}")
    if allow_zero and v < 0:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be >= 0")
    return v


def req_number(body, key, required=True, min_value=None, default=None):
    v = body.get(key)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be a number")
    if min_value is not None and v < min_value:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be >= {min_value}")
    return v


def get_pagination():
    """limit/offset query params; limit must be within [1,100] (ERR_INVALID_REQUEST)."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be within [1, 100]")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
