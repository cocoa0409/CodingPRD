"""Auth header extraction and role authorisation."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


VALID_ROLES = {
    "PlatformAdmin",
    "Recruiter",
    "HiringManager",
    "CompApprover",
    "VP",
    "ComplianceOfficer",
    "PayrollOfficer",
    "Candidate",
}


def require_auth():
    """Return (user_id, user_role) or raise ERR_UNAUTHENTICATED."""
    uid = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not uid or not role:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "missing auth headers")
    return uid, role


def require_role(allowed_roles):
    """Authenticate and assert role membership. Returns (user_id, role)."""
    uid, role = require_auth()
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403, f"role {role} not permitted")
    return uid, role
