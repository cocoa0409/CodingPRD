"""Authentication, RBAC and identity-scope enforcement (PRD 2.1)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "SystemAdmin",
    "InventoryAnalyst",
    "InventorySupervisor",
    "ShrinkController",
    "StoreOps",
    "VendorRep",
    "ThirdPartyCounter",
)

READ_ROLES = ("SystemAdmin", "InventoryAnalyst", "InventorySupervisor", "ShrinkController")


def authenticate():
    """Tier 1 of the rejection order — ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role")
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def require_roles(*allowed):
    """Tier 2 — ERR_ROLE_NOT_PERMITTED."""
    user_id, role = authenticate()
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "role %s may not perform this operation" % role)
    return user_id, role


def require_read():
    return require_roles(*READ_ROLES)


def scope_check(expected_entity_id):
    """Tier 3 — ERR_IDENTITY_SCOPE_VIOLATION.

    Called only for the three entity-backed roles, with the id of the entity
    the resource is scoped to.  ``expected_entity_id`` of None means the scope
    cannot be established, which is itself a violation.
    """
    if g.get("user_id") != expected_entity_id:
        raise ApiError("ERR_IDENTITY_SCOPE_VIOLATION",
                       "acting identity is not scoped to this resource")


def scope_store(store_id):
    if g.get("role") == "StoreOps":
        scope_check(store_id)


def scope_vendor(vendor_id):
    if g.get("role") == "VendorRep":
        scope_check(vendor_id)


def scope_counter_firm(counter_firm_id):
    if g.get("role") == "ThirdPartyCounter":
        scope_check(counter_firm_id)


def acting_user():
    return g.get("user_id")


def acting_role():
    return g.get("role")


def segregation_check(other_user_id):
    """PRD 2.1 — the two X-User-ID values must differ."""
    if other_user_id is not None and g.get("user_id") == other_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the acting user may not review their own work")
