"""Auth context extraction, role checks, shape validation, pagination."""
from flask import request

from errors import (
    ApiError, ERR_AUTH, ERR_FORBIDDEN, ERR_INVALID,
)

ROLES = {
    "HRAdmin",
    "HiringManager",
    "Candidate",
    "VendorAgent",
    "Adjudicator",
    "ComplianceOfficer",
    "Auditor",
}

ALL_ROLES = frozenset(ROLES)


def auth():
    """Priority 1: X-User-ID and X-User-Role present, role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_AUTH, 400,
                       "X-User-ID or X-User-Role header missing or role unrecognized")
    return uid, role


def require_role(role, allowed):
    """Priority 2: role permitted for this endpoint."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")


def forbid(message="Ownership check failed"):
    raise ApiError(ERR_FORBIDDEN, 403, message)


def invalid(message="Invalid request"):
    raise ApiError(ERR_INVALID, 400, message)


def get_body():
    """JSON object body; malformed/missing JSON behaves as empty object."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object")
    return data


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        invalid("Missing or invalid field: %s" % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        invalid("Invalid field: %s" % field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        invalid("Missing or invalid field: %s" % field)
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        invalid("Missing or invalid field: %s" % field)
    if minimum is not None and v < minimum:
        invalid("Field %s must be >= %s" % (field, minimum))
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        invalid("Missing or invalid field: %s" % field)
    return v


def opt_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        invalid("Invalid field: %s" % field)
    return v


def opt_int(body, field, minimum=None):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        invalid("Invalid field: %s" % field)
    if minimum is not None and v < minimum:
        invalid("Field %s must be >= %s" % (field, minimum))
    return v


def opt_bool(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        invalid("Invalid field: %s" % field)
    return v


def parse_pagination():
    """limit default 10 (min 1, max 100); offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def sort_key(ent):
    """created_at ascending; _seq preserves insertion order for ties."""
    return (ent["created_at"], ent["_seq"])
