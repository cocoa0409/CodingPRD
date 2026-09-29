"""Authentication (rung 1) and role authorisation (rung 2) — PRD 2.1 / 2.8."""

from flask import request

from errors import ApiError

ROLES = (
    "HarborAdmin",
    "Dispatcher",
    "VesselMaster",
    "MarineInspector",
    "Rider",
    "FareAuditor",
)

ALL_ROLES = set(ROLES)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    return Actor(str(user_id).strip(), role)


def require(*allowed_roles):
    """Rungs 1 and 2 of the rejection ladder, in order."""
    actor = authenticate()
    if actor.role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Role %s may not perform this operation." % actor.role)
    return actor
