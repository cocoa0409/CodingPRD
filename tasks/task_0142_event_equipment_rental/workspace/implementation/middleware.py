"""Auth header extraction & RBAC per PRD §2.1 and scaffold §1.4 / §1.7.

Every request must carry X-User-ID and X-User-Role. Recognised roles, spelt
exactly as below (PRD §2.1), are Customer, RentalAgent, DepositAdjuster.
"""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

VALID_ROLES = {"Customer", "RentalAgent", "DepositAdjuster"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED (PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise_err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role header")
    return user_id, role


def require_role(role: str, allowed):
    """Authorization check (priority 2): the acting role must be permitted for
    this operation per the RBAC matrix (scaffold §1.7).
    """
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED, f"Role {role!r} not permitted on this endpoint")
