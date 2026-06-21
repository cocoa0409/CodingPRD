"""Cascade / state-transition side effects (PRD §3.2, §3.4, §3.5, §3.6).

These helpers carry every link of a cascade to completion within the same
request (PRD §2.5).
"""
from __future__ import annotations

from db import db
from services.common import sort_by_created, touch, audit
from services.calculations import (
    compute_line_tuition,
    reconcile_offering_counts,
    compute_invoice_totals,
)


# ---------------------------------------------------------------------------
# Session cancel — depth-3 cascade (PRD §3.2)
# ---------------------------------------------------------------------------
def cancel_session_cascade(session: dict, actor_role: str) -> None:
    session["status"] = "CANCELLED"

    offerings = [w for w in db.weekly_offerings.values() if w["session_id"] == session["id"]]
    touched_invoices = set()
    for offering in offerings:
        members = [
            e
            for e in db.enrollments.values()
            if e["weekly_offering_id"] == offering["id"]
            and e["status"] in ("CONFIRMED", "WAITLISTED")
        ]
        for e in members:
            e["status"] = "WITHDRAWN"
            e["waitlist_rank"] = None
            touch(e)
            inv_id = e.get("invoice_id")
            if inv_id and inv_id in db.invoices:
                touched_invoices.add(inv_id)
        # link 2: reconcile each affected offering
        reconcile_offering_counts(offering)

    # link 3: re-total each affected DRAFT invoice
    for inv_id in touched_invoices:
        inv = db.invoices.get(inv_id)
        if inv and inv["status"] == "DRAFT":
            compute_invoice_totals(inv)

    touch(session)
    audit("Session", session["id"], "SESSION_CANCELLED", actor_role)


# ---------------------------------------------------------------------------
# Enrollment withdraw — depth-3 cascade w/ waitlist promotion (PRD §3.4)
# ---------------------------------------------------------------------------
def withdraw_enrollment_cascade(enrollment: dict, offering: dict, actor_role: str) -> None:
    was_confirmed = enrollment["status"] == "CONFIRMED"
    withdrawn_invoice_id = enrollment.get("invoice_id")

    enrollment["status"] = "WITHDRAWN"
    enrollment["waitlist_rank"] = None
    # the withdrawn enrollment's line is removed from its invoice (no longer
    # CONFIRMED, so it stops contributing to subtotal); detach the line.
    enrollment["invoice_id"] = None
    enrollment["provisional_tuition_cents"] = 0
    touch(enrollment)

    promoted = None
    if was_confirmed:
        # link 1: free a seat
        reconcile_offering_counts(offering)
        # link 2: promote the head waitlisted enrollment if any
        waitlisted = [
            e
            for e in db.enrollments.values()
            if e["weekly_offering_id"] == offering["id"] and e["status"] == "WAITLISTED"
        ]
        if waitlisted:
            head = sort_by_created(waitlisted)[0]
            promoted = head
            head["status"] = "CONFIRMED"
            head["waitlist_rank"] = None
            head["provisional_tuition_cents"] = compute_line_tuition(head)
            _attach_to_draft_invoice(head)
            reconcile_offering_counts(offering)
    else:
        # waitlisted withdraw: re-rank remaining
        reconcile_offering_counts(offering)

    # link 3: re-total invoices (withdrawn's own invoice, and the promoted one)
    invoices_to_total = set()
    if withdrawn_invoice_id and withdrawn_invoice_id in db.invoices:
        invoices_to_total.add(withdrawn_invoice_id)
    if promoted and promoted.get("invoice_id"):
        invoices_to_total.add(promoted["invoice_id"])
    for inv_id in invoices_to_total:
        inv = db.invoices.get(inv_id)
        if inv and inv["status"] == "DRAFT":
            compute_invoice_totals(inv)

    audit("Enrollment", enrollment["id"], "ENROLLMENT_WITHDRAWN", actor_role)


# ---------------------------------------------------------------------------
# Invoice attach (PRD §3.4): the guardian's DRAFT invoice for the offering's
# billing period; created if absent.
# ---------------------------------------------------------------------------
def _attach_to_draft_invoice(enrollment: dict) -> dict:
    from services.common import make_record

    offering = db.weekly_offerings[enrollment["weekly_offering_id"]]
    billing_period = offering["week_start"]
    child = db.children[enrollment["child_id"]]
    guardian_id = child["guardian_id"]

    # find an existing DRAFT invoice for (guardian, period)
    invoice = None
    for inv in db.invoices.values():
        if (
            inv["guardian_id"] == guardian_id
            and inv["billing_period"] == billing_period
            and inv["status"] == "DRAFT"
        ):
            invoice = inv
            break
    if invoice is None:
        invoice = make_record(
            {
                "guardian_id": guardian_id,
                "billing_period": billing_period,
                "status": "DRAFT",
                "subtotal_cents": 0,
                "sibling_discount_cents": 0,
                "total_due_cents": 0,
                "amount_paid_cents": 0,
            }
        )
        db.invoices[invoice["id"]] = invoice
    enrollment["invoice_id"] = invoice["id"]
    return invoice


# ---------------------------------------------------------------------------
# Scholarship cascades (PRD §3.6)
# ---------------------------------------------------------------------------
def scholarship_reprice_cascade(child_id: str, *, discount_pct=None) -> None:
    """Re-run provisional line price for every CONFIRMED enrollment of this child
    on a DRAFT invoice, then re-total each touched invoice.

    discount_pct=None  -> use the child's current APPROVED discount (approve path)
    discount_pct=0     -> compensating restore (revoke path)
    """
    touched_invoices = set()
    for e in db.enrollments.values():
        if e["child_id"] != child_id or e["status"] != "CONFIRMED":
            continue
        inv_id = e.get("invoice_id")
        inv = db.invoices.get(inv_id) if inv_id else None
        if not inv or inv["status"] != "DRAFT":
            continue
        e["provisional_tuition_cents"] = compute_line_tuition(e, discount_pct=discount_pct)
        touch(e)
        touched_invoices.add(inv_id)
    for inv_id in touched_invoices:
        compute_invoice_totals(db.invoices[inv_id])
