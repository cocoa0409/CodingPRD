"""Auth header extraction and RBAC (PRD §2.1, §1.7).

Headers: X-User-ID and X-User-Role.
Roles (spelled precisely): GridOperator, ProgramAdmin, Subscriber.
"""
from flask import request

from errors import err

ROLES = {"GridOperator", "ProgramAdmin", "Subscriber"}


def get_caller():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role missing/unknown."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Authorization gate (priority 2). allowed is an iterable of role names."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
