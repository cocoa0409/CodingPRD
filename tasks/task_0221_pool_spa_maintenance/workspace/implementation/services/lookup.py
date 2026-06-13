"""Shared existence-checking lookups (PRD §2.6: referenced resource that names
no existing resource yields ERR_NOT_FOUND)."""
from db import db
from errors import err


def get_pool_or_404(pool_id):
    pool = db.pools.get(pool_id)
    if not pool:
        raise err("ERR_NOT_FOUND", "Pool not found")
    return pool


def get_customer_or_404(customer_id):
    c = db.customers.get(customer_id)
    if not c:
        raise err("ERR_NOT_FOUND", "Customer not found")
    return c


def get_plan_or_404(plan_id):
    p = db.service_plans.get(plan_id)
    if not p:
        raise err("ERR_NOT_FOUND", "Service plan not found")
    return p


def get_route_or_404(route_id):
    r = db.routes.get(route_id)
    if not r:
        raise err("ERR_NOT_FOUND", "Route not found")
    return r


def get_visit_or_404(visit_id):
    v = db.visits.get(visit_id)
    if not v:
        raise err("ERR_NOT_FOUND", "Visit not found")
    return v


def get_work_order_or_404(wo_id):
    wo = db.work_orders.get(wo_id)
    if not wo:
        raise err("ERR_NOT_FOUND", "Work order not found")
    return wo


def get_seasonal_event_or_404(ev_id):
    ev = db.seasonal_events.get(ev_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "Seasonal event not found")
    return ev


def get_invoice_or_404(inv_id):
    inv = db.invoices.get(inv_id)
    if not inv:
        raise err("ERR_NOT_FOUND", "Invoice not found")
    return inv
