"""Auth header extraction + RBAC. Headers and role names per PRD §2.1.

Auth headers: X-User-ID, X-User-Role.
Recognized roles (exactly five): ProgramAdmin, IntakeCoordinator, MedicalDirector,
NurseStaff, BillingSpecialist.
"""
from functools import wraps

from flask import request

from errors import err

ROLES = {
    "ProgramAdmin",
    "IntakeCoordinator",
    "MedicalDirector",
    "NurseStaff",
    "BillingSpecialist",
}


def authenticate():
    """PRD §2.1: both headers must be present and X-User-Role must be a known
    role, else ERR_UNAUTHENTICATED (401). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers")
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce that the role is permitted for this
    operation (PRD §2.1 / §4 RBAC). ERR_UNAUTHORIZED (403) on mismatch.

    The authentication and authorization checks run before any path-id existence
    check, matching the fixed validation precedence in PRD §2.5."""
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed_set:
                raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
