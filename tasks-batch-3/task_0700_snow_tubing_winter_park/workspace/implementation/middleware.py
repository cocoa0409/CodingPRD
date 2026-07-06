"""Auth header extraction and RBAC enforcement.

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Roles, spelled exactly: Anonymous, GuestPatron, GroupHost, ParkOperator, SafetyMarshal.
"""
from flask import request

from errors import err

VALID_ROLES = {"Anonymous", "GuestPatron", "GroupHost", "ParkOperator", "SafetyMarshal"}

# Endpoints that accept unauthenticated callers (bootstrap).
# These skip the auth header requirement entirely.
BOOTSTRAP_ENDPOINTS = {
    ("POST", "/patrons"),
    ("POST", "/parks"),
}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(method, route_key):
    """Validate auth headers. Returns a Caller.

    For bootstrap endpoints, missing/invalid headers are tolerated and the caller
    is treated as Anonymous when headers are absent. If headers ARE present they
    must still be a declared role (Anonymous or ParkOperator both permitted there).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    is_bootstrap = (method, route_key) in BOOTSTRAP_ENDPOINTS

    if is_bootstrap:
        # Bootstrap endpoints accept unauthenticated callers. If no role header at
        # all is supplied, treat as Anonymous. If a role header is supplied it must
        # be a declared role.
        if role is None and user_id is None:
            return Caller(None, "Anonymous")
        if role is None or role not in VALID_ROLES:
            raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role header.")
        if user_id is None:
            raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID header.")
        return Caller(user_id, role)

    # Authenticated endpoint: both headers required, role must be declared.
    if not role or not user_id:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown X-User-Role value.")
    return Caller(user_id, role)


def require_roles(caller, allowed_roles):
    """Enforce that the caller's role is in allowed_roles, else ERR_FORBIDDEN_ROLE."""
    if caller.role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint.")
