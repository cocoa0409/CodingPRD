"""Auth/RBAC middleware (PRD §2.1, §2.9 validation ordering).

Headers: X-User-ID (acting user), X-User-Role (operational capacity).
Six recognized roles, spelled exactly.
"""
from flask import request

from errors import err

ROLES = {
    "PlatformAdmin",
    "SystemsDesigner",
    "ProjectManager",
    "LowVoltageTech",
    "SupportEngineer",
    "Client",
}


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and role is recognized.

    Returns (user_id, role) or raises ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2: acting role permitted for this endpoint.

    Raises ERR_UNAUTHORIZED (403) otherwise.
    """
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
