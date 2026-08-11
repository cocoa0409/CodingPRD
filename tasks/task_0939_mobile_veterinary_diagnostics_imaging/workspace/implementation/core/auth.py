"""Ladder rungs 1 and 2 — authentication and role authorization (PRD 2.1 / 2.8)."""

from flask import g, request

from .constants import ALL_ROLES
from .errors import ApiError


def authenticate():
    """Rung 1: both headers present, role is one of the six declared names."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*roles):
    """Rung 2: the acting role appears in the endpoint's authorized-role list."""
    if g.role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def require_owner(condition):
    """Rung 3 helper: `condition` is the ownership predicate for this endpoint."""
    if not condition:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


READ_ROLES = tuple(ALL_ROLES)
