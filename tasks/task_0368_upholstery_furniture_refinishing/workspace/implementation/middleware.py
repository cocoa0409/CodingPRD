"""Auth header extraction and RBAC checks (PRD §2.1, §3.10).

Headers: X-User-ID (acting principal), X-User-Role (capacity).
Roles: IntakeClerk, Estimator, ShopManager, Customer.
"""
from flask import request

from errors import err
import errors

VALID_ROLES = {"IntakeClerk", "Estimator", "ShopManager", "Customer"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if either missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(errors.ERR_UNAUTHENTICATED,
                  "Missing X-User-ID or X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role not in allowed set."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE,
                  "Acting role is not permitted for this operation")


def require_owner(user_id, work_order):
    """For the four customer-acting ops: X-User-ID must equal customer_id."""
    if work_order["customer_id"] != user_id:
        raise err(errors.ERR_NOT_OWNER,
                  "Customer does not own this work order")
