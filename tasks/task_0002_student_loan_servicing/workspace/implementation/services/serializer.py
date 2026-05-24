"""Entity → JSON-serializable dict transformations.

We store entities as dicts internally; serializer just returns a copy that's
safe to JSON-encode and includes any derived/computed fields.
"""
from __future__ import annotations

import db
from services import calc


# ---------- Borrower ----------


TERMINAL_LOAN_STATES = {"PAID_OFF", "DEFAULT", "DISCHARGED"}


def loans_for_borrower(borrower_id: str) -> list:
    return [l for l in db.loans.values() if l["borrower_id"] == borrower_id]


def recompute_borrower(borrower_id: str) -> None:
    """Recompute aggregate_outstanding_principal_cents + borrower_status from child loans.

    Bubble-up via cascade per PRD §2.8. Each cascade call refreshes updated_at and
    bumps version on the borrower.
    """
    b = db.borrowers.get(borrower_id)
    if b is None:
        return
    child_loans = loans_for_borrower(borrower_id)

    non_terminal = [l for l in child_loans if l["status"] not in TERMINAL_LOAN_STATES]
    aggregate = sum(l["outstanding_principal_cents"] for l in non_terminal)

    if not child_loans:
        status = "CURRENT"
    elif all(l["status"] in {"PAID_OFF", "DISCHARGED"} for l in child_loans):
        status = "CLEARED"
    elif any(l["status"] == "DEFAULT" for l in child_loans):
        status = "IN_DEFAULT"
    elif any(l["status"] == "DELINQUENT" for l in child_loans):
        status = "AT_RISK"
    else:
        # Every non-terminal loan in {IN_SCHOOL, GRACE, REPAYMENT, DEFERMENT, FORBEARANCE}
        status = "CURRENT"

    changed = (
        b.get("aggregate_outstanding_principal_cents") != aggregate
        or b.get("borrower_status") != status
    )
    if changed:
        b["aggregate_outstanding_principal_cents"] = aggregate
        b["borrower_status"] = status
        b["updated_at"] = db.now_iso()
        b["version"] = b.get("version", 0) + 1


def serialize_borrower(b: dict) -> dict:
    return {
        "id": b["id"],
        "ssn_last4": b["ssn_last4"],
        "full_name": b["full_name"],
        "date_of_birth": b["date_of_birth"],
        "email": b["email"],
        "military_status": b["military_status"],
        "aggregate_outstanding_principal_cents": b["aggregate_outstanding_principal_cents"],
        "borrower_status": b["borrower_status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


# ---------- Loan ----------

SUBSIDY_STATES = {"IN_SCHOOL", "GRACE", "DEFERMENT"}


def compute_subsidy_active(loan: dict) -> bool:
    return loan["loan_type"] == "DIRECT_SUBSIDIZED" and loan["status"] in SUBSIDY_STATES


def serialize_loan(l: dict) -> dict:
    return {
        "id": l["id"],
        "borrower_id": l["borrower_id"],
        "loan_type": l["loan_type"],
        "original_principal_cents": l["original_principal_cents"],
        "outstanding_principal_cents": l["outstanding_principal_cents"],
        "accrued_interest_cents": l["accrued_interest_cents"],
        "interest_rate_bps": l["interest_rate_bps"],
        "disbursement_date": l["disbursement_date"],
        "status": l["status"],
        "subsidy_active": compute_subsidy_active(l),
        "days_delinquent": l["days_delinquent"],
        "capitalized_interest_cents": l["capitalized_interest_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def bump_loan(loan: dict) -> None:
    loan["updated_at"] = db.now_iso()
    loan["version"] = loan.get("version", 0) + 1


# ---------- RepaymentPlan ----------


def serialize_plan(p: dict) -> dict:
    return {
        "id": p["id"],
        "loan_id": p["loan_id"],
        "plan_type": p["plan_type"],
        "agi_cents": p.get("agi_cents"),
        "family_size": p.get("family_size"),
        "state_of_residence": p["state_of_residence"],
        "monthly_payment_cents": p["monthly_payment_cents"],
        "status": p["status"],
        "certification_expires_on": p.get("certification_expires_on"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def bump_plan(plan: dict) -> None:
    plan["updated_at"] = db.now_iso()
    plan["version"] = plan.get("version", 0) + 1


def active_plan_for_loan(loan_id: str):
    for p in db.repayment_plans.values():
        if p["loan_id"] == loan_id and p["status"] == "ACTIVE":
            return p
    return None


# ---------- Payment ----------


def serialize_payment(p: dict) -> dict:
    return {
        "id": p["id"],
        "loan_id": p["loan_id"],
        "amount_cents": p["amount_cents"],
        "posted_on": p["posted_on"],
        "source": p["source"],
        "applied_to_interest_cents": p.get("applied_to_interest_cents", 0),
        "applied_to_principal_cents": p.get("applied_to_principal_cents", 0),
        "applied_to_fees_cents": p.get("applied_to_fees_cents", 0),
        "status": p["status"],
        "recorded_by_user_id": p["recorded_by_user_id"],
        "pslf_qualifying": p.get("pslf_qualifying", False),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def bump_payment(payment: dict) -> None:
    payment["updated_at"] = db.now_iso()
    payment["version"] = payment.get("version", 0) + 1


# ---------- ServicingEvent ----------


def serialize_event(e: dict) -> dict:
    # ServicingEvent has no updated_at/version per PRD §2.4
    return {
        "id": e["id"],
        "loan_id": e["loan_id"],
        "event_type": e["event_type"],
        "effective_on": e["effective_on"],
        "reason_code": e["reason_code"],
        "created_by_user_id": e["created_by_user_id"],
        "created_at": e["created_at"],
    }


# ---------- EmploymentCertification ----------


def compute_pslf_qualifying_employer(cert: dict) -> bool:
    return (
        cert["status"] == "APPROVED"
        and cert["employer_type"]
        in {
            "GOVERNMENT_FEDERAL",
            "GOVERNMENT_STATE_LOCAL_TRIBAL",
            "NONPROFIT_501C3",
            "OTHER_NONPROFIT_QUALIFYING",
        }
        and float(cert["weekly_hours"]) >= 30
    )


def serialize_cert(c: dict) -> dict:
    return {
        "id": c["id"],
        "borrower_id": c["borrower_id"],
        "employer_ein": c["employer_ein"],
        "employer_type": c["employer_type"],
        "period_start_on": c["period_start_on"],
        "period_end_on": c["period_end_on"],
        "weekly_hours": c["weekly_hours"],
        "status": c["status"],
        "pslf_qualifying_employer": compute_pslf_qualifying_employer(c),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def bump_cert(cert: dict) -> None:
    cert["updated_at"] = db.now_iso()
    cert["version"] = cert.get("version", 0) + 1


# ---------- PSLFTracker ----------


def serialize_tracker(t: dict) -> dict:
    return {
        "id": t["id"],
        "borrower_id": t["borrower_id"],
        "qualifying_payment_count": t["qualifying_payment_count"],
        "required_payment_count": t["required_payment_count"],
        "status": t["status"],
        "last_recount_on": t["last_recount_on"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def bump_tracker(tracker: dict) -> None:
    tracker["updated_at"] = db.now_iso()
    tracker["version"] = tracker.get("version", 0) + 1


def tracker_for_borrower(borrower_id: str):
    for t in db.pslf_trackers.values():
        if t["borrower_id"] == borrower_id:
            return t
    return None


# ---------- DischargeApplication ----------


def serialize_application(a: dict) -> dict:
    return {
        "id": a["id"],
        "borrower_id": a["borrower_id"],
        "discharge_type": a["discharge_type"],
        "va_certification_doc_id": a.get("va_certification_doc_id"),
        "filed_on": a["filed_on"],
        "status": a["status"],
        "approved_by_user_id": a.get("approved_by_user_id"),
        "total_discharged_principal_cents": a.get("total_discharged_principal_cents"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def bump_application(app: dict) -> None:
    app["updated_at"] = db.now_iso()
    app["version"] = app.get("version", 0) + 1


# ---------- DelinquencyRecord ----------


def serialize_delinquency(d: dict) -> dict:
    return {
        "id": d["id"],
        "loan_id": d["loan_id"],
        "opened_on": d["opened_on"],
        "closed_on": d.get("closed_on"),
        "cumulative_days": d["cumulative_days"],
        "outcome": d["outcome"],
        "created_at": d["created_at"],
    }


def open_delinquency_for_loan(loan_id: str):
    for d in db.delinquency_records.values():
        if d["loan_id"] == loan_id and d["outcome"] == "OPEN":
            return d
    return None
