"""Derived ledgers reconciled from live rows (PRD section 2.7)."""

from db import db, today, touch
from services import calc

INCLUDED_CLAIM_STATUSES = ("GENERATED", "SUBMITTED")


def customer_orders(customer_id):
    return [o for o in db.orders.values() if o["customer_id"] == customer_id]


def customer_returns(customer_id):
    return [r for r in db.return_requests.values() if r["customer_id"] == customer_id]


def plan_year_anchor(customer):
    plan = db.insurance_plans.get(customer.get("insurance_plan_id"))
    if plan is not None:
        return plan.get("plan_year_start_month_day") or "01-01"
    return "01-01"


def compute_allowance_used(customer):
    start, end = calc.plan_year_window(plan_year_anchor(customer), today())
    total = 0
    for claim in db.reimbursement_claims.values():
        if claim["customer_id"] != customer["id"]:
            continue
        if claim["status"] not in INCLUDED_CLAIM_STATUSES:
            continue
        created = claim["created_at"].date()
        if start <= created < end:
            total += claim.get("applied_allowance_cents") or 0
    return total


def compute_ledger(customer):
    """Recompute every derived counter without mutating the row."""
    orders = customer_orders(customer["id"])
    returns = customer_returns(customer["id"])
    charged = sum(o["total_cents"] for o in orders if o["fulfillment_state"] != "CANCELLED")
    refunded = sum(
        (r.get("settlement_cents") or 0)
        for r in returns
        if r["status"] == "SETTLED" and r.get("settlement_channel") == "CASH_REFUND"
    )
    store_credit = sum(
        (r.get("settlement_cents") or 0)
        for r in returns
        if r["status"] == "SETTLED" and r.get("settlement_channel") == "STORE_CREDIT"
    )
    allowance_used = compute_allowance_used(customer)
    open_holds = sum(
        1
        for h in db.reorder_holds.values()
        if h["customer_id"] == customer["id"] and h["status"] == "OPEN"
    )
    active_schedules = sum(
        1
        for s in db.auto_reorder_schedules.values()
        if s["customer_id"] == customer["id"] and s["status"] == "ACTIVE"
    )
    return {
        "store_credit_cents": store_credit,
        "lifetime_charged_cents": charged,
        "lifetime_refunded_cents": refunded,
        "net_cash_position_cents": charged - refunded,
        "allowance_used_cents": allowance_used,
        "open_hold_count": open_holds,
        "active_schedule_count": active_schedules,
        "auto_reorder_enabled": active_schedules > 0 and open_holds == 0,
    }


def allowance_remaining(customer, allowance_used=None):
    plan = db.insurance_plans.get(customer.get("insurance_plan_id"))
    if plan is None:
        return 0
    if allowance_used is None:
        allowance_used = compute_allowance_used(customer)
    return max(0, plan["annual_allowance_cents"] - allowance_used)


def reconcile_customer(customer):
    """Apply the reconciled ledgers; the reconciliation itself is a mutation."""
    if customer is None:
        return
    customer.update(compute_ledger(customer))
    touch(customer)


def reconcile_customer_id(customer_id):
    reconcile_customer(db.customers.get(customer_id))


def reconcile_prescription_boxes(prescription):
    """INV_BOXES: boxes_consumed over non-CANCELLED orders on the prescription."""
    if prescription is None:
        return
    total = 0
    for order in db.orders.values():
        if order["prescription_id"] != prescription["id"] and order.get("prescription_id") != prescription["id"]:
            continue
        if order["fulfillment_state"] == "CANCELLED":
            continue
        total += order["boxes_od"] + order["boxes_os"]
    prescription["boxes_consumed"] = total
    touch(prescription)


def has_open_hold(customer_id):
    return any(
        h["customer_id"] == customer_id and h["status"] == "OPEN" for h in db.reorder_holds.values()
    )


def settled_settlements_on_order(order_id, exclude_id=None):
    total = 0
    for r in db.return_requests.values():
        if r["order_id"] != order_id or r["status"] != "SETTLED":
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        total += r.get("settlement_cents") or 0
    return total
