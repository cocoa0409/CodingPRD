from flask import request
from errors import raise_error, ERR_AUTH_REQUIRED, ERR_FORBIDDEN

VALID_ROLES = {"employee", "manager", "facility_admin"}

# Role hierarchy: facility_admin > manager > employee
ROLE_LEVEL = {
    "employee": 1,
    "manager": 2,
    "facility_admin": 3,
}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if not user_id or not role:
        raise_error(ERR_AUTH_REQUIRED, "Missing X-User-ID or X-User-Role header")

    if role not in VALID_ROLES:
        raise_error(ERR_AUTH_REQUIRED, "Invalid role")

    return user_id, role


def require_roles(*allowed_roles):
    """Validate that the current user has one of the allowed roles."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, "Insufficient role for this operation")
    return user_id, role
