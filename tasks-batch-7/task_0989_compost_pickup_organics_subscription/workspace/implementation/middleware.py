"""Auth header extraction and role gating (PRD 2.1, validations 1-2)."""

from flask import request

from errors import ApiError, ERR_FORBIDDEN_ROLE, ERR_UNAUTHENTICATED, forbidden

ROLES = {"Anonymous", "Subscriber", "Driver", "OperationsManager"}


def auth():
    """Return (user_id, role); both headers required and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(role, *allowed):
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "Role %s is not allowed on this endpoint" % role)


def own_or_403(owner_subscriber_id, user_id):
    if owner_subscriber_id != user_id:
        forbidden("Subscriber caller does not own the target resource")
