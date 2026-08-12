"""Auth middleware: header extraction, role validation, RBAC enforcement."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLES = {
    "SchedulingAdmin",
    "Surgeon",
    "CirculatorNurse",
    "AnesthesiaCoordinator",
    "CommitteeMember",
    "BlockCommitteeChair",
}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_auth():
    """Validate X-User-ID / X-User-Role headers (validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID header is missing",
        )
    if not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role header is missing or not a declared role",
        )
    return AuthContext(user_id, role)


def require_roles(*roles):
    """Role authorization (validation priority 2)."""
    auth = get_auth()
    if auth.role not in roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            f"Role {auth.role} may not perform this operation",
        )
    return auth


def get_json_body():
    """Parse the JSON request body; malformed JSON is a shape error."""
    from errors import ERR_INVALID_REQUEST

    if request.data is None or request.data == b"":
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body
