"""Auth: X-User-ID / X-User-Role header extraction and RBAC checks."""
from flask import request

from errors import err

VALID_ROLES = {"Excavator", "FacilityOwner", "LocateTech", "CallCenter", "Admin"}


def get_user_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s is not permitted for this operation" % role)
