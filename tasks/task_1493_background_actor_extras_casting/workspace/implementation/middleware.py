"""Auth context extraction (PRD section 2.1) and body/field validation helpers."""
from flask import request

from errors import (
    ApiError,
    ERR_AUTH,
    ERR_FORBIDDEN_ROLE,
    ERR_VALIDATION,
)

ROLES = {
    "AgencyAdmin",
    "CastingDirector",
    "CastingAssociate",
    "BackgroundActor",
    "PayrollCoordinator",
    "UnionRepresentative",
}

ALL_ROLES = [
    "AgencyAdmin",
    "CastingDirector",
    "CastingAssociate",
    "BackgroundActor",
    "PayrollCoordinator",
    "UnionRepresentative",
]


def auth(allowed_roles):
    """Validate X-User-ID / X-User-Role headers and endpoint role authorization.

    Returns (user_id, role). Priority 1: header presence and known role name.
    Priority 2: caller role must appear in the endpoint's roles list.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_AUTH,
            400,
            "X-User-ID and X-User-Role headers are required and the role must be recognized",
        )
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Caller role is not authorized for this operation")
    return user_id, role


def body():
    """JSON request body as a dict; absent/non-object bodies become {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' is required and must be a string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a string")
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be >= {minimum}")
    return v


def opt_int(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be an integer")
    return v


def req_enum(data, field, members):
    v = data.get(field)
    if not isinstance(v, str) or v not in members:
        raise ApiError(
            ERR_VALIDATION,
            400,
            f"Field '{field}' must be one of {sorted(members)}",
        )
    return v


def opt_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a boolean")
    return v
