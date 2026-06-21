"""Auth header extraction and RBAC enforcement (PRD 2.1, 2.6)."""

from flask import request

import errors

# The four recognized roles (PRD 2.1).
VALID_ROLES = {"DealerManager", "SalesAgent", "ServiceAdvisor", "Customer"}


def get_auth():
    """Validate the two mandatory auth headers. Returns (user_id, role).

    Missing or malformed X-User-ID / X-User-Role => ERR_MISSING_AUTH (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        errors.err("ERR_MISSING_AUTH", "Missing or malformed authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Enforce RBAC: the declared role must be permitted for this operation."""
    if role not in allowed:
        errors.err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
