"""Auth header extraction and role checking (PRD §2.1)."""

from flask import request

from errors import raise_error

ROLES = {
    "FarmManager",
    "Grower",
    "SanitationLead",
    "QualityAssurance",
    "ContractsManager",
    "LaborPlanner",
    "Worker",
}

ALL_ROLES = sorted(ROLES)


def auth_context():
    """Return (user_id, role). Raises ERR_MISSING_CONTEXT_HEADER / ERR_FORBIDDEN_ROLE."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error("ERR_MISSING_CONTEXT_HEADER")
    return user_id, role


def require_roles(*roles):
    user_id, role = auth_context()
    if role not in roles:
        raise_error("ERR_FORBIDDEN_ROLE")
    return user_id, role
