"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 p1-p2).

Headers: X-User-ID and X-User-Role on every request.
Roles: MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep.
CustomerRep is entity-backed: X-User-ID must equal an existing Customer.id,
and ownership checks compare resource.customer_id to X-User-ID.
"""

from flask import request

from db import store
from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "MarketAdmin",
    "Receiver",
    "USDAInspector",
    "SalesDesk",
    "BillingClerk",
    "CustomerRep",
}

# Roles allowed on every GET endpoint.
ALL_ROLES = [
    "MarketAdmin",
    "Receiver",
    "USDAInspector",
    "SalesDesk",
    "BillingClerk",
    "CustomerRep",
]


def get_auth():
    """Validate auth headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED, f"Unrecognized role: {role}")
    if role == "CustomerRep" and user_id not in store.customers:
        raise_error(
            ERR_UNAUTHENTICATED,
            "CustomerRep X-User-ID must equal an existing Customer id",
        )
    return user_id, role


def require_roles(allowed_roles):
    """Validate auth then role permission (priorities 1-2)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, f"Role {role} not permitted for this endpoint")
    return user_id, role


def check_customer_ownership(user_id, role, customer_id):
    """CustomerRep may only touch resources whose customer_id == X-User-ID."""
    if role == "CustomerRep" and customer_id != user_id:
        raise_error(ERR_FORBIDDEN, "CustomerRep may only access own resources")
