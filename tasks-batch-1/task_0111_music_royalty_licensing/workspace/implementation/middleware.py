"""Auth header extraction and RBAC.

Headers (PRD §2.1): X-User-ID identifies the acting user; X-User-Role declares
the operational capacity. Missing/malformed -> ERR_UNAUTHENTICATED. Role not
permitted -> ERR_UNAUTHORIZED.

Roles spelled precisely (PRD §2.1): Administrator, RoyaltyOperator, Licensee,
Rightsholder.

Administrator/RoyaltyOperator are opaque operator identities (X-User-ID not tied
to any entity). Licensee/Rightsholder are entity-backed: X-User-ID is the acting
Rightsholder.id.
"""
from flask import request

from errors import fail, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

VALID_ROLES = {"Administrator", "RoyaltyOperator", "Licensee", "Rightsholder"}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if headers missing or
    the role is not one of the four recognized values."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or user_id.strip() == "" or role.strip() == "":
        fail(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    if role not in VALID_ROLES:
        fail(ERR_UNAUTHENTICATED, "X-User-Role is not a recognized role")
    return user_id, role


def authorize(allowed_roles):
    """Validate auth (priority 1) then role membership (priority 2).
    Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        fail(ERR_UNAUTHORIZED, f"Role {role} may not perform this operation")
    return user_id, role
