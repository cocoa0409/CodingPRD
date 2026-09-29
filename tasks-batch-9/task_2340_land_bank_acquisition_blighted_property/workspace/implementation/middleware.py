"""Auth header extraction and RBAC (PRD 2.1)."""
from flask import request

from errors import ApiError

ROLES = (
    "IntakeOfficer",
    "BoardClerk",
    "DispositionOfficer",
    "InventoryManager",
    "CountyTreasurer",
    "Applicant",
)

STAFF_ROLES = (
    "IntakeOfficer",
    "BoardClerk",
    "DispositionOfficer",
    "InventoryManager",
    "CountyTreasurer",
)


def authenticate(*allowed_roles):
    """Validate the X-User-ID / X-User-Role headers and the endpoint's RBAC."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be recognized.",
        )
    if allowed_roles and role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not authorized for this operation." % role,
        )
    return user_id, role
