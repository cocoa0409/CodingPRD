"""Auth header extraction and role checking."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ROLES = {"GroupAdmin", "Hospitalist", "ConsultingSpecialist"}


def get_auth():
    """Extract and validate X-User-Role and X-User-ID headers.

    Returns (role, user_id). Raises ApiError(401) when missing/invalid.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or malformed X-User-Role / X-User-ID headers",
            401,
        )
    return role, user_id


def require_roles(allowed):
    """Return (role, user_id) or raise 401/403."""
    role, user_id = get_auth()
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            "Role not permitted for the endpoint",
            403,
        )
    return role, user_id
