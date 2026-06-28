"""Auth header extraction and RBAC. Header names and role values come verbatim
from PRD §2.1: X-User-ID, X-User-Role; roles PlatformAdmin, ApiaryManager,
StateApiarist, ContractCoordinator."""
from flask import request

import errors

KNOWN_ROLES = {"PlatformAdmin", "ApiaryManager", "StateApiarist", "ContractCoordinator"}


def get_identity():
    """PRD §2.1: every request carries X-User-ID and X-User-Role. If either header
    is missing, or X-User-Role is not a known role -> ERR_UNAUTHENTICATED (401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(allowed_roles):
    """Validate auth (401) then RBAC (403) in PRD §2.8 precedence order.
    Returns (user_id, role)."""
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise errors.forbidden_role()
    return user_id, role
