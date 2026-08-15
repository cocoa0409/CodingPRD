"""Auth header extraction and role checking.

Headers: X-User-ID and X-User-Role. Roles (exact spellings):
PlatformAdmin, BrokerOps, Grower, Buyer, LabTechnician.
"""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ROLES = {"PlatformAdmin", "BrokerOps", "Grower", "Buyer", "LabTechnician"}


def authenticate():
    """Priority 1: headers present and role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-ID and X-User-Role headers are required and the role must be a declared role")
    return uid, role


def authorize(allowed_roles):
    """Priority 1 + 2. Returns (user_id, role)."""
    uid, role = authenticate()
    if role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                       f"role {role} is not authorized for this operation")
    return uid, role
