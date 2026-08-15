"""Auth context extraction and role checks (PRD §2.1, validations priority 1-2)."""
from flask import request

from errors import ERR_AUTH, ERR_FORBIDDEN, ApiError

DECLARED_ROLES = {
    "DistrictStaffingAdmin",
    "SpecialEdCoordinator",
    "BuildingAdministrator",
    "Teacher",
    "Paraprofessional",
    "Any",
}


def auth_context():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_AUTH, 400,
            "X-User-ID and X-User-Role headers are required and role must be declared",
        )
    return user_id, role


def require_role(role, allowed):
    """allowed is a collection of role names; 'Any' admits every authenticated caller."""
    if "Any" in allowed:
        return
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "role %s is not permitted for this endpoint" % role)
