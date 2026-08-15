"""Auth middleware per PRD §2.1: X-User-ID + X-User-Role headers."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"StationAdmin", "MembershipCoordinator", "PhoneVolunteer"}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED[0],
            "Missing or unrecognized X-User-Role / X-User-ID headers",
            ERR_UNAUTHENTICATED[1],
        )
    return user_id, role


def require_roles(*allowed):
    """Validate auth and role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED[0],
            f"Role {role} not permitted for this endpoint",
            ERR_UNAUTHORIZED[1],
        )
    return user_id, role
