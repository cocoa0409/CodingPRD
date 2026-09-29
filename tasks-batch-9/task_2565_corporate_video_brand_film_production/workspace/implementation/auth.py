"""Authentication, role authorization and crew read scoping (PRD 2.1, 2.12)."""

from flask import request

from errors import ApiError

ROLES = (
    "ProductionCoordinator",
    "LineProducer",
    "PostSupervisor",
    "ClientApprover",
    "ComplianceOfficer",
    "CrewMember",
)

ALL_PRODUCTION_ROLES = (
    "ProductionCoordinator",
    "LineProducer",
    "PostSupervisor",
    "ClientApprover",
    "ComplianceOfficer",
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Priority 1 then priority 2 of the precedence order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or not str(role).strip() or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing, empty or unknown.")
    if role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not authorized for this endpoint." % role,
        )
    return Caller(str(user_id), role)
