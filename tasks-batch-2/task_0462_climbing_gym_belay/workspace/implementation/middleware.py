"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.9)."""
from flask import request

from errors import err

VALID_ROLES = {"Member", "FrontDesk", "Examiner", "RouteSetter", "GymAdmin"}


def get_caller():
    """Return (user_id, role) after asserting both headers present and role known.

    Raises ERR_UNAUTHENTICATED when either header is missing/blank or the role
    is not one of the five recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown X-User-Role")
    return user_id, role


def require_role(role, allowed):
    """Assert the caller role is in the allowed set, else ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)
