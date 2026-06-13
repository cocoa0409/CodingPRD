"""Quote (ESTIMATE) and final (FINAL) total computation (PRD §3.4–§3.6, §3.9).

The ESTIMATE prices on ordered quantities (line_qty) at confirm; the FINAL
re-prices the blank subtotal on consumed units at invoice, carrying decoration
and setup over unchanged and re-using the is_rush captured at confirm.
"""
from services import pricing
from services.lookups import (
    lines_of_order,
    proofs_of_order,
    get_garment_style,
    get_decoration_method,
)


def _approved_proof(order_id):
    for p in proofs_of_order(order_id):
        if p["status"] == "APPROVED":
            return p
    return None


def _reorder_waiver_applies(order):
    """True when the order is a reorder whose APPROVED proof art_hash matches the
    referenced order's approved proof art_hash (PRD §3.6)."""
    from db import store
    ref_id = order.get("reorder_of_order_id")
    if not ref_id:
        return False
    ref_order = store.orders.get(ref_id)
    if ref_order is None:
        return False
    own = _approved_proof(order["id"])
    ref = _approved_proof(ref_id)
    if own is None or ref is None:
        return False
    return own["art_hash"] == ref["art_hash"]


def compute_subtotals(order):
    """Compute the four subtotals + grand total for the ESTIMATE (PRD §3.4).

    Returns a dict of the five money fields. blank_subtotal here is the
    reserved/ordered-quantity variant (ESTIMATE).
    """
    lines = lines_of_order(order["id"])
    waive_setup = _reorder_waiver_applies(order)

    blank_subtotal = 0
    decoration_subtotal = 0
    setup_subtotal = 0
    for line in lines:
        style = get_garment_style(line["garment_style_id"])
        method = get_decoration_method(line["decoration_method_id"])
        blank_subtotal += style["blank_cost_cents"] * line["line_qty"]
        # Per-line rounding pinned: per_unit_line * line_qty, then summed.
        decoration_subtotal += pricing.line_decoration_cost(method, line)
        line_setup = 0 if waive_setup else pricing.line_setup_cost(method, line)
        setup_subtotal += line_setup

    rush = order.get("is_rush", False)
    # rush_surcharge_pct read from the shop at compute time.
    from db import store
    shop = store.shops[order["shop_id"]]
    rush_charge = pricing.rush_surcharge(decoration_subtotal, shop["rush_surcharge_pct"], rush)
    grand_total = blank_subtotal + setup_subtotal + decoration_subtotal + rush_charge
    return {
        "blank_subtotal_cents": blank_subtotal,
        "setup_subtotal_cents": setup_subtotal,
        "decoration_subtotal_cents": decoration_subtotal,
        "rush_surcharge_cents": rush_charge,
        "grand_total_cents": grand_total,
    }


def final_total(order, consumed_blank_subtotal):
    """FINAL grand total = consumed blank subtotal + setup + decoration + rush.

    Decoration and setup are carried over unchanged from the ESTIMATE; rush is
    re-evaluated against the SAME is_rush captured at confirm (PRD §3.9).
    """
    from db import store
    quote = next((q for q in store.quotes.values() if q["order_id"] == order["id"]), None)
    setup_subtotal = quote["setup_subtotal_cents"]
    decoration_subtotal = quote["decoration_subtotal_cents"]
    shop = store.shops[order["shop_id"]]
    rush_charge = pricing.rush_surcharge(
        decoration_subtotal, shop["rush_surcharge_pct"], order.get("is_rush", False)
    )
    return consumed_blank_subtotal + setup_subtotal + decoration_subtotal + rush_charge
