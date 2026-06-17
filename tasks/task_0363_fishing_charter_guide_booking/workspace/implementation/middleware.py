"""Auth header extraction and role checking (PRD 2.1, 2.9 priorities 1-2)."""
from flask import request

from errors import ApiError

VALID_ROLES = {"DockMaster", "FleetManager", "Captain", "Customer"}


def get_user_context():
    """Validate X-User-ID and X-User-Role headers (priority 1).

    Both must be present and well-formed; role must be one of the four
    recognized roles. Otherwise ERR_MISSING_USER_CONTEXT.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-ID header")
    if not role or not role.strip():
        raise ApiError("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-Role header")
    if role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT", "Unrecognized X-User-Role value")
    return user_id, role


def require_role(allowed_roles):
    """Validate context, then enforce RBAC (priority 2)."""
    user_id, role = get_user_context()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
    return user_id, role
