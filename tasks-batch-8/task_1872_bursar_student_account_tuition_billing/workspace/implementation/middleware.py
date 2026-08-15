"""Auth context and role/ownership enforcement per PRD section 2.1."""
from flask import request

from errors import err, ERR_MISSING_OR_INVALID_USER_CONTEXT, ERR_FORBIDDEN

ROLES = {"Student", "RegistrarStaff", "BursarStaff", "BursarManager"}


def auth_context():
    """Priority 1: X-User-ID and X-User-Role present; role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT,
                  "X-User-ID and X-User-Role headers are required and the role must be a declared role name")
    return uid, role


def require_roles(role, *allowed):
    """Priority 2: role is permitted on this endpoint."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role is not permitted on this endpoint")


def forbid():
    raise err(ERR_FORBIDDEN, "Entity-backed ownership check failed")
