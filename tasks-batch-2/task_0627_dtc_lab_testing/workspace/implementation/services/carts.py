"""Cart estimate recompute (PRD §3.2, §3.3)."""
import db
from services.pricing import price_lines


def cart_lines_for(cart_id):
    rows = [cl for cl in db.all_rows("cart_lines") if cl["cart_id"] == cart_id]
    return db.sorted_rows(rows)


def recompute_cart(cart):
    """Recompute line_count, subtotal_cents, estimated_* over all OPEN-cart lines.

    Forward-looking variant: every line is included regardless of fulfillment.
    """
    lines = cart_lines_for(cart["id"])
    patient = db.get("patients", cart["patient_id"])
    hsa_balance = patient["hsa_balance_cents"] if patient else 0

    priced = price_lines(lines, cart["fund_source"], hsa_balance)
    cart["line_count"] = len(lines)
    cart["subtotal_cents"] = priced["subtotal_cents"]
    cart["estimated_total_cents"] = priced["total_cents"]
    cart["estimated_hsa_applied_cents"] = priced["hsa_applied_cents"]
    cart["estimated_patient_due_cents"] = priced["patient_due_cents"]
    return cart
