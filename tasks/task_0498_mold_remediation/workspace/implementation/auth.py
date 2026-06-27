"""Auth header extraction and RBAC (PRD §2.1, §1.7)."""
from flask import request
from errors import err

ROLES = {"ProjectManager", "AbatementSupervisor", "LabTech", "Hygienist", "ComplianceOfficer"}


def authenticate():
    """Validate auth headers in priority order: presence then recognized role.
    Returns (user_id, role). Raises ApiError on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_MISSING_AUTH_HEADER", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise err("ERR_INVALID_ROLE", "X-User-Role is not a recognized role")
    return user_id, role


def require_role(role, allowed):
    """allowed is a set/list of role names. Raises ERR_FORBIDDEN_ROLE if not allowed."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation" % role)
