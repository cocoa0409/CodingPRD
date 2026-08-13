"""Auth header extraction and role checking."""

from flask import request
from errors import missing_context, unauthorized_role, ApiError
import errors

VALID_ROLES = {"ClientAgent", "Photographer", "Coordinator", "OpsAdmin"}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ApiError on missing/invalid.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise missing_context()
    if role not in VALID_ROLES:
        raise missing_context()
    return user_id, role


def require_roles(*roles):
    """Validate headers then enforce role membership."""
    user_id, role = get_auth()
    if role not in roles:
        raise unauthorized_role()
    return user_id, role
