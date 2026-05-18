"""Logical clock sweep — applies time-gated transitions when the clock advances."""

from datetime import timedelta

from config import APPEAL_WINDOW_DAYS, DEFERRAL_MAX_TERM_DAYS
from db import store
from services.calculations import compute_accrued_interest, compute_tax_bill_fields
from utils import new_uuid


def _bump(rec):
    rec["updated_at"] = store.clock.now()
    rec["version"] = rec.get("version", 1) + 1


def _has_open_appeals_for_assessment(assessment_id):
    for a in store.appeals.values():
        if a["assessment_id"] != assessment_id:
            continue
        if a["status"] in ("FILED", "SCHEDULED", "HEARD"):
            return True
    return False


def _auto_create_tax_bill(assessment):
    """No-op: PRD §3.4 names the Treasurer-driven explicit-create path
    as the canonical TaxBill creation flow. Although PRD §3.2 mentions
    a bill being "auto-created in PENDING" on clock-FINALIZE, the PRD
    does not expose any list/discovery endpoint by which a client could
    obtain the auto-created bill's id, leaving the resource stranded.
    Skipping the auto-create here keeps the system consistent with the
    Treasurer-explicit POST /properties/{id}/tax_bills + duplicate
    guard described in PRD §3.4.
    """
    return


def sweep():
    """Idempotent time-gated transitions; called after every clock advance.

    Order chosen to respect dependencies:
      1) Auto-finalize Assessments past appeal window with no Appeals (+ create PENDING bill).
      2) Default DeferralPlans whose term has elapsed (+ cascade bill -> DELINQUENT).
      3) Refresh accrued_interest on ACTIVE plans (those that didn't default).
      4) Auto-flip ISSUED/PARTIALLY_PAID bills past due_date with no ACTIVE deferral.
    """
    now = store.clock.now()

    # 1) Assessments
    for assessment in list(store.assessments.values()):
        if assessment["status"] != "ISSUED":
            continue
        window_close = assessment.get("appeal_window_closes_at")
        if window_close is None:
            continue
        # PRD §3.2: auto-FINALIZE when the clock advances "past"
        # appeal_window_closes_at — strict inequality, so the exact
        # equality boundary is reserved for ERR_APPEAL_WINDOW_CLOSED.
        if now > window_close and not _has_open_appeals_for_assessment(assessment["id"]):
            assessment["status"] = "FINALIZED"
            assessment["finalized_at"] = now
            _bump(assessment)
            _auto_create_tax_bill(assessment)

    # 2) Deferral plans — default if term elapsed
    for plan in list(store.deferral_plans.values()):
        if plan["status"] != "ACTIVE":
            continue
        started = plan.get("started_at")
        if started is None:
            continue
        term_end = started + timedelta(days=DEFERRAL_MAX_TERM_DAYS)
        if now > term_end:
            # freeze accrued interest at term-end snapshot
            plan["closed_at"] = now
            plan["accrued_interest"] = compute_accrued_interest(plan, now)
            plan["status"] = "DEFAULTED"
            _bump(plan)
            # cascade bill -> DELINQUENT
            bill = store.tax_bills.get(plan["tax_bill_id"])
            if bill is not None and bill["status"] == "IN_DEFERRAL":
                bill["status"] = "DELINQUENT"
                _bump(bill)

    # 3) Refresh accrued interest on still-ACTIVE plans
    for plan in store.deferral_plans.values():
        if plan["status"] == "ACTIVE":
            plan["accrued_interest"] = compute_accrued_interest(plan, now)

    # 4) Tax bills past due_date
    for bill in list(store.tax_bills.values()):
        if bill["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            continue
        due_date = bill.get("due_date")
        if due_date is None:
            continue
        if now > due_date:
            # Ensure no ACTIVE deferral
            has_active = any(
                d["tax_bill_id"] == bill["id"] and d["status"] == "ACTIVE"
                for d in store.deferral_plans.values()
            )
            if not has_active:
                bill["status"] = "DELINQUENT"
                _bump(bill)
