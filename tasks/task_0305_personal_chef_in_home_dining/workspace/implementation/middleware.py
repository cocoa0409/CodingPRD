"""Auth header extraction and RBAC (PRD §2.1, §2.9; SCAFFOLD validations 1-2).

Every request must carry X-User-ID and X-User-Role. Missing/malformed ->
ERR_MISSING_AUTH_CONTEXT (401). Role not one of the three declared, or not
permitted for the operation -> ERR_UNAUTHORIZED_ROLE (403).
"""
from flask import request

from errors import err

ROLES = {"Chef", "Client", "PlatformAdmin"}


def get_auth():
    """Return (user_id, role) after validating presence/well-formedness and role membership.

    Raises ERR_MISSING_AUTH_CONTEXT if either header is missing/blank.
    Raises ERR_UNAUTHORIZED_ROLE if the role value is not a declared role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise err("ERR_MISSING_AUTH_CONTEXT", "Missing or malformed authentication context")
    if role not in ROLES:
        raise err("ERR_UNAUTHORIZED_ROLE", "Role '%s' is not a recognized role" % role)
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_UNAUTHORIZED_ROLE if role is not in the allowed set for the operation."""
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED_ROLE", "Role '%s' is not permitted for this operation" % role)
