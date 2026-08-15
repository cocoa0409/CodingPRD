"""Auth header extraction, role checking, pagination parsing."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
)

ROLES = {
    "CoopAdmin",
    "GinOperator",
    "ClassingClerk",
    "WarehouseManager",
    "CoopAccountant",
    "Grower",
}


def get_context():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        err_id, status = ERR_MISSING_OR_INVALID_USER_CONTEXT
        raise ApiError(err_id, "X-User-ID and X-User-Role headers must be present and non-empty", status)
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        err_id, status = ERR_MISSING_OR_INVALID_USER_CONTEXT
        raise ApiError(err_id, "Unrecognized role", status)
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        err_id, status = ERR_FORBIDDEN
        raise ApiError(err_id, f"Role {role} is not permitted on this endpoint", status)


def grower_owns(user_id, role, grower_id):
    """Grower-role callers may only act on their own grower chain."""
    if role == "Grower" and user_id != grower_id:
        err_id, status = ERR_FORBIDDEN
        raise ApiError(err_id, "Grower may only access own resources", status)


def parse_pagination():
    """limit (default 10, min 1, max 100), offset (default 0)."""
    args = request.args
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, "limit must be an integer", status)
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, "offset must be an integer", status)
    if limit < 1 or limit > 100:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "limit must be in [1, 100]", status)
    if offset < 0:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "offset must be >= 0", status)
    return limit, offset


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "Request body must be a JSON object", status)
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, f"Missing required field: {f}", status)


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, f"{field} must be an integer", status)
    if minimum is not None and v < minimum:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, f"{field} must be >= {minimum}", status)
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, f"{field} must be a number", status)
    return v
