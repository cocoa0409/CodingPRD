"""Cross-entity domain helpers: order-total recompute, customer open-plan count,
financing periods-elapsed, and FK-collection lookups.
"""
from datetime import timedelta

import clock
import db
from services import calculations as calc


# ---------------------------------------------------------------------------
# Collection lookups by FK
# ---------------------------------------------------------------------------
def lines_for_order(order_id):
    return [ln for ln in db.order_lines.values() if ln["order_id"] == order_id]


def active_lines_for_order(order_id):
    return [ln for ln in lines_for_order(order_id) if ln["status"] == "ACTIVE"]


def financing_plans_for_order(order_id):
    return [p for p in db.financing_plans.values() if p["order_id"] == order_id]


def open_financing_plans_for_order(order_id):
    """Plans in PENDING_APPROVAL or CURRENT for this order."""
    return [p for p in financing_plans_for_order(order_id)
            if p["status"] in ("PENDING_APPROVAL", "CURRENT")]


def stops_for_order(order_id):
    return [s for s in db.delivery_stops.values() if s["order_id"] == order_id]


def active_stops_for_order(order_id):
    return [s for s in stops_for_order(order_id) if s["status"] in ("BOOKED", "DISPATCHED")]


def stops_for_route(route_id):
    return [s for s in db.delivery_stops.values() if s["route_id"] == route_id]


def active_stops_for_route(route_id):
    return [s for s in stops_for_route(route_id) if s["status"] in ("BOOKED", "DISPATCHED")]

def payments_for_plan(plan_id):
    return [p for p in db.payments.values() if p["financing_plan_id"] == plan_id]


def returns_for_order(order_id):
    return [r for r in db.return_requests.values() if r["order_id"] == order_id]


def active_protection_plans_for_line(line_id):
    return [p for p in db.protection_plans.values()
            if p["order_line_id"] == line_id and p["status"] == "ACTIVE"]


# ---------------------------------------------------------------------------
# Order total recomputation (calc order_* family)
# ---------------------------------------------------------------------------
def recompute_order_totals(order):
    """Recompute merchandise_subtotal, service_total, order_total from ACTIVE lines.
    Does NOT touch version/updated_at — the caller decides whether this is a
    standalone mutation (line add/remove, confirm, pay-in-full) and bumps version.
    """
    active = active_lines_for_order(order["id"])
    merchandise = calc.order_merchandise_subtotal(active)
    service = calc.order_service_total(order["delivery_tier"], active)
    total = calc.order_grand_total(merchandise, service)
    order["merchandise_subtotal_cents"] = merchandise
    order["service_total_cents"] = service
    order["order_total_cents"] = total


def compute_earliest_schedulable_date(order):
    """created_at date + max lead_days over ACTIVE special-order lines (else +0).
    Null until at least one line exists.
    """
    all_lines = lines_for_order(order["id"])
    if not all_lines:
        return None
    active = active_lines_for_order(order["id"])
    max_lead = 0
    for ln in active:
        product = db.products.get(ln["product_id"])
        if product and product.get("is_special_order"):
            max_lead = max(max_lead, product.get("lead_days", 0))
    created = clock.parse_iso(order["created_at"])
    base_date = created.replace(hour=0, minute=0, second=0, microsecond=0)
    sched = base_date + timedelta(days=max_lead)
    return clock.format_iso(sched)


# ---------------------------------------------------------------------------
# Customer open_financing_count (CURRENT or PAST_DUE plans)
# ---------------------------------------------------------------------------
def recompute_open_financing_count(customer_id):
    """open_financing_count = number of this customer's plans in {CURRENT, PAST_DUE}."""
    customer = db.customers.get(customer_id)
    if customer is None:
        return
    count = sum(
        1 for p in db.financing_plans.values()
        if p["customer_id"] == customer_id and p["status"] in ("CURRENT", "PAST_DUE")
    )
    customer["open_financing_count"] = count


# ---------------------------------------------------------------------------
# Financing recompute on payment
# ---------------------------------------------------------------------------
def recompute_plan_payment_aggregates(plan):
    """Recompute paid_to_date_cents, payments_made_count, payoff_balance_cents."""
    pays = payments_for_plan(plan["id"])
    plan["paid_to_date_cents"] = sum(p["amount_cents"] for p in pays)
    plan["payments_made_count"] = len(pays)
    plan["payoff_balance_cents"] = calc.financing_payoff_balance(plan)


def periods_elapsed(plan):
    """Whole calendar months from activation date to current clock, capped at term_months.
    Advance month-by-month; a partial month does not count.
    """
    activation = plan.get("_activation_date")
    if activation is None:
        return 0
    start = clock.parse_iso(activation)
    now = clock.now()
    raw = _whole_months_between(start, now)
    return min(raw, plan["term_months"])


def _whole_months_between(start, now):
    """Count complete months elapsed from start to now (date components, UTC)."""
    if now < start:
        return 0
    months = (now.year - start.year) * 12 + (now.month - start.month)
    # If the day-of-month (and time-of-day) hasn't reached start's, the current
    # partial month does not count.
    if (now.day, now.hour, now.minute, now.second, now.microsecond) < \
       (start.day, start.hour, start.minute, start.second, start.microsecond):
        months -= 1
    return max(months, 0)
