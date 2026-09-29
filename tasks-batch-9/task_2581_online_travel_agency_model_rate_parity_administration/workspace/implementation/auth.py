"""Authentication, authorisation and supplier scoping (PRD §2.1, §2.10 steps 1-3)."""
from flask import request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "CommercialManager",
    "ComplianceOfficer",
    "ParityAnalyst",
    "SupplierUser",
    "BookingAgent",
)

ALL_ROLES = ROLES


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_supplier(self):
        return self.role == "SupplierUser"


def authenticate(allowed_roles):
    """Priority 1 then priority 2: headers, then the endpoint's role list."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return Actor(user_id, role)


def require_supplier_scope(actor, supplier_id):
    """Priority 3: a SupplierUser write must target its own supplier."""
    if actor.role != "SupplierUser":
        return
    if supplier_id is None or actor.user_id != supplier_id:
        raise ApiError(
            "ERR_SUPPLIER_SCOPE_VIOLATION",
            "SupplierUser may only write against resources owned by its own supplier.",
        )


def require_supplier_scope_any(actor, supplier_ids):
    """Scope check for a target owned by any one of several suppliers."""
    if actor.role != "SupplierUser":
        return
    if actor.user_id not in [s for s in supplier_ids if s]:
        raise ApiError(
            "ERR_SUPPLIER_SCOPE_VIOLATION",
            "SupplierUser may only write against resources owned by its own supplier.",
        )


def require_distinct(actor, other_user_id):
    """Priority 10: segregation of duties (PRD §2.9)."""
    if other_user_id is not None and actor.user_id == other_user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The acting identity may not approve, waive or resolve its own submission.",
        )
