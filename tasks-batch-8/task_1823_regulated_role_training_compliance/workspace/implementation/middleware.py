"""Auth context (X-User-ID / X-User-Role) and role gating (PRD 2.1, validation P1-P3)."""
from flask import g, request

from errors import ApiError

ROLES = {"ComplianceAdmin", "HRAdmin", "Manager", "Employee", "Auditor", "Anonymous"}
AUTHENTICATED = ("ComplianceAdmin", "HRAdmin", "Manager", "Employee", "Auditor")


def auth_context():
    """P1: both headers present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip() or role is None or not str(role).strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-ID and X-User-Role headers are required")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(*allowed):
    """P1 then P2: role must be permitted for the endpoint. Anonymous/unrecognized: denied."""
    uid, role = auth_context()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role %s is not permitted here" % role)
    return uid, role


def require_any_authenticated():
    return require_roles(*AUTHENTICATED)
