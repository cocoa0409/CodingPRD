"""Authentication & RBAC (PRD §2.1).

Two mandatory headers: X-User-ID and X-User-Role. Five roles spelled exactly:
ServiceManager, FieldTech, Dispatcher, BillingClerk, Customer.

ServiceManager is a hierarchical superset: it may perform every operation any
other role can. So role permission is satisfied when the caller's role is in
the endpoint's allowed set (ServiceManager is always listed where it applies).
"""
from flask import request

from errors import err

VALID_ROLES = {"ServiceManager", "FieldTech", "Dispatcher", "BillingClerk", "Customer"}


def authenticate():
    """Validate presence/shape of auth headers. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED (401) when missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-Role header")
    return user_id, role


def authorize(role, allowed_roles):
    """ERR_UNAUTHORIZED (403) when role not permitted for the operation."""
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role %s not permitted for this operation" % role)
