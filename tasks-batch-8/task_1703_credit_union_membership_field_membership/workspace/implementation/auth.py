"""Authentication (tier 1), role authorization (tier 2), ownership (tier 3)."""
from flask import request

from errors import ApiError

MEMBER = "Member"
STAFF_ROLES = {
    "MembershipOfficer",
    "ComplianceOfficer",
    "Regulator",
    "BoardDirector",
    "OperationsOfficer",
}
ALL_ROLES = STAFF_ROLES | {MEMBER, "SystemAdmin"}


def require_roles(allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       f"role {role} is not permitted on this endpoint")
    return uid, role


def check_member_owns(uid, role, owner_member_id):
    """Tier 3: a Member-role caller may only touch their own records."""
    if role == MEMBER and uid != owner_member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Member role may only access its own records")
