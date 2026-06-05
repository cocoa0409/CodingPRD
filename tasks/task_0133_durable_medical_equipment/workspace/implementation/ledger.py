"""Order-level ledger helpers and cross-entity recompute (PRD 2.7, 3.7, 3.9, 3.11)."""
import db
from calc import RENTAL_CAP_MONTHS


def order_claim_lines(order_id):
    return [cl for cl in db.claim_lines.values() if cl["order_id"] == order_id]


def order_cycles(order_id):
    return [c for c in db.rental_cycles.values() if c["order_id"] == order_id]


def recompute_total_allowed(order):
    """total_allowed_cents = sum of allowed_amount_cents over non-VOID claim lines (PRD 2.7)."""
    total = 0
    for cl in order_claim_lines(order["id"]):
        if cl["status"] != "VOID":
            total += cl["allowed_amount_cents"]
    order["total_allowed_cents"] = total
    return total


def recompute_rental_progress(order, item):
    """rental_months_billed = count of cycles in {BILLED, PAID}; cap_reached for
    CAPPED_RENTAL when >= 13 (PRD 3.7 rental_cap_progress)."""
    count = 0
    for c in order_cycles(order["id"]):
        if c["status"] in ("BILLED", "PAID"):
            count += 1
    order["rental_months_billed"] = count
    order["cap_reached"] = (
        item["billing_category"] == "CAPPED_RENTAL" and count >= RENTAL_CAP_MONTHS
    )
    return count
