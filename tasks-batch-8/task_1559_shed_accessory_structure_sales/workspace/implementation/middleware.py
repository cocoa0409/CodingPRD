"""Auth header extraction and role checking (SCAFFOLD Table 7 / PRD §2.1).

Every request must carry X-User-ID and X-User-Role. Customer identity is
entity-backed (X-User-ID == Customer.id); all other roles are opaque staff
identifiers.
"""

from flask import request, g

import db
from errors import unauthenticated, forbidden

ROLES = ["Customer", "SalesRep", "PermitCoordinator", "InstallCrew", "FinanceManager", "OperationsAdmin"]


def authenticate():
    """Priority-1 check: headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    g.user_id = user_id
    g.role = role


def require_roles(*allowed: str):
    """Priority-2 check: role permitted on this endpoint."""
    if g.role not in allowed:
        raise forbidden(f"Role {g.role} is not permitted on this endpoint")


def check_customer_owns_order(order: dict):
    """Customer callers may only act on resources of their own orders."""
    if g.role == "Customer" and order.get("customer_id") != g.user_id:
        raise forbidden("Customer may only access their own resources")
