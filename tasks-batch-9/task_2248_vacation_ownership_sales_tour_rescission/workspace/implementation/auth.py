"""Authentication and RBAC (PRD 2.1, 2.9 steps 1-2)."""

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, fail

MARKETING_MANAGER = "MarketingManager"
GALLERY_MANAGER = "GalleryManager"
SALES_REPRESENTATIVE = "SalesRepresentative"
COMPLIANCE_OFFICER = "ComplianceOfficer"
CONTRACT_ADMINISTRATOR = "ContractAdministrator"
PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    MARKETING_MANAGER,
    GALLERY_MANAGER,
    SALES_REPRESENTATIVE,
    COMPLIANCE_OFFICER,
    CONTRACT_ADMINISTRATOR,
    PLATFORM_ADMIN,
)


def actor():
    """Return (user_id, role) after enforcing header presence and role recognition."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        fail(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    if role not in ALL_ROLES:
        fail(ERR_UNAUTHENTICATED, "unknown role: %s" % role)
    return user_id, role


def require(*allowed_roles):
    """Enforce headers then endpoint role authorisation; return (user_id, role)."""
    user_id, role = actor()
    if role not in allowed_roles:
        fail(ERR_UNAUTHORIZED, "role %s may not perform this operation" % role)
    return user_id, role


def require_any():
    return require(*ALL_ROLES)
