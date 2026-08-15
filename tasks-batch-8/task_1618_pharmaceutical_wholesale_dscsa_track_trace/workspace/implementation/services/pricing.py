"""Order pricing, invoicing, and chargeback computation (PRD §3.4, §3.7).

All monetary values are integer cents; the pricing, chargeback, and receivable
ledger involve only integer arithmetic (PRD §2.6).
"""
import db
from db import store


def unit_price_for(order, product):
    """340B contract price when the order is a 340B order and the product is
    340B-contracted; the WAC list price otherwise (order_line_pricing)."""
    if order.get("is_340b_order") and product.get("is_340b_contracted"):
        return product["contract_340b_price_cents"]
    return product["wholesale_acquisition_cost_cents"]


def order_lines(order_id):
    return [l for l in store.order_lines.values() if l["order_id"] == order_id]


def price_lines_provisional(order):
    """DRAFT -> CONFIRMED: price every line regardless of line status; the
    provisional extended price uses quantity_requested (nothing allocated)."""
    total = 0
    for line in order_lines(order["id"]):
        product = store.products[line["product_id"]]
        line["unit_price_cents"] = unit_price_for(order, product)
        line["extended_price_cents"] = line["quantity_requested"] * line["unit_price_cents"]
        db.touch(line)
        total += line["extended_price_cents"]
    order["invoice_total_cents"] = total
    order["invoice_balance_cents"] = total
    return total


def reprice_lines_final(order):
    """After allocation: extended price uses quantity_allocated; the invoice
    total/balance are restated and the customer's receivable moves by the delta."""
    total = 0
    for line in order_lines(order["id"]):
        new_ext = (line["quantity_allocated"] or 0) * (line["unit_price_cents"] or 0)
        if new_ext != line.get("extended_price_cents"):
            line["extended_price_cents"] = new_ext
            db.touch(line)
        total += new_ext
    delta = total - order["invoice_total_cents"]
    order["invoice_total_cents"] = total
    order["invoice_balance_cents"] += delta
    if delta:
        customer = store.trading_partners.get(order["customer_id"])
        if customer is not None:
            customer["open_receivable_cents"] += delta
            db.touch(customer)
    return total


def compute_chargeback_amount(order):
    """chargeback_amount: sum over the order's lines that are ALLOCATED or
    PARTIALLY_ALLOCATED and whose product is 340B-contracted of
    (WAC - contract price) * quantity_allocated. Integer cents, no rounding."""
    total = 0
    for line in order_lines(order["id"]):
        if line["line_status"] not in ("ALLOCATED", "PARTIALLY_ALLOCATED"):
            continue
        product = store.products.get(line["product_id"])
        if product is None or not product.get("is_340b_contracted"):
            continue
        delta = product["wholesale_acquisition_cost_cents"] - product["contract_340b_price_cents"]
        total += delta * (line["quantity_allocated"] or 0)
    return total
