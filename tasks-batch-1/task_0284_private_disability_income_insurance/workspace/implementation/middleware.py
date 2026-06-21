"""Auth header extraction and RBAC (PRD §2.1).

Every request carries two mandatory headers: X-User-ID and X-User-Role.
Missing/malformed -> ERR_MISSING_AUTH_CONTEXT (401).
Role not permitted for the operation -> ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import raise_err, ERR_MISSING_AUTH_CONTEXT, ERR_FORBIDDEN_ROLE

# The system recognizes exactly four roles (PRD §2.1).
VALID_ROLES = {"Underwriter", "Policyholder", "ClaimsAdjudicator", "SystemOperator"}


def get_auth():
    """Return (user_id, role) or raise ERR_MISSING_AUTH_CONTEXT.

    Both headers must be present and well-formed; role must be a recognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise_err(ERR_MISSING_AUTH_CONTEXT, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise_err(ERR_MISSING_AUTH_CONTEXT, "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role: str, allowed):
    """Authorization gate (priority 2). allowed is a collection of role names."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, f"Role {role!r} not permitted for this operation")
