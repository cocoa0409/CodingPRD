"""Authentication and role authorization (PRD section 2.1)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLE_NAMES = (
    "SystemAdmin",
    "NetworkPlanner",
    "TestSupervisor",
    "FieldTechnician",
    "SafetyOfficer",
    "FaultCrewLead",
    "DispatchCoordinator",
    "AssetEngineer",
)

ALL_ROLES = list(ROLE_NAMES)


def authenticate(allowed_roles):
    """Validate X-User-ID / X-User-Role headers and endpoint role membership."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_NAMES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or unknown X-User-Role or X-User-ID header")
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not authorized for this endpoint" % role)
    return user_id, role
