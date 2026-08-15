"""Auth header extraction and role checking."""

from flask import request
import errors

VALID_ROLES = {"ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member"}


def get_auth():
    """Extract and validate X-User-ID and X-User-Role headers.

    Returns (user_id, role) or raises ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated(f"Undeclared role: {role}")
    return user_id, role


def require_roles(*allowed_roles):
    """Check that the caller has one of the allowed roles.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED then ERR_UNAUTHORIZED.
    """
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise errors.unauthorized()
    return user_id, role
