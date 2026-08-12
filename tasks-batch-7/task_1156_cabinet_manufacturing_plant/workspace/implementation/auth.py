"""Auth header extraction + role gating (PRD §2.1, validations priority 1-2)."""
from flask import request

from domain import ALL_ROLES
from errors import api_error


def require_roles(allowed):
    """Priority 1: X-User-ID and X-User-Role present and role name declared.
    Priority 2: role is permitted for this endpoint.
    Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise api_error(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and X-User-Role must name a declared role",
        )
    if role not in allowed:
        raise api_error(
            "ERR_FORBIDDEN_ROLE",
            f"Role {role} is not permitted for this endpoint",
        )
    return uid, role


def require_any_role():
    """Read access is shared by all six declared roles."""
    return require_roles(ALL_ROLES)


def check_dealer_ownership(uid, resource_dealer_id):
    """Priority 3: entity-backed ownership for dealer-scoped operations."""
    if resource_dealer_id != uid:
        raise api_error(
            "ERR_RESOURCE_OWNERSHIP_MISMATCH",
            "The acting dealer does not own the target resource",
        )
