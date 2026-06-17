"""Auth header extraction and RBAC enforcement (PRD 2.1, validations p1/p2)."""

from flask import request

import errors

ROLES = {"AccountManager", "CrewLead", "QualityInspector", "DispatchOperator"}


def get_user_context():
    """Validate the two mandatory auth headers. Returns (user_id, role).

    Missing X-User-ID, missing X-User-Role, or an unrecognized role ->
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.fail(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "Missing or invalid user context headers")
    return user_id, role


def require_role(role, allowed):
    """RBAC check (priority 2). allowed is an iterable of role names."""
    if role not in allowed:
        errors.fail(errors.ERR_INSUFFICIENT_PERMISSIONS,
                    "Role '%s' is not permitted for this operation" % role)
