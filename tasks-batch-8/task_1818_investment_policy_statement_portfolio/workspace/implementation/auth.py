from flask import request
from errors import ApiError

ROLES = {"Advisor", "ComplianceOfficer", "Client", "CommitteeMember",
         "CommitteeChair", "PlatformAdmin"}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Unrecognized role")
    return uid, role


def authorize(*allowed):
    """Returns (user_id, role). Raises 401 then 403 per validation priority."""
    uid, role = authenticate()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Role not authorized for this endpoint")
    return uid, role
