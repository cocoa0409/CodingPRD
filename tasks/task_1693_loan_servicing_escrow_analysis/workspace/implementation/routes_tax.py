"""Tax monitoring records."""

from datetime import timedelta

from flask import Blueprint, request

from auth import any_role, require_roles
from domain import account_of_loan, compute_penalty
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    not_found,
)
from routes_core import get_loan_or_404
from serializers import tax_record_out
from store import store
from util import bump, fmt_date, new_record, ok, ok_list, parse_date, today
from validate import body, fk_exists, opt_int, req_date, req_enum, req_int, req_str

bp = Blueprint("tax", __name__)

PENALTY_METHODS = ("SIMPLE", "COMPOUND")
TERMINAL = ("PAID_CURRENT", "PAID_DELINQUENT")
NON_TERMINAL = ("MONITORING", "DUE_SOON", "DELINQUENT", "PENALTY_ACCRUING",
                "REDEMPTION_RISK")


def get_tax_record_or_404(tid):
    r = store.tax_records.get(tid)
    if r is None:
        raise not_found("TaxMonitoringRecord not found")
    return r


@bp.post("/servicing/loans/<lid>/tax-monitoring-records")
def create_tax_record(lid):
    require_roles("EscrowAnalyst")
    get_loan_or_404(lid)
    data = body()
    parcel = req_str(data, "parcel_number")
    tax_year = req_int(data, "tax_year")
    seq = req_int(data, "installment_sequence")
    amount_due = req_int(data, "amount_due_cents")
    due = req_date(data, "due_date")
    rate = req_int(data, "monthly_penalty_rate_bps", minimum=0)
    method = req_enum(data, "penalty_method", PENALTY_METHODS)
    grace = opt_int(data, "grace_period_days", 0, minimum=0)
    for r in store.tax_records.values():
        if (r["loan_id"] == lid and r["parcel_number"] == parcel
                and r["tax_year"] == tax_year
                and r["installment_sequence"] == seq
                and r["status"] in NON_TERMINAL):
            raise ApiError("ERR_DUPLICATE_TAX_RECORD", 409,
                           "A non-terminal record with this parcel/year/sequence exists")
    if amount_due <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "amount_due_cents must be positive")
    rec = new_record({
        "loan_id": lid,
        "parcel_number": parcel,
        "tax_year": tax_year,
        "installment_sequence": seq,
        "amount_due_cents": amount_due,
        "due_date": due,
        "grace_period_days": grace,
        "monthly_penalty_rate_bps": rate,
        "penalty_method": method,
        "status": "MONITORING",
        "delinquent_since": None,
        "accrued_penalty_cents": 0,
        "paid_via_disbursement_id": None,
    })
    store.tax_records[rec["id"]] = rec
    return ok(tax_record_out(rec), 201)


@bp.get("/servicing/loans/<lid>/tax-monitoring-records")
def list_tax_records(lid):
    any_role()
    get_loan_or_404(lid)
    rows = [r for r in sorted(store.tax_records.values(), key=lambda x: x["_seq"])
            if r["loan_id"] == lid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([tax_record_out(r) for r in rows])


@bp.get("/servicing/tax-monitoring-records/<tid>")
def get_tax_record(tid):
    any_role()
    return ok(tax_record_out(get_tax_record_or_404(tid)))


@bp.post("/servicing/tax-monitoring-records/<tid>/mark-paid")
def mark_paid(tid):
    require_roles("EscrowAnalyst")
    rec = get_tax_record_or_404(tid)
    data = body()
    disb = fk_exists(store.disbursements, data.get("disbursement_id"), "disbursement_id")
    if disb is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "disbursement_id is required")
    if rec["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Record is terminal")
    if rec["status"] not in NON_TERMINAL:
        raise ApiError(ERR_INVALID_STATE, 409, "Record cannot be marked paid")
    now_date = today()
    grace_end = parse_date(rec["due_date"]) + timedelta(days=rec["grace_period_days"])
    paid_current_states = ("MONITORING", "DUE_SOON")
    if rec["status"] in paid_current_states and now_date > grace_end:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Payment after grace period cannot land PAID_CURRENT from this state")
    # Disbursement must be RELEASED/CLEARED, same loan, and cover the bill
    if disb["status"] not in ("RELEASED", "CLEARED"):
        raise ApiError(ERR_INVALID_AMOUNT, 422,
                       "Disbursement must be RELEASED or CLEARED")
    account = store.accounts.get(disb["escrow_account_id"])
    if account is None or account["loan_id"] != rec["loan_id"]:
        raise ApiError(ERR_INVALID_AMOUNT, 422,
                       "Disbursement belongs to a different loan")
    if disb["amount_cents"] < rec["amount_due_cents"]:
        raise ApiError(ERR_INVALID_AMOUNT, 422,
                       "Disbursement amount is below amount_due_cents")
    if rec["status"] in paid_current_states:
        rec["status"] = "PAID_CURRENT"
        # penalty frozen at current value (0)
    else:
        rec["accrued_penalty_cents"] = compute_penalty(rec, now_date)
        rec["status"] = "PAID_DELINQUENT"
    rec["paid_via_disbursement_id"] = disb["id"]
    bump(rec)
    return ok(tax_record_out(rec))
