"""Auth header extraction and RBAC (PRD §2.1, §2.6).

Headers: X-User-ID and X-User-Role. X-User-Role must be one of the four known
roles. Missing header or unknown role => ERR_UNAUTHENTICATED (401).
Role not permitted for the operation => ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import err

KNOWN_ROLES = {"Dispatcher", "Customer", "Technician", "Inspector"}


def get_identity():
    """Return (user_id, role) after validating presence and known role.

    Raises ERR_UNAUTHENTICATED if a header is missing or role is unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    """ERR_FORBIDDEN_ROLE if the acting role is not in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role {} is not permitted for this operation".format(role))
