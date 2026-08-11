"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import unauthenticated, unauthorized

ROLES = {"Anonymous", "Member", "ShopStaff", "ComplianceOfficer", "PlatformAdmin"}


def get_auth():
    """Return (role, user_id). Raises ERR_UNAUTHENTICATED when malformed."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise unauthenticated()
    if role == "Anonymous":
        return role, uid
    if not uid:
        raise unauthenticated()
    return role, uid


def require(allowed_roles):
    """Authorize the caller against the endpoint's role list.

    Returns (role, user_id). PlatformAdmin inherits ShopStaff permissions
    (hierarchical override) but NOT Member or ComplianceOfficer permissions.
    """
    role, uid = get_auth()
    expanded = set(allowed_roles)
    if "ShopStaff" in expanded:
        expanded.add("PlatformAdmin")
    if role not in expanded:
        raise unauthorized()
    return role, uid


def require_member_ownership(role, uid, member_id):
    """When the caller is a Member, they may only act on their own resources."""
    if role == "Member" and uid != member_id:
        raise unauthorized("Member may only access own resources")
