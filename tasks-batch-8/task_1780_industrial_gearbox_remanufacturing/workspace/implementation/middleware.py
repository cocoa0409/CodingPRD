"""Auth: X-User-ID / X-User-Role header extraction, role gating, ownership (PRD 2.1)."""
from flask import request, g

from db import store
from errors import ApiError

ROLES = [
    "IntakeCoordinator",
    "RemanEngineer",
    "QualityInspector",
    "ServiceManager",
    "Customer",
]

ALL_ROLES = list(ROLES)


def get_context():
    """Validate the X-User-Role header; returns (user_id, role, request).

    PRD 2.1: a request with a missing or unrecognized X-User-Role header is
    rejected with ERR_UNAUTHENTICATED (401). X-User-ID is opaque for staff
    roles; for Customer it is the acting Customer entity id.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or unrecognized X-User-Role header")
    g.user_id = uid
    g.user_role = role
    return uid, role, request


def require_roles(allowed):
    role = getattr(g, "user_role", None)
    if role is None:
        get_context()
        role = g.user_role
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role %s is not permitted for this endpoint" % role)


def owning_customer_id_of_unit(unit):
    return unit.get("customer_id")


def owning_customer_id_of_order(order):
    unit = store.units.get(order.get("gear_unit_id"))
    return unit.get("customer_id") if unit else None


def owning_customer_id_of_claim(claim):
    order = store.orders.get(claim.get("reman_order_id"))
    if order is None:
        return None
    return owning_customer_id_of_order(order)


def check_customer_scope(uid, role, owning_customer_id):
    """Entity-backed ownership (PRD 2.1): Customer may act only on its own chain."""
    if role == "Customer" and uid != owning_customer_id:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Customer may only access its own record, units and orders")
