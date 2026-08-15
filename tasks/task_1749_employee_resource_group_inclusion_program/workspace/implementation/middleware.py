"""Auth header extraction, role checks, request body and field validation,
pagination parsing. Validation pipeline order (PRD section 2.6):
1 auth context -> 2 role -> 3 schema -> 4 existence -> 4.5 OCC -> 5 state ->
6 referential -> 7 temporal -> 8 constraint -> 9 fiscal/capacity.
This module provides steps 1-3 primitives."""
from flask import request

from errors import (
    ApiError,
    ERR_AUTH,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
)
from util import parse_dt

ROLES = {"DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee"}


def authenticate(allowed_roles):
    """Validate X-User-ID / X-User-Role, then role membership.
    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_AUTH, 400, "missing or invalid user context headers")
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "role is not authorized for this endpoint")
    return user_id, role


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _invalid(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        _invalid(f"{name} is required and must be a string")
    return v


def opt_str(data, name):
    v = data.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        _invalid(f"{name} must be a string")
    return v


def req_int(data, name, min_v=None, max_v=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(f"{name} is required and must be an integer")
    if min_v is not None and v < min_v:
        _invalid(f"{name} must be >= {min_v}")
    if max_v is not None and v > max_v:
        _invalid(f"{name} must be <= {max_v}")
    return v


def opt_int(data, name, min_v=None, max_v=None, default=None):
    v = data.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(f"{name} must be an integer")
    if min_v is not None and v < min_v:
        _invalid(f"{name} must be >= {min_v}")
    if max_v is not None and v > max_v:
        _invalid(f"{name} must be <= {max_v}")
    return v


def req_enum(data, name, values):
    v = data.get(name)
    if not isinstance(v, str) or v not in values:
        _invalid(f"{name} must be one of {sorted(values)}")
    return v


def req_dt(data, name):
    return parse_dt(data.get(name), name)


def opt_dt(data, name):
    v = data.get(name)
    if v is None:
        return None
    return parse_dt(v, name)


def pagination_params():
    """limit (default 10, min 1, max 100), offset (default 0, min 0).
    Out-of-range values clamp to the documented bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _invalid("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _invalid("offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def sort_and_page(items, serializer):
    """Sort by created_at ascending (insertion sequence breaks ties), then
    apply limit/offset. Returns (page_json, limit, offset, total_count)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination_params()
    page = ordered[offset:offset + limit]
    return [serializer(e) for e in page], limit, offset, len(ordered)
