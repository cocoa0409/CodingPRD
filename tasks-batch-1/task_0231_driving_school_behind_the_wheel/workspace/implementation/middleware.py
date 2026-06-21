"""Auth header extraction and RBAC."""
from flask import request

from errors import err

VALID_ROLES = {"SchoolAdmin", "Instructor", "Student", "Guardian"}


def get_auth():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED when either header is missing/empty or role is
    unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown role.")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint.")
