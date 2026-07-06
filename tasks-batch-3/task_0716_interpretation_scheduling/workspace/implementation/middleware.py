from flask import request

from errors import err

VALID_ROLES = {"PlatformAdmin", "CoordinatorOps", "ClientAccount", "Interpreter"}


def authenticate():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if headers missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)
