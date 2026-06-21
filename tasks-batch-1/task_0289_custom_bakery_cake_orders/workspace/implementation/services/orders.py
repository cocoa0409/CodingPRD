"""Shared order helpers: lookup with ownership, line recompute, capacity check."""
from flask import g

from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_NOT_ORDER_OWNER, ERR_REFERENCE_NOT_FOUND,
)
from services import calculations as calc


def get_order_or_404(order_id):
    obj = store.orders.get(order_id)
    if obj is None:
        raise err(ERR_NOT_FOUND, "order not found")
    return obj


def assert_owner(order):
    """Customer-owned action: X-User-ID must equal order.customer_id."""
    if g.role == "Customer" and g.user_id != order["customer_id"]:
        raise err(ERR_NOT_ORDER_OWNER, "caller is not the order owner")


def option_index():
    """Map option_code -> option dict (codes are unique among options)."""
    idx = {}
    for o in store.options.values():
        idx[o["option_code"]] = o
    return idx


def order_lines(order_id):
    items = [l for l in store.lines.values() if l["order_id"] == order_id]
    return sorted(items, key=lambda l: (l["created_at"], l["id"]))


def order_units(order_id):
    return sum(l["units"] for l in store.lines.values() if l["order_id"] == order_id)


def recompute_estimate(order):
    """Re-run estimate_pricing + deposit_calc and set balance. Used while QUOTED."""
    product = store.products[order["product_id"]]
    pday = store.production_days[order["production_day_id"]]
    lines = order_lines(order["id"])
    total, peak = calc.compute_pricing(lines, product, pday)
    order["estimate_total_cents"] = total
    order["peak_surcharge_cents"] = peak
    deposit = calc.compute_deposit(total, pday, product)
    order["deposit_due_cents"] = deposit
    order["balance_due_cents"] = total - deposit
