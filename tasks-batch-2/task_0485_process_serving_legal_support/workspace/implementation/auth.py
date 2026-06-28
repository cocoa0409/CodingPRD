"""Auth header extraction and RBAC (PRD 2.1).

Every request must carry X-User-ID and X-User-Role. The five known roles are
Admin, Dispatcher, Client, Server, Notary. Missing header or unknown role ->
ERR_UNAUTHENTICATED (401). Role not permitted for the endpoint ->
ERR_UNAUTHORIZED (403).
"""
from flask import request

from errors import err

KNOWN_ROLES = {"Admin", "Dispatcher", "Client", "Server", "Notary"}


def get_principal():
    """Return (user_id, role) after validating headers. Raises on auth failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers")
    return user_id, role


def require_roles(role, allowed):
    """Authorization check (priority 2). role must be in the allowed set."""
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
