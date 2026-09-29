"""Authentication and role checks (PRD §2.1, precedence rules 1 and 2)."""

from flask import request

from errors import ApiError

ROLES = ("PlatformAdmin", "HotelManagerOps", "AssetManager", "OwnerRep")
ALL_ROLES = list(ROLES)
READ_ROLES = list(ROLES)


def authenticate(allowed_roles):
    """Rule 1 then rule 2.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role
