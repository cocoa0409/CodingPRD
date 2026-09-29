"""Authentication and role authorisation (PRD section 2.1)."""

from flask import request

from constants import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE
from errors import ApiError


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role %r is not a recognised role." % role)
    return Actor(user_id, role)


def require(*roles):
    """Priority 1 then priority 2: authenticate, then authorise the endpoint."""
    actor = authenticate()
    if actor.role not in roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorised for this endpoint." % actor.role,
        )
    return actor
