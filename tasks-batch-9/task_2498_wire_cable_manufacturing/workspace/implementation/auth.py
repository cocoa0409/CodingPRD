"""Authentication and role authorization (PRD 2.1, ladder rungs 1 and 2)."""

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, fail

ROLES = (
    "PlantAdmin",
    "ProcurementBuyer",
    "ProcessEngineer",
    "QualityEngineer",
    "CertificationOfficer",
    "ShippingClerk",
    "BillingAnalyst",
    "Customer",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == "Customer"


def require_auth(*allowed_roles):
    """Rung 1: both headers present and non-empty.  Rung 2: role allowed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        fail(ERR_UNAUTHENTICATED, "X-User-ID header is required")
    if role is None or role.strip() == "":
        fail(ERR_UNAUTHENTICATED, "X-User-Role header is required")
    if role not in allowed_roles:
        fail(ERR_UNAUTHORIZED, "Role %s may not perform this operation" % role)
    return Actor(user_id, role)


def deny():
    fail(ERR_UNAUTHORIZED, "The acting account may not reach this resource")
