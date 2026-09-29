"""Authentication, RBAC and entity-backed ownership (PRD §2.1, ladder rungs 1/2/13)."""

from flask import request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "Seller",
    "Trustee",
    "TitleOfficer",
    "ComplianceOfficer",
    "AuctionOps",
    "Bidder",
    "Anonymous",
)


def authenticate(allowed_roles):
    """Rung 1 then rung 2. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and a recognized X-User-Role are required.")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


def require_owner(user_id, expected_id):
    """Rung 13 — entity-backed identity must match the target."""
    if user_id != expected_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The acting principal does not own this resource.")
