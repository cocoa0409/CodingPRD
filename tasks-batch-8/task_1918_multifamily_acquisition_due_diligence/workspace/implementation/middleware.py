"""Auth header extraction and role checking."""

from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = [
    "PlatformAdmin",
    "AcquisitionsAnalyst",
    "UnderwritingManager",
    "PropertyOperationsLead",
    "HRPartner",
    "VendorManager",
    "EscrowOfficer",
]


def get_caller():
    """Extract X-User-ID and X-User-Role, raising ERR_UNAUTHENTICATED when missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED, "X-User-Role is not a declared role")
    return user_id, role


def require_role(role, allowed_roles):
    """Raise ERR_FORBIDDEN if role is not in allowed_roles."""
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, "role not authorized for this endpoint")
