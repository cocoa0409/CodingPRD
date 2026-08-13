"""Auth header extraction and role checking (scaffold §1.4 priorities 1-2, PRD §2.1)."""

from flask import request
from errors import raise_err

ROLES = {"ProgramCoordinator", "Volunteer", "Specialist"}


def auth_context(allowed_roles):
    """Validate X-User-ID / X-User-Role and role authorization.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers required and role must be a declared role")
    if role not in allowed_roles:
        raise_err("ERR_FORBIDDEN", "The caller's role is not authorized for this endpoint")
    return user_id, role
