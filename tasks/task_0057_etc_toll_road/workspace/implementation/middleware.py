from flask import request
import errors
from errors import err

KNOWN_ROLES = {"AccountHolder", "TollOperator", "InteropClerk", "SystemAdmin"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role missing/unknown."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in KNOWN_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "X-User-Role header missing or unknown")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
