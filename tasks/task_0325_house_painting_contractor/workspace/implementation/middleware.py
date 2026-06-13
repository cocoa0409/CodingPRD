"""Auth header extraction and role checking (PRD §2.1, §3.12).

Headers: X-User-ID (opaque actor), X-User-Role (one of the four roles).
Priority 1: both present and role declared, else ERR_MISSING_OR_INVALID_USER_CONTEXT (401).
Priority 2: acting role permitted for the endpoint, else ERR_FORBIDDEN_ROLE (403).
Identity is opaque for all roles — no entity-backed ownership check (PRD §2.1).
"""
from flask import request

from errors import err

ROLES = {"Estimator", "ProjectManager", "Customer", "CrewMember"}


def require_auth():
    """Validate headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT",
                  "X-User-ID and X-User-Role headers are required and the role must be declared.")
    return user_id, role


def require_role(role, allowed):
    """Role authorization (priority 2)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE",
                  "Acting role '%s' is not permitted for this operation." % role)
