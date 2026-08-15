"""Auth header extraction and RBAC checks (SCAFFOLD validations priority 1-2)."""
from flask import request

from errors import ApiError, ERR_MISSING_CONTEXT, ERR_FORBIDDEN

ROLES = {
    "TeamAdmin",
    "MedicalStaff",
    "TeamPhysician",
    "PerformanceStaff",
    "BillingStaff",
    "CoachingStaff",
}


def ctx():
    """Returns (user_id, role); raises 400 on missing/invalid context headers."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str):
        raise ApiError(ERR_MISSING_CONTEXT, 400,
                       "X-User-ID header missing or invalid")
    if not role or role not in ROLES:
        raise ApiError(ERR_MISSING_CONTEXT, 400,
                       "X-User-Role header missing or invalid")
    return uid, role


def require_roles(*allowed):
    uid, role = ctx()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Role %s not permitted for this endpoint" % role)
    return uid, role
