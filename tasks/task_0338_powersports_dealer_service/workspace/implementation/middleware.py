"""Auth header extraction and RBAC enforcement (PRD 2.1, 2.8)."""

from flask import request

import errors

VALID_ROLES = {
    "SalesManager",
    "FinanceManager",
    "ServiceAdvisor",
    "PartsClerk",
    "DealerPrincipal",
}


def get_user_context():
    """Validate the two mandatory auth headers. Returns (user_id, role).

    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (401) if either header is
    missing/blank or the role is not a recognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        errors.err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT)
    return user_id, role


def require_role(role, allowed):
    """Enforce RBAC: role must be in the allowed set for the operation."""
    if role not in allowed:
        errors.err(errors.ERR_FORBIDDEN_ROLE)
