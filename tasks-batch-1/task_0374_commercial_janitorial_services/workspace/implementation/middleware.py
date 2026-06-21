"""Auth + RBAC helpers (PRD section 2.1, 2.6; scaffold validations 1-3)."""
from flask import request

from errors import err

KNOWN_ROLES = {"AccountManager", "FieldSupervisor", "ClientContact", "PlatformAdmin"}


def get_caller():
    """Return (user_id, role) after validating the auth headers.

    Raises ERR_UNAUTHENTICATED (401) when a header is missing or the role is
    not one of the four recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role permission. Raise ERR_FORBIDDEN (403) if not allowed."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s is not permitted for this operation" % role)
