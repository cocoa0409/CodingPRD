"""Authentication and role authorization (PRD §2.1, precedence ordinals 1-2)."""

from flask import request

from errors import api_error

ROLES = (
    "CatastropheDirector",
    "PermitOfficer",
    "CrewCoordinator",
    "IntakeAdvisor",
    "ShopEstimator",
    "PdrTechnician",
    "QualityInspector",
    "InsurerAdjuster",
    "BillingCoordinator",
)


class Principal:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Ordinal 1 then ordinal 2. Returns the acting Principal."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "" or role not in ROLES:
        raise api_error(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
        )
    if role not in allowed_roles:
        raise api_error(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not authorized for this endpoint." % role,
        )
    return Principal(user_id, role)
