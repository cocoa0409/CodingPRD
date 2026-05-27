"""Auth header extraction and role authorisation (per PRD §2.1)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED


# The four recognised roles, spelled verbatim per PRD §2.1.
VALID_ROLES = {"Member", "MemberServices", "LoyaltyManager", "ComplianceOfficer"}


def require_auth():
    """Return (user_id, user_role) — raises ERR_UNAUTHENTICATED if missing/blank."""
    uid = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not uid or not role:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "missing X-User-ID or X-User-Role")
    return uid, role


def require_role(allowed_roles):
    """Authenticate then verify role membership."""
    uid, role = require_auth()
    if role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED, 403, f"role {role!r} not permitted")
    return uid, role
