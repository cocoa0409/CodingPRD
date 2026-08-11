"""G1_AUTH (rungs 1-2) and G2_ROLE (rungs 3-5)."""

from flask import request

from constants import ROLES
from errors import ApiError

ENTITY_BACKED_ROLE = "Member"


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_member(self):
        return self.role == ENTITY_BACKED_ROLE


def gate(*allowed_roles):
    """Rungs 1, 2 and 3, evaluated in that order before anything else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    # rung 1
    if user_id is None or role is None or str(user_id).strip() == "" or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    # rung 2
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    # rung 3
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_FORBIDDEN")
    return Caller(user_id, role)


def own(caller, member_id):
    """Rung 4: for an entity-backed role the acting id must own the resource."""
    if caller.is_member and caller.user_id != member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
