"""Auth middleware: X-User-ID / X-User-Role extraction and role checking."""
from flask import request
from errors import raise_err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_UNAUTHORIZED_ROLE

DECLARED_ROLES = {
    "BandDirector",
    "AssistantDirector",
    "BoosterTreasurer",
    "EquipmentManager",
    "SectionLeader",
    "Student",
}


def get_actor():
    """Extract (user_id, role) from headers. Raise 400 if missing/invalid."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers are required")
    if role not in DECLARED_ROLES:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-Role is not a declared role")
    return uid, role


def require_roles(allowed):
    """allowed: list of role names; 'Any' means any declared role."""
    uid, role = get_actor()
    if "Any" in allowed:
        return uid, role
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED_ROLE, f"Role {role} is not permitted for this endpoint")
    return uid, role
