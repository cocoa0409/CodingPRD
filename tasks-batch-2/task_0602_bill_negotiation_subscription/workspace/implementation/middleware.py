"""Auth header extraction and role checking."""
from flask import request

from errors import err

VALID_ROLES = {"Member", "ConciergeAgent", "PlatformAdmin"}


def get_auth():
    """Return (user_id, role). Does not validate; raises only structural error."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth():
    """Validate auth headers present and role recognized. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized auth headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
