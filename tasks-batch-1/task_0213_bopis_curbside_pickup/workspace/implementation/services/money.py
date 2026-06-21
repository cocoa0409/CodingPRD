"""Money calculations (PRD §3.9 / scaffold §1.3).

All amounts are integer cents. Rounding, where invoked, is round-half-up — but
because effective unit prices are already integer cents it is a no-op. The order
of operations is pinned: per-line subtotal first, then sum.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_product(line):
    return db.products.get(line["product_id"])


def authorized_total(order):
    """sum_over_lines(unit_price_cents * qty_ordered). Per-line subtotal then sum."""
    total = 0
    for line in _lines_of(order):
        prod = line_product(line)
        if prod is None:
            continue
        total += prod["unit_price_cents"] * line["qty_ordered"]
    return total


def effective_unit_price(line):
    """Original product price normally; substitute product price for a line that
    carries an ACCEPTED substitution. Keyed on the accepted substitution rather
    than the transient line_status (which flips to HANDED_OVER at pickup)."""
    sub = _accepted_sub_for_line(line)
    if sub is not None:
        sub_prod = db.products.get(sub["substitute_product_id"])
        if sub_prod is not None:
            return sub_prod["unit_price_cents"]
    prod = line_product(line)
    return prod["unit_price_cents"] if prod else 0


def captured_total(order):
    """sum_over_lines( round_half_up(effective_unit_price) * qty_handed_over )."""
    total = 0
    for line in _lines_of(order):
        if line.get("qty_handed_over", 0) > 0:
            unit = round_half_up(effective_unit_price(line))
            total += unit * line["qty_handed_over"]
    return total


def captured_for_event(line, qty):
    unit = round_half_up(effective_unit_price(line))
    return unit * qty


def substitution_price_delta(sub):
    sub_prod = db.products.get(sub["substitute_product_id"])
    line = db.order_lines.get(sub["order_line_id"])
    orig_prod = db.products.get(line["product_id"]) if line else None
    if sub_prod is None or orig_prod is None:
        return 0
    return (sub_prod["unit_price_cents"] - orig_prod["unit_price_cents"]) * sub["substitute_qty"]


# --- helpers ---------------------------------------------------------------

def _lines_of(order):
    return [ln for ln in db.order_lines.values() if ln["order_id"] == order["id"]]


def _accepted_sub_for_line(line):
    for sub in db.substitutions.values():
        if sub["order_line_id"] == line["id"] and sub["decision_status"] == "ACCEPTED":
            return sub
    return None
