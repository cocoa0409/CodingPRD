"""Auth header extraction, role checking, list helpers, and shape validation."""
from flask import request

from db import serialize
from errors import ApiError

ROLES = {
    "EmployeeHealthNurse",
    "EmployeeHealthPhysician",
    "ComplianceOfficer",
    "SafetyOfficer",
    "StaffEmployee",
}

READ_ROLES = ROLES  # all five roles may read (subject to StaffEmployee self-scope)


def auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_AUTH_CONTEXT",
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Acting role is not permitted for this endpoint")


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def get_required(data, field):
    value = data.get(field)
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return value


def check_enum(value, members, field):
    if not isinstance(value, str) or value not in members:
        raise ApiError(
            "ERR_INVALID_ENUM", "Field %s must be one of %s" % (field, sorted(members))
        )
    return value


def check_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return value


def check_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return value


def paginate(items):
    """limit/offset pagination per PRD 2.3 (default 10, min 1, max 100, offset 0)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = min(100, max(1, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


def sorted_entities(entities):
    """Every list endpoint returns resources sorted by created_at ascending;
    internal insertion order breaks ties deterministically."""
    return sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))


def list_response(items, filters, scope_fn=None):
    """Apply equality filters (query params), optional self-scope, sort, serialize."""
    out = []
    for ent in sorted_entities(items):
        if scope_fn is not None and not scope_fn(ent):
            continue
        ok = True
        for param, getter in filters.items():
            raw = request.args.get(param)
            if raw is None:
                continue
            if getter(ent) != raw:
                ok = False
                break
        if ok:
            out.append(ent)
    page, meta = paginate(out)
    return [serialize(e) for e in page], meta
