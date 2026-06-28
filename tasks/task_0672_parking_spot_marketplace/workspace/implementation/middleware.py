"""Auth header extraction and role checking.

Auth headers (PRD §2.1): X-User-ID identifies the acting user; X-User-Role declares
the operational capacity. Roles spelled exactly: Anonymous, Host, Driver, PlatformAdmin.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"Anonymous", "Host", "Driver", "PlatformAdmin"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    """Extract and validate the auth headers. Returns a Caller or raises 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role.")
    return Caller(user_id, role)


def require_auth():
    """Authenticated endpoints: header must be present, well-formed, valid role."""
    return get_caller()


def require_role(caller, *allowed_roles):
    """Role permission check (ERR_FORBIDDEN_ROLE)."""
    if caller.role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")
