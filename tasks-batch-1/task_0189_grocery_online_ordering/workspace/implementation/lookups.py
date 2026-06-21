"""Cross-aggregate lookups + derived-field recomputation for an Order.

Centralizes how an Order's totals (PRD §2.5 / §3.5 / §3.6 / §3.8) are
recomputed from its lines, substitutions, refunds and the customer balance.
"""
import db
import calculations as calc


def lines_for_order(order_id):
    return [l for l in db.order_lines.values() if l["order_id"] == order_id]


def product_lookup(product_id):
    return db.products.get(product_id)


def accepted_sub_for_line(line_id):
    """The ACCEPTED substitution governing a SUBSTITUTED line, if any."""
    found = None
    for s in db.substitutions.values():
        if s["order_line_id"] == line_id and s["status"] == "ACCEPTED":
            found = s
    return found


def refunds_for_order(order_id):
    return [r for r in db.refunds.values() if r["order_id"] == order_id]


def recompute_estimated_totals(order):
    """estimated_total_cents + estimated_ebt_eligible_cents (PRD §3.5)."""
    lines = lines_for_order(order["id"])
    order["estimated_total_cents"] = calc.estimated_total(lines, order["tip_cents"])
    order["estimated_ebt_eligible_cents"] = calc.estimated_ebt_eligible(lines, product_lookup)


def recompute_final_totals(order):
    """final_total_cents, final_ebt_eligible_cents, requires_age_check
    (PRD §3.5)."""
    lines = lines_for_order(order["id"])
    order["final_total_cents"] = calc.final_total(lines, order["tip_cents"])
    order["final_ebt_eligible_cents"] = calc.final_ebt_eligible(
        lines, product_lookup, accepted_sub_for_line)
    order["requires_age_check"] = calc.requires_age_check(
        lines, product_lookup, accepted_sub_for_line)


def recompute_net_captured(order):
    """net_captured_cents = ebt_charged + card_charged - refunded_total
    (PRD §3.8)."""
    order["net_captured_cents"] = (
        order["ebt_charged_cents"]
        + order["card_charged_cents"]
        - order["refunded_total_cents"]
    )
