"""Aggregate recomputation, cascades, and shared lookup helpers."""

from decimal import Decimal, ROUND_HALF_UP

import db
from db import new_id, next_order, now_iso, touch
from errors import not_found

ACTIVE_DRAW_STATES = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED"}
OVERLAP_BLOCKING_STATES = {"SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "FUNDED"}


def get_or_404(store, rid, what="Resource"):
    rec = store.get(rid)
    if rec is None:
        raise not_found(what)
    return rec


def lines_of_loan(loan_id):
    return [l for l in db.budget_lines.values() if l["loan_id"] == loan_id]


def draws_of_loan(loan_id):
    return [d for d in db.draws.values() if d["loan_id"] == loan_id]


def items_of_draw(draw_id):
    return [i for i in db.draw_line_items.values() if i["draw_id"] == draw_id]


def docs_of_draw(draw_id):
    return [d for d in db.draw_documents.values() if d["draw_id"] == draw_id]


def entries_of_loan(loan_id):
    return sorted(
        (e for e in db.interest_entries.values() if e["loan_id"] == loan_id),
        key=lambda e: e["entry_index"],
    )


def next_entry_index(loan_id):
    return len(entries_of_loan(loan_id)) + 1


def make_entry(loan, entry_type, amount_cents, period_start, period_end,
               days_counted, interest_due, paid_from_reserve, capitalized,
               balance_after):
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "_order": next_order(),
        "loan_id": loan["id"],
        "entry_index": next_entry_index(loan["id"]),
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "days_counted": days_counted,
        "interest_due_cents": interest_due,
        "paid_from_reserve_cents": paid_from_reserve,
        "capitalized_cents": capitalized,
        "reserve_balance_after_cents": balance_after,
    }
    db.interest_entries[e["id"]] = e
    return e


def recompute_loan_money(loan):
    """Recompute total_original / principal / retained / cost percent, and
    latch retainage_fully_released when the retained balance returns to 0
    after having been positive."""
    lines = lines_of_loan(loan["id"])
    loan["total_original_budget_cents"] = sum(l["original_amount_cents"] for l in lines)
    loan["principal_disbursed_cents"] = sum(l["disbursed_cents"] for l in lines)
    loan["retained_cents"] = sum(l["retained_cents"] for l in lines)
    denom = sum(l["revised_amount_cents"] for l in lines)
    numer = sum(l["disbursed_cents"] + l["retained_cents"] for l in lines)
    if denom == 0:
        loan["cost_percent_complete"] = 0.0
    else:
        loan["cost_percent_complete"] = float(
            (Decimal(numer) * 100 / Decimal(denom)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
    if loan["retained_cents"] > 0:
        loan["_retained_positive"] = True
    if loan["retained_cents"] == 0 and loan.get("_retained_positive"):
        loan["retainage_fully_released"] = True


def latest_accepted_inspection(loan_id, draw_id=None):
    cands = [
        i
        for i in db.inspections.values()
        if i["loan_id"] == loan_id
        and i["status"] == "ACCEPTED"
        and (draw_id is None or i["draw_id"] == draw_id)
    ]
    if not cands:
        return None
    return max(
        cands,
        key=lambda i: (i["completed_date"] or "", i["created_at"], i["_order"]),
    )


def recompute_inspection_progress(loan):
    insp = latest_accepted_inspection(loan["id"])
    loan["inspection_percent_complete"] = (
        float(insp["percent_complete_reported"]) if insp else 0.0
    )
    if loan["inspection_percent_complete"] >= loan["retainage_milestone_pct"]:
        loan["milestone_reached"] = True  # latched, never flips back


def has_accepted_100_inspection(loan_id):
    return any(
        i["loan_id"] == loan_id
        and i["status"] == "ACCEPTED"
        and float(i["percent_complete_reported"]) == 100.0
        for i in db.inspections.values()
    )


def cascade_close_budget_lines(loan):
    for line in lines_of_loan(loan["id"]):
        if line["status"] == "ACTIVE":
            line["status"] = "CLOSED"
            touch(line)


def sweep_reserve(loan):
    bal = loan["interest_reserve_balance_cents"]
    if bal > 0:
        make_entry(
            loan, "SWEEP", -bal, None, None, None, None, None, 0, 0
        )
        loan["interest_reserve_swept_cents"] += bal
        loan["interest_reserve_balance_cents"] = 0


def approved_unfunded_for_line(line_id):
    """Sum of approved_cents over this line's items in APPROVED (not yet
    FUNDED) draws."""
    total = 0
    for item in db.draw_line_items.values():
        if item["budget_line_id"] != line_id:
            continue
        draw = db.draws.get(item["draw_id"])
        if draw is not None and draw["status"] == "APPROVED":
            total += item["approved_cents"]
    return total
