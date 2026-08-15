"""Auth header extraction and RBAC per PRD §2.1 and SCAFFOLD §1.7."""
from flask import request

from errors import err_forbidden, err_unauthenticated

ROLES = {"AquaticsManager", "GateAttendant", "Lifeguard", "PassHolder"}


def authenticate(allowed_roles):
    """Validate X-User-Role / X-User-ID and endpoint role permission.

    Returns (role, user_id). Priority order per PRD §2.10:
    1. X-User-Role present and one of the declared roles -> 401
    2. X-User-ID present -> 401
    3. Role permitted for this endpoint -> 403
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err_unauthenticated()
    user_id = request.headers.get("X-User-ID")
    if user_id is None or not isinstance(user_id, str) or user_id == "":
        raise err_unauthenticated()
    if role not in allowed_roles:
        raise err_forbidden()
    return role, user_id
