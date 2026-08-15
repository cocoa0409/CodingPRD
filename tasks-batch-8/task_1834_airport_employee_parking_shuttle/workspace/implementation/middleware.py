"""Auth header extraction and role checking."""
from flask import request

from errors import raise_error

ROLES = {
    "ParkingAdmin",
    "Employee",
    "PayrollAdmin",
    "EnforcementOfficer",
    "AppealsOfficer",
    "ShuttleDispatcher",
}


def get_auth():
    """Validate auth context headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(
            "ERR_MISSING_OR_INVALID_AUTH_CONTEXT",
            "X-User-ID and X-User-Role headers are required and role must be a declared role",
        )
    return user_id, role


def require_roles(*roles):
    user_id, role = get_auth()
    if role not in roles:
        raise_error("ERR_FORBIDDEN_ROLE", "Role not allowed on this endpoint")
    return user_id, role
