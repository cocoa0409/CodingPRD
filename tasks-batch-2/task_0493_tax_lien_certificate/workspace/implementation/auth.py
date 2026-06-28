"""Authentication & RBAC (PRD §2.1, §2.10, §2.11).

Every request must carry X-User-ID and X-User-Role. The three valid roles are
spelled exactly CountyTreasurer, Investor, Auditor. Missing header or unknown
role -> ERR_UNAUTHENTICATED (401). Valid role not permitted for the operation ->
ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, fail

VALID_ROLES = {"CountyTreasurer", "Investor", "Auditor"}


def get_caller():
    """Validate auth headers and return (user_id, role). Raises on failure.

    Priority 1 (PRD §2.10): authentication before everything else.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        fail(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Priority 2 (PRD §2.10): role must be permitted for this operation."""
    if role not in allowed:
        fail(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)
