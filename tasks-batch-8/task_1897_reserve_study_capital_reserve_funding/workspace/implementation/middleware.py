"""Auth middleware — header extraction and role checking."""

from flask import request
from errors import make_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"PlatformAdmin", "ReserveSpecialist", "BoardMember", "AssociationManager"}


def get_role():
    """Extract and validate the X-User-Role header. Returns role string or raises."""
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise make_error(ERR_UNAUTHENTICATED, "X-User-Role header missing or not a declared role")
    return role


def require_roles(*allowed_roles):
    """Check that the caller's role is in allowed_roles. Returns the role."""
    role = get_role()
    if role not in allowed_roles:
        raise make_error(ERR_FORBIDDEN, f"Role {role} not permitted for this endpoint")
    return role


ANY_ROLE = ("PlatformAdmin", "ReserveSpecialist", "BoardMember", "AssociationManager")
