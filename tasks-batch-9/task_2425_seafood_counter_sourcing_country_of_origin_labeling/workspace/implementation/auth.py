"""Authentication, RBAC and ownership scoping (PRD 2.1, rejection order 1-5)."""

from flask import g, request

from errors import fail

ROLES = (
    "ChainAdmin",
    "SeafoodManager",
    "ComplianceOfficer",
    "MerchandisingLead",
    "SupplierRep",
)


def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    g.role = role
    g.uid = user_id


def is_manager():
    return g.role == "SeafoodManager"


def is_supplier_rep():
    return g.role == "SupplierRep"


def counter_scope(counter_id):
    """Rejection order 3: a SeafoodManager's X-User-ID is the owning Counter id."""
    if counter_id is None:
        return
    if is_manager() and g.uid != counter_id:
        fail("ERR_COUNTER_SCOPE_FORBIDDEN")


def supplier_scope(supplier_id):
    """Rejection order 4: a SupplierRep's X-User-ID is the owning Supplier id."""
    if supplier_id is None:
        return
    if is_supplier_rep() and g.uid != supplier_id:
        fail("ERR_SUPPLIER_SCOPE_FORBIDDEN")
