"""Auth middleware: X-User-ID / X-User-Role extraction and role enforcement (PRD §2.1)."""
from flask import request

from errors import ApiError

ROLES = {
    "PlatformAdmin",
    "InfectionPreventionist",
    "InfectionControlDirector",
    "UnitNurseManager",
    "EmployeeHealthNurse",
}

ALL_ROLES = sorted(ROLES)


def current_user():
    uid = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not uid or not uid.strip() or not role or not role.strip():
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return uid.strip(), role.strip()


def require_roles(allowed):
    """Validate identity headers then role membership. Returns (user_id, role)."""
    uid, role = current_user()
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            403,
            f"Role {role} is not authorized for this endpoint",
        )
    return uid, role
