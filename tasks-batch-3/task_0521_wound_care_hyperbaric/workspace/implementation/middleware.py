"""Auth header extraction and RBAC checking (PRD §2.1)."""
from flask import request

from errors import err

VALID_ROLES = {
    "IntakeCoordinator",
    "WoundClinician",
    "HyperbaricTech",
    "PayerLiaison",
    "AttendingPhysician",
}


def get_user_context():
    """Priority 1: header presence and validity."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers must be present and valid")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: RBAC. `allowed` is a set/list of role names."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s is not permitted for this operation" % role)
