"""Auth header extraction and RBAC enforcement."""
from flask import request

from errors import ApiError

VALID_ROLES = {"AccountManager", "GrantWriter", "ClientContact", "ComplianceOfficer", "Ops"}


def require_context():
    """Validate the X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or not user_id.strip() or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Role %s is not permitted for this endpoint" % role)
