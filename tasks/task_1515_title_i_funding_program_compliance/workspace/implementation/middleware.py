"""Auth context (validation tier 1) and RBAC (tier 2) per PRD section 2.1."""

from flask import request

import errors

ROLES = {
    "FederalProgramsDirector",
    "ComplianceAnalyst",
    "SEAMonitor",
    "PrivateSchoolOmbudsman",
}


def current_user():
    """Return (user_id, role). Tier 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.fail(
            errors.ERR_AUTH,
            "X-User-ID and X-User-Role headers are required and the role must be recognized.",
        )
    return user_id, role


def require_role(role, allowed):
    """Tier 2: role permitted to call this endpoint."""
    if role not in allowed:
        errors.fail(
            errors.ERR_FORBIDDEN,
            "Role %s is not permitted to call this endpoint." % role,
        )
