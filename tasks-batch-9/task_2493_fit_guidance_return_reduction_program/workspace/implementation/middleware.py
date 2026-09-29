"""Authentication / authorisation, ranks 1 and 2 of the PRD 2.9 ladder."""

from flask import request

import constants as C
from errors import ApiError


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(*allowed_roles):
    """Rank 1: headers present and role recognised.  Rank 2: role authorised."""
    user_id = request.headers.get(C.HEADER_USER_ID)
    role = request.headers.get(C.HEADER_USER_ROLE)
    if not user_id or not role or role not in C.ALL_ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be "
            "one of the five declared roles.",
        )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorized for this operation." % role,
        )
    return Actor(user_id, role)


def require_owner(condition, message="The acting user does not own the target resource."):
    """Rank 4: ownership for the two entity-backed roles."""
    if not condition:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", message)
