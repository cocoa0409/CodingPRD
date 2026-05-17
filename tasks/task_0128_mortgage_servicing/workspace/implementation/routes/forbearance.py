"""Forbearance plan routes."""
from __future__ import annotations

from flask import Blueprint, request

from db import store
from errors import (
    err_forbearance_date,
    err_forbearance_plan_exists,
    err_hardship_missing,
    err_invalid_state,
    err_resource_not_found,
)
from middleware import require_auth
from response import list_success, success
from services.loan_engine import (
    bump,
    loan_has_active_forbearance,
    recompute_delinquency_days,
    recompute_posture,
)
from services.serializers import forbearance_view
from utils import add_months, midnight_utc, new_uuid, parse_iso

from routes._helpers import (
    enforce_borrower_owns_loan,
    get_int,
    get_json,
    get_loan_or_404,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("forbearance", __name__)

_ALLOWED_METHODS = {"LUMP_SUM", "REPAYMENT_PLAN_12M", "DEFERRAL"}


@bp.post("/loans/<lid>/forbearance-plans")
@require_auth(["LossMitigationUnderwriter"])
def create_forbearance(lid):
    loan = get_loan_or_404(lid)
    borrower = store.borrowers.get(loan["borrower_id"])
    if borrower is None or borrower.get("hardship_attested_at") is None:
        raise err_hardship_missing()
    # PRD §3.4 lists the named errors in textual order: hardship, then
    # plan-exists (ERR_FORBEARANCE_PLAN_EXISTS), then posture. When a
    # second ACTIVE plan is attempted, the loan is necessarily in
    # FORBEARANCE posture (caused by the existing plan); raising the
    # specific named error is the more useful signal and matches the
    # PRD §3 textual ordering.
    if loan_has_active_forbearance(lid):
        raise err_forbearance_plan_exists()
    if loan["posture"] not in ("CURRENT", "DELINQUENT"):
        raise err_invalid_state("Forbearance only valid from CURRENT or DELINQUENT.")
    body = get_json()
    sd_raw = body.get("start_date")
    if sd_raw is None:
        raise err_forbearance_date("start_date required")
    try:
        start_date = parse_iso(sd_raw)
    except Exception:
        raise err_forbearance_date("Invalid start_date")
    months = get_int(body, "months")
    if months is None or months < 1 or months > 12:
        raise err_invalid_state("months must be in [1, 12]")
    repayment_method = body.get("repayment_method")
    if repayment_method not in _ALLOWED_METHODS:
        raise err_invalid_state("Invalid repayment_method.")
    if midnight_utc(start_date) > midnight_utc(loan["next_due_date"]):
        raise err_forbearance_date()

    now = store.now()
    end_date = add_months(start_date, months)
    total_paused = months * (loan["scheduled_payment_cents"] + loan["monthly_escrow_payment_cents"])

    fid = new_uuid()
    record = {
        "id": fid,
        "loan_id": lid,
        "start_date": start_date,
        "months": months,
        "end_date": end_date,
        "total_paused_cents": total_paused,
        "repayment_method": repayment_method,
        "status": "ACTIVE",
        "cure_balance_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.forbearance_plans[fid] = record
    # Cascade Loan posture.
    loan["posture"] = "FORBEARANCE"
    bump(loan, now)
    return success(forbearance_view(record), 201)


@bp.post("/loans/<lid>/forbearance-plans/<fid>/cancel")
@require_auth(["LossMitigationUnderwriter"])
def cancel_forbearance(lid, fid):
    loan = get_loan_or_404(lid)
    fp = store.forbearance_plans.get(fid)
    if fp is None or fp["loan_id"] != lid:
        raise err_resource_not_found("ForbearancePlan not found under loan.")
    if fp["status"] != "ACTIVE":
        raise err_invalid_state("Only ACTIVE plans can be cancelled.")
    now = store.now()
    if midnight_utc(now) >= midnight_utc(fp["end_date"]):
        raise err_invalid_state("Cannot cancel a plan after its end_date.")
    fp["status"] = "CANCELED"
    bump(fp, now)
    # Loan posture reverts: take it out of FORBEARANCE then recompute.
    if loan["posture"] == "FORBEARANCE":
        loan["posture"] = "DELINQUENT"  # transient; will be corrected below
    recompute_delinquency_days(loan, now)
    recompute_posture(loan, now)
    bump(loan, now)
    return success(forbearance_view(fp), 200)


@bp.get("/loans/<lid>/forbearance-plans")
@require_auth(["Servicer", "LossMitigationUnderwriter", "Borrower"])
def list_forbearance(lid):
    loan = get_loan_or_404(lid)
    enforce_borrower_owns_loan(loan)
    limit, offset = parse_pagination()
    items = [f for f in store.forbearance_plans.values() if f["loan_id"] == lid]
    status = request.args.get("status")
    if status:
        items = [f for f in items if f["status"] == status]
    items = sort_by_created_at(items)
    page = paginate(items, limit, offset)
    return list_success([forbearance_view(f) for f in page], limit, offset, len(items), 200)
