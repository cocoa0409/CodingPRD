"""Auth header extraction, role checks, structural payload validation, pagination."""

from flask import request

from errors import (
    err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_VALIDATION,
)
from util import parse_dt

ROLES = {
    "ProductionExecutive",
    "StuntCoordinator",
    "SafetyOfficer",
    "DepartmentHead",
    "Performer",
    "EquipmentInspector",
}

ALL_ROLES = sorted(ROLES)


def auth():
    """Validate X-User-ID / X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be "
            "one of the six declared roles",
            400,
        )
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(
            ERR_FORBIDDEN_ROLE,
            f"Role {role} is not authorized for this endpoint",
            403,
        )


# ---------------------------------------------------------------------------
# Structural payload validation (PRD 2.7 tier 0): missing required field,
# unknown field (incl. client-supplied computed/system fields), invalid enum,
# non-positive amount -> ERR_VALIDATION (400).
# ---------------------------------------------------------------------------


def get_body():
    """Return the JSON request body as a dict; empty body is {}."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err(ERR_VALIDATION, "Request body must be valid JSON", 400)
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object", 400)
    return data


# --- field validators: fn(value, field_name) -> parsed value -----------------


def v_string(value, field):
    if not isinstance(value, str):
        raise err(ERR_VALIDATION, f"Field '{field}' must be a string", 400)
    return value


def v_nonempty_string(value, field):
    if not isinstance(value, str) or len(value) == 0:
        raise err(ERR_VALIDATION, f"Field '{field}' must be a non-empty string", 400)
    return value


def v_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_VALIDATION, f"Field '{field}' must be an integer", 400)
    return value


def v_pos_int(value, field):
    v = v_int(value, field)
    if v <= 0:
        raise err(ERR_VALIDATION, f"Field '{field}' must be a positive integer", 400)
    return v


def v_nonneg_int(value, field):
    v = v_int(value, field)
    if v < 0:
        raise err(ERR_VALIDATION, f"Field '{field}' must be a non-negative integer", 400)
    return v


def v_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_VALIDATION, f"Field '{field}' must be a number", 400)
    return value


def v_bool(value, field):
    if not isinstance(value, bool):
        raise err(ERR_VALIDATION, f"Field '{field}' must be a boolean", 400)
    return value


def v_enum(choices):
    def check(value, field):
        if not isinstance(value, str) or value not in choices:
            raise err(
                ERR_VALIDATION,
                f"Field '{field}' must be one of {sorted(choices)}",
                400,
            )
        return value

    return check


def v_datetime(value, field):
    return parse_dt(value, field)


def v_id_list(value, field):
    if not isinstance(value, list):
        raise err(ERR_VALIDATION, f"Field '{field}' must be an array of ids", 400)
    for el in value:
        if not isinstance(el, str):
            raise err(ERR_VALIDATION, f"Field '{field}' must be an array of ids", 400)
    return list(value)


def v_rating(value, field):
    v = v_int(value, field)
    if v < 1 or v > 5:
        raise err(ERR_VALIDATION, f"Field '{field}' must be an integer in 1..5", 400)
    return v


def v_take_number(value, field):
    v = v_int(value, field)
    if v < 1:
        raise err(ERR_VALIDATION, f"Field '{field}' must be at least 1", 400)
    return v


def v_nullable_id(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise err(ERR_VALIDATION, f"Field '{field}' must be a string id or null", 400)
    return value


# spec entry: field_name -> (validator, required, default)
def validate_payload(body, spec):
    for key in body:
        if key not in spec:
            raise err(ERR_VALIDATION, f"Unknown field in request payload: '{key}'", 400)
    out = {}
    for name, (fn, required, default) in spec.items():
        if name in body and body[name] is not None:
            out[name] = fn(body[name], name)
        elif name in body and body[name] is None and not required:
            out[name] = default
        elif required:
            raise err(ERR_VALIDATION, f"Missing required field: '{name}'", 400)
        else:
            out[name] = default
    return out


def pagination_params():
    """limit (default 10, clamped to 1..100), offset (default 0, min 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "Query parameter 'limit' must be an integer", 400)
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "Query parameter 'offset' must be an integer", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
