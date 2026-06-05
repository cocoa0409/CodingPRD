"""Auth header extraction + RBAC (PRD §2.1).

Two mandatory headers: X-User-ID and X-User-Role. Recognized roles are exactly
SpecialEdAdmin, CaseManager, Evaluator, Parent. All identity is opaque.
"""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"SpecialEdAdmin", "CaseManager", "Evaluator", "Parent"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, f"Unknown role {role!r}")
    return user_id, role


def require_role(role: str, allowed):
    """RBAC permission check (priority 2). Raise ERR_FORBIDDEN if not permitted."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, f"Role {role!r} not permitted for this operation")
