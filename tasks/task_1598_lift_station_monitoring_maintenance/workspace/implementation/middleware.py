"""Auth header extraction and role checking (PRD sections 2.1, 2.8).

Identity headers: X-User-ID and X-User-Role. Role check (priority 1) runs
before the id check (priority 2); role authorization is priority 3.
Called directly at the top of each view: require_roles("UtilityAdmin", ...).
"""
from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED
from helpers import ROLES


def require_roles(*allowed):
    """Validate identity headers, then enforce role membership."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "X-User-Role header is missing or does not name a declared role",
        )
    uid = request.headers.get("X-User-ID")
    if uid is None or not isinstance(uid, str) or not uid.strip():
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "X-User-ID header is missing or empty",
        )
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED, 403,
            "Role %s is not authorized for this endpoint" % role,
        )
    g.user_id = uid
    g.user_role = role
    return uid
