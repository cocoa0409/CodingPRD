"""Return credit calculation and application (PRD §3.8, calculations.return_credit).

The credit is floor(quantity_returned * per_unit * restock_rate) — the pinned
rounding order multiplies through before the floor, so 3 * 9999 * 0.50 yields
14998 (not the per-unit-first 14997). Whole days since delivery, partial days
discarded. Integer cents throughout.
"""
from datetime import timedelta

import db
from db import store

COLD_CHAIN_WINDOW = timedelta(hours=48)
COLD_CHAIN_RATE_NUM, COLD_CHAIN_RATE_DEN = 50, 100     # 0.50
FULL_CREDIT_RATE_NUM, FULL_CREDIT_RATE_DEN = 100, 100  # 1.00
PARTIAL_CREDIT_RATE_NUM, PARTIAL_CREDIT_RATE_DEN = 80, 100  # 0.80

COLD_CHAIN_WINDOW_DAYS = 2
FULL_CREDIT_WINDOW_DAYS = 30
PARTIAL_CREDIT_WINDOW_DAYS = 90


def days_since_delivery(order):
    delivered_at = order.get("_delivered_at")
    if delivered_at is None:
        return 0
    delta = db.logical_now() - delivered_at
    return delta.days  # floor of whole days; partial days discarded


def restock_rate(product, days):
    """(numerator, denominator) pair so the rate never becomes a float."""
    if product.get("is_cold_chain"):
        if days <= COLD_CHAIN_WINDOW_DAYS:
            return COLD_CHAIN_RATE_NUM, COLD_CHAIN_RATE_DEN
        return 0, 1
    if days <= FULL_CREDIT_WINDOW_DAYS:
        return FULL_CREDIT_RATE_NUM, FULL_CREDIT_RATE_DEN
    if days <= PARTIAL_CREDIT_WINDOW_DAYS:
        return PARTIAL_CREDIT_RATE_NUM, PARTIAL_CREDIT_RATE_DEN
    return 0, 1


def compute_return_credit(ret):
    order = store.purchase_orders[ret["order_id"]]
    product = store.products[ret["product_id"]]
    per_unit = 0
    for line in store.order_lines.values():
        if line["order_id"] == order["id"] and line["product_id"] == product["id"]:
            per_unit = line.get("unit_price_cents") or 0
            break
    days = days_since_delivery(order)
    num, den = restock_rate(product, days)
    # floor(quantity * per_unit * rate) with the multiplication applied first.
    return (ret["quantity_returned"] * per_unit * num) // den


def apply_return_credit(ret, credit):
    """Apply the credit: order balance floored at zero; the customer's
    receivable reduced by the credit, clamped at zero; a zeroed balance on an
    order not already PAID moves the financial dimension to CREDITED."""
    order = store.purchase_orders[ret["order_id"]]
    order["invoice_balance_cents"] = max(0, order["invoice_balance_cents"] - credit)
    customer = store.trading_partners.get(order["customer_id"])
    if customer is not None:
        customer["open_receivable_cents"] = max(0, customer["open_receivable_cents"] - credit)
        db.touch(customer)
    if order["invoice_balance_cents"] == 0 and order["financial_status"] != "PAID":
        order["financial_status"] = "CREDITED"
    db.touch(order)
