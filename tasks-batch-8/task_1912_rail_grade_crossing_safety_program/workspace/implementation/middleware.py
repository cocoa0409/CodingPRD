"""Auth header extraction and role checking (SCAFFOLD 1.4 p1/p2, PRD §2.1)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")


def auth(allowed_roles):
    """Validate X-User-ID / X-User-Role headers and endpoint role admission.

    Returns (user_id, role). Priority 1: unauthenticated; priority 2: role not
    on the endpoint's admitted list.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "X-User-ID and X-User-Role headers are required and must name a declared role",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"Role {role} is not authorized for this operation",
        )
    return user_id, role
