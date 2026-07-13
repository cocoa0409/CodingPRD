from flask import request

from errors import ApiError

ROLES = {"Applicant", "PermitReviewer", "Inspector", "EnforcementOfficer", "PlatformAdmin"}


def authenticate():
    """Validate the two mandatory auth headers. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role not permitted for this operation")
