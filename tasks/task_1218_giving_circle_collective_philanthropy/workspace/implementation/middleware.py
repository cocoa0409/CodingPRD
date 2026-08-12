"""Auth header extraction and role checking."""

from flask import request

from errors import unauthenticated, forbidden

ROLES = {"CircleAdmin", "FinanceOfficer", "Member", "GranteeContact"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated()
    if role not in ROLES:
        raise unauthenticated("X-User-Role is not a declared role")
    return user_id, role


def require_roles(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise forbidden("Role not allowed on this endpoint")
    return user_id, role
