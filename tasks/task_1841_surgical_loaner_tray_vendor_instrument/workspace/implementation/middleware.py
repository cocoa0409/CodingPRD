"""Auth header extraction, body validation helpers, and role checking.

Header scheme (PRD §2.1): X-User-ID and X-User-Role, both mandatory and
non-empty on every request. Roles are the five operational roles.
"""

from flask import request

from errors import ApiError, ERROR_CATALOG

ALL_ROLES = {
    "VendorCoordinator",
    "ORScheduler",
    "SterileProcessingTech",
    "ORCirculatorNurse",
    "VendorRep",
}


def get_auth():
    """Validate the two auth headers (validation tier 1) and return
    (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not str(user_id).strip()
        or role is None
        or not str(role).strip()
    ):
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            ERROR_CATALOG["ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"],
            "X-User-ID and X-User-Role headers are required and must be non-empty",
        )
    return user_id.strip(), role.strip()


def require_role(role: str, allowed):
    """Validation tier 3: role authorization."""
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            ERROR_CATALOG["ERR_FORBIDDEN_ROLE"],
            f"Role {role} is not authorized for this operation",
        )


def get_body(required: bool = False):
    """Parse the JSON request body. Returns {} for empty bodies unless
    required=True. Raises ERR_VALIDATION on unparseable JSON."""
    if request.data is None or request.data == b"":
        if required:
            raise ApiError(
                "ERR_VALIDATION", ERROR_CATALOG["ERR_VALIDATION"], "Request body is required"
            )
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(
            "ERR_VALIDATION", ERROR_CATALOG["ERR_VALIDATION"], "Request body must be valid JSON"
        )
    if data is None:
        if required:
            raise ApiError(
                "ERR_VALIDATION", ERROR_CATALOG["ERR_VALIDATION"], "Request body is required"
            )
        return {}
    if not isinstance(data, dict):
        raise ApiError(
            "ERR_VALIDATION", ERROR_CATALOG["ERR_VALIDATION"], "Request body must be a JSON object"
        )
    return data


def req_str(body, field):
    """Required string field."""
    val = body.get(field)
    if val is None or not isinstance(val, str) or not val.strip():
        raise ApiError(
            "ERR_VALIDATION",
            ERROR_CATALOG["ERR_VALIDATION"],
            f"Field '{field}' is required and must be a non-empty string",
        )
    return val


def req_int(body, field, min_value=None):
    """Required integer field (bool is not accepted as int)."""
    val = body.get(field)
    if val is None or isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(
            "ERR_VALIDATION",
            ERROR_CATALOG["ERR_VALIDATION"],
            f"Field '{field}' is required and must be an integer",
        )
    if min_value is not None and val < min_value:
        raise ApiError(
            "ERR_VALIDATION",
            ERROR_CATALOG["ERR_VALIDATION"],
            f"Field '{field}' must be >= {min_value}",
        )
    return val


def opt_int(body, field, default=None, min_value=None):
    val = body.get(field)
    if val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(
            "ERR_VALIDATION",
            ERROR_CATALOG["ERR_VALIDATION"],
            f"Field '{field}' must be an integer",
        )
    if min_value is not None and val < min_value:
        raise ApiError(
            "ERR_VALIDATION",
            ERROR_CATALOG["ERR_VALIDATION"],
            f"Field '{field}' must be >= {min_value}",
        )
    return val


def opt_bool(body, field, default=False):
    val = body.get(field)
    if val is None:
        return default
    if not isinstance(val, bool):
        raise ApiError(
            "ERR_VALIDATION",
            ERROR_CATALOG["ERR_VALIDATION"],
            f"Field '{field}' must be a boolean",
        )
    return val


def req_enum(body, field, allowed):
    val = body.get(field)
    if val is None or not isinstance(val, str) or val not in allowed:
        raise ApiError(
            "ERR_VALIDATION",
            ERROR_CATALOG["ERR_VALIDATION"],
            f"Field '{field}' must be one of {sorted(allowed)}",
        )
    return val
