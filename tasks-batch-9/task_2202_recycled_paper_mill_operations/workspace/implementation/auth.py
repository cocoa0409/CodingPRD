"""Auth header extraction + RBAC (PRD §2.1)."""
from flask import g, request

import store
from errors import err

ROLES = [
    "MillPlanner",
    "FiberBuyer",
    "QualityLab",
    "MachineOperator",
    "EnvironmentalOfficer",
    "EnergyManager",
    "Supplier",
    "Customer",
]

ENTITY_BACKED = {"Supplier": "suppliers", "Customer": "customers"}


def authenticate():
    """Validate headers; populate g.user_id / g.role / g.identity_row."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or not uid.strip() or not role.strip():
        raise err("ERR_MISSING_AUTH_HEADERS", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise err("ERR_UNKNOWN_ROLE", "Unknown role: %s" % role)
    g.user_id = uid
    g.role = role
    g.identity_row = None
    if role in ENTITY_BACKED:
        row = store.get(ENTITY_BACKED[role], uid)
        if row is None:
            raise err("ERR_IDENTITY_NOT_FOUND", "X-User-ID does not resolve to a %s" % role)
        g.identity_row = row


def require_roles(*allowed):
    if g.role not in allowed:
        raise err("ERR_ROLE_NOT_PERMITTED", "Role %s is not permitted for this operation" % g.role)


def role():
    return g.role


def user_id():
    return g.user_id


def own_supplier_or_403(supplier_id):
    if g.role == "Supplier" and supplier_id != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Supplier does not own this resource")


def own_customer_or_403(customer_id):
    if g.role == "Customer" and customer_id != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this resource")
