"""Auth context extraction, role permission, and entity-backed ownership.

Headers: X-User-ID and X-User-Role. Six roles: FacilityAdmin, YardMaster,
SafetyOfficer, TransferOperator, BillingClerk, CustomerRep. For CustomerRep,
X-User-ID is the acting Customer's id; for the other roles it is opaque.
"""

from flask import request

from errors import (
    raise_err,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_RESOURCE_NOT_OWNED,
)

ROLES = {
    "FacilityAdmin", "YardMaster", "SafetyOfficer",
    "TransferOperator", "BillingClerk", "CustomerRep",
}

ALL_ROLES = [
    "FacilityAdmin", "YardMaster", "SafetyOfficer",
    "TransferOperator", "BillingClerk", "CustomerRep",
]


def auth_context():
    """Pipeline priority 1: both headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return user_id, role


def require_role(role, allowed):
    """Pipeline priority 2: role listed for the endpoint."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this endpoint" % role)


def require_ownership(user_id, role, customer_id):
    """Pipeline priority 6: a CustomerRep may only touch resources of their
    own customer record."""
    if role == "CustomerRep" and customer_id != user_id:
        raise_err(
            ERR_RESOURCE_NOT_OWNED,
            "CustomerRep may act only on resources of their own customer",
        )
