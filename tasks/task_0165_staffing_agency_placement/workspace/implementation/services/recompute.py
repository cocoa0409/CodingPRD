"""Cross-aggregate recomputation and shared cascade side effects.

These helpers implement the derived-field reconciliation and cascading state
changes described in PRD 2.9, 2.10, 3.4, 3.5, and 3.8. Every recompute of a
read-only field on an existing resource counts as a mutation (PRD 2.4): it
refreshes updated_at and bumps version.
"""

import db
from services import calc
from services.common import touch


# --- Client exposure / balance (PRD 2.9) ---

def recompute_open_exposure(client_id):
    """open_exposure_cents = sum of projected_weekly_bill_cents over the
    client's placements whose assignment_status == ACTIVE. Mutates the client."""
    client = db.clients.get(client_id)
    if client is None:
        return
    total = 0
    for p in db.placements.values():
        if p["client_id"] == client_id and p["assignment_status"] == "ACTIVE":
            total += p["projected_weekly_bill_cents"]
    client["open_exposure_cents"] = total
    touch(client)


def recompute_outstanding_balance(client_id):
    """outstanding_balance_cents = sum of total_cents over the client's
    invoices whose status == ISSUED. Mutates the client."""
    client = db.clients.get(client_id)
    if client is None:
        return
    total = 0
    for inv in db.invoices.values():
        if inv["client_id"] == client_id and inv["status"] == "ISSUED":
            total += inv["total_cents"]
    client["outstanding_balance_cents"] = total
    touch(client)


# --- Candidate status (PRD 3.4 / 3.5) ---

def candidate_has_active_placement(candidate_id):
    for p in db.placements.values():
        if p["candidate_id"] == candidate_id and p["assignment_status"] == "ACTIVE":
            return True
    return False


def maybe_release_candidate(candidate_id):
    """If the candidate has no remaining ACTIVE placements and is currently
    ON_ASSIGNMENT, return them to AVAILABLE (PRD 3.5)."""
    cand = db.candidates.get(candidate_id)
    if cand is None:
        return
    if cand["status"] == "ON_ASSIGNMENT" and not candidate_has_active_placement(candidate_id):
        cand["status"] = "AVAILABLE"
        touch(cand)


# --- JobOrder filled_count (PRD 3.4 / 3.5) ---
#
# filled_count is an explicit seat counter, not a live re-count: PRD 3.4 says
# it is "increased by one" when a placement is created, and PRD 3.5 says it is
# "decreased by one" when an ACTIVE assignment ends. A placement is created
# PENDING_START (occupying its seat immediately) and only releases the seat
# when its assignment ends, so filled_count tracks the count of this order's
# placements that have been created and not yet ENDED. Starting a placement
# (PENDING_START -> ACTIVE) does not change filled_count. The endpoints mutate
# jo["filled_count"] directly (+1 on create, -1 on end); there is no recompute
# from a live ACTIVE re-count, which would diverge from the prose.


def cascade_reject_open_submissions(job_order_id, reason):
    """Sweep every still-open submission on the order to REJECTED with the
    given rejection_reason. Open states: SUBMITTED, CLIENT_REVIEW,
    INTERVIEWING, OFFER_EXTENDED (PRD 3.2 / 3.4)."""
    open_states = {"SUBMITTED", "CLIENT_REVIEW", "INTERVIEWING", "OFFER_EXTENDED"}
    for sub in db.submissions.values():
        if sub["job_order_id"] == job_order_id and sub["status"] in open_states:
            sub["status"] = "REJECTED"
            sub["rejection_reason"] = reason
            touch(sub)


# --- Invoice totals (PRD 3.8) ---

def recompute_invoice_totals(invoice):
    """Recompute subtotal/discount/fee/total from the invoice's line items and
    mutate the invoice (PRD 3.8 step order)."""
    inv_id = invoice["id"]
    lines = [li for li in db.invoice_line_items.values() if li["invoice_id"] == inv_id]
    # Order by creation for determinism of the sum (sum is order-independent
    # for integers, but keep a stable order).
    lines.sort(key=lambda li: (li["created_at"], li["id"]))
    line_totals = [li["line_total_cents"] for li in lines]
    subtotal, discount, fee, total = calc.invoice_total(line_totals)
    invoice["subtotal_cents"] = subtotal
    invoice["volume_discount_cents"] = discount
    invoice["processing_fee_cents"] = fee
    invoice["total_cents"] = total
    touch(invoice)


# --- Placement actual margin (PRD 3.6) ---

def recompute_actual_margin(placement):
    """actual_margin_cents = sum of margin_cents over this placement's
    timesheets in status APPROVED or INVOICED, accumulated in week_start ASC
    then created_at ASC order. Mutates the placement."""
    pl_id = placement["id"]
    rows = [
        ts for ts in db.timesheets.values()
        if ts["placement_id"] == pl_id and ts["status"] in ("APPROVED", "INVOICED")
    ]
    rows.sort(key=lambda ts: (ts["week_start"], ts["created_at"]))
    total = 0
    for ts in rows:
        total += ts["margin_cents"]
    placement["actual_margin_cents"] = total
    touch(placement)
