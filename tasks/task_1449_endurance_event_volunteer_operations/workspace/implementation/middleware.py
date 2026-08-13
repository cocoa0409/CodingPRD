"""Auth context extraction and role checking."""
from flask import request

import errors

ROLES = {"Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector"}


def get_context():
    """Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.missing_or_invalid_user_context()
    return user_id, role


def require_roles(*allowed):
    """Validates context headers then role admission."""
    user_id, role = get_context()
    if role not in allowed:
        raise errors.forbidden_role()
    return user_id, role
