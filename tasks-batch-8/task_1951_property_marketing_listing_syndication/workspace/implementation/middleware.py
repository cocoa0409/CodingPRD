"""Auth header extraction, role checks, ownership, body and field validators,
pagination. Validation order follows PRD section 2.9."""
from flask import request

import clock
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

ROLES = {
    "ListingAgent",
    "MarketingCoordinator",
    "ComplianceOfficer",
    "MarketingDirector",
    "PortalWebhook",
}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or invalid authentication headers")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, "Role not permitted for this endpoint")


def check_listing_ownership(role, uid, listing):
    if role == "ListingAgent" and listing["agent_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "ListingAgent does not own this listing")


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def invalid(msg):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def f_str(data, key, required=False):
    v = data.get(key)
    if v is None:
        if required:
            raise invalid(f"{key} is required")
        return None
    if not isinstance(v, str):
        raise invalid(f"{key} must be a string")
    return v


def f_int(data, key, required=False):
    v = data.get(key)
    if v is None:
        if required:
            raise invalid(f"{key} is required")
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid(f"{key} must be an integer")
    return v


def f_num(data, key, required=False):
    v = data.get(key)
    if v is None:
        if required:
            raise invalid(f"{key} is required")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid(f"{key} must be a number")
    return v


def f_dt(data, key, required=False):
    v = data.get(key)
    if v is None:
        if required:
            raise invalid(f"{key} is required")
        return None
    try:
        return clock.parse_iso(v)
    except (ValueError, TypeError):
        raise invalid(f"{key} must be an ISO-8601 timestamp")


def f_enum(data, key, allowed, required=False):
    v = data.get(key)
    if v is None:
        if required:
            raise invalid(f"{key} is required")
        return None
    if v not in allowed:
        raise invalid(f"{key} must be one of {sorted(allowed)}")
    return v


def f_str_list(data, key, required=False):
    v = data.get(key)
    if v is None:
        if required:
            raise invalid(f"{key} is required")
        return None
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise invalid(f"{key} must be an array of strings")
    return v


def paginate(items):
    """Parse and validate limit/offset query params and slice the items."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise invalid("offset must be an integer")
        if offset < 0:
            raise invalid("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
