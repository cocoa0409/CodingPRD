"""Auth header extraction and role checking per PRD §2.1."""

from flask import request
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"LocationManager", "FilmOffice", "OwnerRep"}


def get_auth():
    """Extract and validate X-User-ID and X-User-Role headers.
    Returns (user_id, role) or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role header", 401)
    if not user_id:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing X-User-ID header", 401)
    return user_id, role


def require_role(*allowed_roles: str):
    """Check that the caller's role is in allowed_roles. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, f"Role {role} not permitted for this endpoint", 403)
    return user_id, role


ALL_ROLES = ("LocationManager", "FilmOffice", "OwnerRep")
