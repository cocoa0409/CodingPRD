"""Auth header extraction and RBAC (PRD §2.1).

Every request carries two mandatory headers: X-User-ID and X-User-Role.
Missing/malformed -> ERR_MISSING_USER_CONTEXT (401).
Role not permitted for the operation -> ERR_INSUFFICIENT_PERMISSIONS (403).
"""
from flask import request

from errors import err

ROLES = {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"}


def get_user_context():
    """Validate the two auth headers; return (user_id, role).

    Raises ERR_MISSING_USER_CONTEXT when either header is missing or malformed
    (the role must be one of the four recognized role strings).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_MISSING_USER_CONTEXT", "X-User-ID and X-User-Role headers are required")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_MISSING_USER_CONTEXT", "X-User-ID header is malformed")
    if role not in ROLES:
        raise err("ERR_MISSING_USER_CONTEXT", "X-User-Role header is malformed")
    return user_id, role


def require_role(role, allowed):
    """Enforce RBAC: the acting role must be in the allowed set for this endpoint."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "role %s may not perform this operation" % role)
