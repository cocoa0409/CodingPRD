"""Auth middleware and validation helpers.

Headers: X-User-ID, X-User-Role. Roles: PlatformAdmin, CaseManager,
OperationsSpecialist, ComplianceOfficer, JudicialRecorder, Payee, Any.
"""

from flask import request
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
)
from db import parse_date

DECLARED_ROLES = {
    "PlatformAdmin",
    "CaseManager",
    "OperationsSpecialist",
    "ComplianceOfficer",
    "JudicialRecorder",
    "Payee",
    "Any",
}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    """Priority 1: header presence and role validity."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and X-User-Role must be a declared role",
            400,
        )
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """Priority 2: role authorization for the endpoint.

    `allowed` is a set of role names. "Any" in allowed means any authenticated
    caller. A caller with role "Any" may only access endpoints that allow "Any".
    """
    if "Any" in allowed:
        return
    if caller.role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "Role not authorized for this endpoint",
            403,
        )


# ---------------------------------------------------------------------------
# Input shape helpers (priority 20 — run last)
# ---------------------------------------------------------------------------

def get_json_body():
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


def check_unknown_fields(body, allowed_fields):
    for k in body.keys():
        if k not in allowed_fields:
            raise ApiError(ERR_INVALID_REQUEST, f"Unknown payload field: {k}", 400)


def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {name}", 400)
    return body[name]


def opt_field(body, name, default=None):
    v = body.get(name, default)
    return v


def as_string(v, name):
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string", 400)
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be an integer", 400)
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a boolean", 400)
    return v


def as_positive_int(v, name):
    v = as_int(v, name)
    if v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be > 0", 400)
    return v


def as_nonnegative_int(v, name):
    v = as_int(v, name)
    if v < 0:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be >= 0", 400)
    return v


def as_date(v, name):
    as_string(v, name)
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a YYYY-MM-DD date", 400)


def as_enum(v, name, allowed):
    as_string(v, name)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}", 400)
    return v


def as_year_month(v, name):
    as_string(v, name)
    parts = v.split("-")
    ok = (
        len(parts) == 2
        and len(parts[0]) == 4
        and len(parts[1]) == 2
        and parts[0].isdigit()
        and parts[1].isdigit()
        and 1 <= int(parts[1]) <= 12
    )
    if not ok:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a YYYY-MM label", 400)
    return v


def as_iso8601(v, name):
    from datetime import datetime, timezone
    as_string(v, name)
    s = v
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 timestamp", 400)


def parse_pagination(args):
    """limit default 10, min 1, max 100; offset default 0."""
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset
