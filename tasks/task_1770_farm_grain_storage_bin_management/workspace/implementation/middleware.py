"""Auth middleware (PRD 2.1): X-User-ID / X-User-Role header extraction and
role checking. Validation priority 1 (unauthenticated) then 2 (forbidden)."""
from flask import request

from errors import ApiError

DECLARED_ROLES = {"SiteManager", "FarmOwner", "CertifiedApplicator", "SafetyOfficer"}
ALL_ROLES = ("SiteManager", "FarmOwner", "CertifiedApplicator", "SafetyOfficer")

HDR_USER_ID = "X-User-ID"
HDR_USER_ROLE = "X-User-Role"


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED (401)."""
    user_id = (request.headers.get(HDR_USER_ID) or "").strip()
    role = (request.headers.get(HDR_USER_ROLE) or "").strip()
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and the role must be known")
    return user_id, role


def require_roles(*allowed_roles):
    """Authenticate and enforce endpoint role membership (ERR_FORBIDDEN 403)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403,
                       f"role {role} is not permitted for this endpoint")
    return user_id, role
