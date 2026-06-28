"""Order lifecycle: invoice recompute, fulfillment bubbling, cascades
(PRD §3.4, §3.6, §3.7)."""
import db
from services.pricing import price_lines

TERMINAL_LINE_STATES = {"RESULTED", "REJECTED", "CANCELLED"}


def order_lines_for(order_id):
    rows = [ol for ol in db.all_rows("order_lines") if ol["order_id"] == order_id]
    return db.sorted_rows(rows)


def recompute_invoice(order):
    """Chronological order invoice over RESULTED lines only (PRD §3.6).

    Writes invoiced_total_cents, hsa_applied_cents, patient_due_cents. Does NOT
    debit the HSA balance (that happens only at capture).
    """
    lines = order_lines_for(order["id"])
    billable = [ol for ol in lines if ol["status"] == "RESULTED"]
    patient = db.get("patients", order["patient_id"])
    hsa_balance = patient["hsa_balance_cents"] if patient else 0

    priced = price_lines(billable, order["fund_source"], hsa_balance)
    order["invoiced_total_cents"] = priced["total_cents"]
    order["hsa_applied_cents"] = priced["hsa_applied_cents"]
    order["patient_due_cents"] = priced["patient_due_cents"]


def _bump_fulfillment(order, new_status):
    if order["fulfillment_status"] != new_status:
        order["fulfillment_status"] = new_status


def recompute_fulfillment(order):
    """Derive fulfillment_status from the order's line states (PRD §3.7).

    Never sets CANCELLED here (cancellation is an explicit action). Only advances
    along AWAITING_COLLECTION -> IN_PROCESSING -> PARTIALLY_RESULTED -> COMPLETED.
    """
    if order["fulfillment_status"] == "CANCELLED":
        return
    lines = order_lines_for(order["id"])
    if not lines:
        return
    statuses = [ol["status"] for ol in lines]
    any_resulted = any(s == "RESULTED" for s in statuses)
    all_terminal = all(s in TERMINAL_LINE_STATES for s in statuses)
    any_collected = any(s == "COLLECTED" for s in statuses)

    if all_terminal and any_resulted:
        _bump_fulfillment(order, "COMPLETED")
        return
    if all_terminal and not any_resulted:
        # Every line terminal but none resulted (all rejected/cancelled). The
        # order stays in its current non-completed fulfillment state; only
        # explicit cancellation makes it CANCELLED.
        return
    # Not all terminal yet.
    if any_resulted:
        _bump_fulfillment(order, "PARTIALLY_RESULTED")
    elif any_collected or order["fulfillment_status"] == "IN_PROCESSING":
        _bump_fulfillment(order, "IN_PROCESSING")
    # else stays AWAITING_COLLECTION


def line_terminal_cascade(order, *, recompute=True):
    """After a line reaches a terminal state, recompute invoice + fulfillment."""
    if recompute:
        recompute_invoice(order)
    recompute_fulfillment(order)
    db.touch(order)
