"""Auth header extraction and role/ownership checks (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = {
    "MarketOperator",
    "VendorRole",
    "JuryMember",
    "JuryChair",
    "UtilityCrew",
    "FinanceOfficer",
}


class User:
    def __init__(self, user_id, role):
        self.id = user_id
        self.role = role


def auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Missing or malformed X-User-Role / X-User-ID",
            401,
        )
    return User(user_id, role)


def require_roles(user, allowed):
    if user.role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "role %s is not permitted for this endpoint" % user.role,
            403,
        )


def require_vendor_owner(user, vendor_id):
    """VendorRole callers may only act on resources whose vendor_id is them."""
    if user.role == "VendorRole" and vendor_id is not None and user.id != vendor_id:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "vendor may only act on its own resources",
            403,
        )
