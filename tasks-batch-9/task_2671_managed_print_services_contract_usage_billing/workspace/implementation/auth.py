"""Authentication and role authorisation (PRD 2.1 / 2.9 priorities 1 and 2)."""
from flask import request

from errors import fail

ROLES = (
    "AccountManager",
    "BillingAnalyst",
    "FleetOpsController",
    "FieldTechnician",
    "CustomerAdmin",
)

ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: both headers present and the role is one of the five names."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or role == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role." % role)
    return user_id, role


def require(*allowed):
    """Priority 1 then priority 2; returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED",
             "Role '%s' may not call this endpoint." % role)
    return user_id, role
