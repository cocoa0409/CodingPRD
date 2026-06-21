"""Auth header extraction and RBAC (PRD §2.1, §2.10, scaffold validations 1-2).

Two mandatory headers: X-User-ID, X-User-Role.
Roles: Customer, DispatchOperator, BillingClerk, PlatformAdmin.
- Missing/invalid X-User-Role, or missing X-User-ID for the entity-backed
  Customer role => ERR_UNAUTHENTICATED (401).
- Role not permitted for the endpoint, or Customer acting on a resource it does
  not own => ERR_FORBIDDEN (403).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"Customer", "DispatchOperator", "BillingClerk", "PlatformAdmin"}


def authenticate():
    """Validate the auth headers. Returns (role, user_id). Raises 401 on failure."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role header.")
    # Customer is the only entity-backed role; it requires X-User-ID.
    if role == "Customer" and (user_id is None or user_id == ""):
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID for Customer role.")
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role %s not permitted for this endpoint." % role)


def require_owner_or_operator(role, user_id, customer_id):
    """Ownership rule (PRD §2.1): a Customer may act only on resources owned by
    them. Operator roles are opaque and bypass the ownership comparison."""
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_FORBIDDEN, "Customer does not own this resource.")
