"""Auth header extraction and role checking (PRD §2.1, §2.6).

Headers: X-User-ID (acting user), X-User-Role (capacity).
Roles (exact spelling): StudioAdmin, Designer, ProcurementCoordinator, Client.
"""
from flask import request

from errors import err

ROLES = {"StudioAdmin", "Designer", "ProcurementCoordinator", "Client"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role missing/unknown.

    Auth is validation priority 1 (PRD §2.6): a missing or unrecognized
    X-User-Role yields ERR_UNAUTHENTICATED.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header.")
    return user_id, role


def require_roles(role, allowed):
    """Authorization priority 2 (PRD §2.6): role must be permitted for the op."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation.")
