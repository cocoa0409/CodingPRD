"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.10).

Every request must carry X-User-ID and X-User-Role. Roles: PlanAdmin,
Dispatcher, Technician, Homeowner. Missing/unknown -> 401; role not permitted
for the operation -> 403.
"""
from flask import request

from errors import err

KNOWN_ROLES = {"PlanAdmin", "Dispatcher", "Technician", "Homeowner"}


def get_user_context():
    """Validate presence of headers and known role. Returns (user_id, role).

    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (401) on any failure.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            "Missing or invalid user context.",
        )
    return user_id, role


def require_roles(role, allowed):
    """Enforce that `role` is in the allowed set. Raises ERR_FORBIDDEN_ROLE (403)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
