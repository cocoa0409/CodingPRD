"""Auth header extraction and role checks (PRD 2.1)."""

from flask import request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "MillPlanner",
    "ExtrusionOperator",
    "DyeHouseOperator",
    "QALabTechnician",
    "CertificationOfficer",
    "DealerBuyer",
    "PlantAdmin",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Rung 1 (authentication) then rung 2 (role authorisation)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is not a recognised role")
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s may not perform this operation" % role,
        )
    return Actor(str(user_id), role)
