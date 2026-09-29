"""Authentication and authorisation (PRD section 2.1, validations 1-4)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "LaboratoryUser",
    "SupplierUser",
    "CertificationOfficer",
    "DistributionManager",
)


def authenticate():
    """Priority 1: both headers present, non-empty, role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not user_id.strip() or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed):
    """Priorities 1 then 2, in that order, for a single endpoint."""
    user_id, role = authenticate()
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "role", None)


def require_assigned_lab(order):
    """Priority 3: acting LaboratoryUser must be the order's laboratory."""
    if current_role() == "LaboratoryUser" and current_user_id() != order["laboratory_id"]:
        raise ApiError("ERR_LAB_NOT_ASSIGNED")


def require_part_owner(part):
    """Priority 4: acting SupplierUser must own the component part."""
    if current_role() == "SupplierUser" and current_user_id() != part["supplier_id"]:
        raise ApiError("ERR_SUPPLIER_NOT_PART_OWNER")
