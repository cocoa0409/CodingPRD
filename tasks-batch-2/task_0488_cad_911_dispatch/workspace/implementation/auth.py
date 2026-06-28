"""Auth header extraction and RBAC (PRD §2.1, Scaffold Table 7).

Every request carries X-User-ID (acting user) and X-User-Role (operational
capacity). If X-User-Role is missing or names no recognized role, reject with
ERR_UNAUTHENTICATED (401). A recognized but unpermitted role yields
ERR_FORBIDDEN_ROLE (403).

For FieldUnit, X-User-ID is the id of the acting Unit (ownership checks on
assignment field operations compare the assignment's unit to X-User-ID). For
every other role X-User-ID is an opaque operator id, never compared to entities.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {"Calltaker", "Dispatcher", "FieldUnit", "Supervisor", "Records", "SystemClock"}


def authenticate():
    """Validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role header.")
    return user_id, role


def require_role(role, allowed):
    """Reject with ERR_FORBIDDEN_ROLE if role is not in the allowed set."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")
