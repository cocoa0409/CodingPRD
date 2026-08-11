"""Authentication and role authorisation (PRD 2.1, ladder rungs 1-4)."""

from flask import g, request

from .constants import ROLE_NAMES
from .errors import ApiError


def authenticate():
    """Rungs 1 and 2.  An unknown role is treated as no credential at all."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    user_id = str(user_id).strip()
    if role not in ROLE_NAMES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role names an unknown role.")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed_roles):
    """Rungs 1-3 in one call; returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s may not perform this operation." % role,
        )
    return user_id, role


def subscriber_owns(user_id, role, subscription_id):
    """Rung 4: a Subscriber may only act on its own subscription."""
    if role == "Subscriber" and user_id != subscription_id:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "A Subscriber may only act on their own subscription.",
        )
