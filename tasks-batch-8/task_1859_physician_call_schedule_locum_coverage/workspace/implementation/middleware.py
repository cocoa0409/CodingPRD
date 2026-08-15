"""Auth: X-User-ID / X-User-Role header extraction and role gating (PRD §2.1).

Validation priority 1 (context headers) then 2 (role permission). Ownership
(priority 3) is enforced per-endpoint where the Physician role is entity-backed.
"""
from flask import request, g

from errors import ApiError

ROLES = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_context():
    """Validate the two auth headers; populate flask.g with user_id/user_role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers are required and role must be declared")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(allowed):
    uid, role = get_context()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role %s is not permitted on this endpoint" % role)
    return uid, role


def ownership_violation(msg="Physician identity does not own the target resource"):
    raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, msg)
