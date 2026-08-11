"""Auth middleware and role checking per PRD §2.1."""
from flask import request

from errors import err_unauthenticated, err_unauthorized_role


VALID_ROLES = {
    "PlatformAdmin",
    "NetworkAffiliateRelations",
    "StationGroupOwner",
    "ComplianceAuditor",
}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_unauthenticated()
    if role not in VALID_ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_role(*allowed_roles):
    """Verify the caller's role is in the allowed set. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise err_unauthorized_role()
    return user_id, role
