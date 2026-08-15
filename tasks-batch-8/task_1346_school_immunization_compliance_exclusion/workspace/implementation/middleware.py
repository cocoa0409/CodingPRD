"""Auth header extraction and role checking per PRD §2.1."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"HealthClerk", "SchoolNurse", "DistrictHealthOfficer", "RegistryCoordinator"}
ALL_ROLES = ["HealthClerk", "SchoolNurse", "DistrictHealthOfficer", "RegistryCoordinator"]


def current_user():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or invalid X-User-ID / X-User-Role headers.",
            401,
        )
    return user_id, role


def require_roles(*roles):
    """Authenticate and authorize; returns (user_id, role)."""
    user_id, role = current_user()
    if role not in roles:
        raise ApiError(
            ERR_FORBIDDEN,
            "Caller role is not authorized for this endpoint.",
            403,
        )
    return user_id, role
