"""LoanAccount endpoints: origination lifecycle + financial summary."""
from flask import Blueprint

from db import STORE, get_clock
from errors import raise_err
from middleware import ALL_ROLES, auth, require_role
from response import ok_list, ok_object
from serialize import list_response, ser_loan
from services.core import (available_credit_cents, budgets_of_loan,
                           collaterals_of_loan, coverage_cents,
                           filings_of_collateral, has_assigned_active_policy,
                           has_perfected_pledged_collateral, notices_of_loan,
                           pending_draw_cents, recompute_borrowing_base,
                           reevaluate_borrower, standard_cascade, stamp_new,
                           touch)
from util import as_dt, as_int, as_pos_int, as_str, body, need, new_id

bp = Blueprint("loans", __name__)


def get_loan_or_404(loan_id):
    loan = STORE.loans.get(loan_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    return loan


@bp.route("/loan-accounts", methods=["POST"])
def create_loan():
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    b = body()
    borrower_id = as_str(need(b, "borrower_id"), "borrower_id")
    requested = as_pos_int(need(b, "requested_commitment_cents"), "requested_commitment_cents")
    rate_bps = as_int(need(b, "rate_bps"), "rate_bps", min_value=0)
    season_year = as_int(need(b, "season_year"), "season_year")
    maturity_date = as_dt(need(b, "maturity_date"), "maturity_date")
    borrower = STORE.borrowers.get(borrower_id)
    if borrower is None:
        raise_err("ERR_NOT_FOUND", "Borrower not found")
    loan = stamp_new({
        "id": new_id(),
        "borrower_id": borrower_id,
        "association_id": borrower["association_id"],
        "requested_commitment_cents": requested,
        "approved_commitment_cents": None,
        "rate_bps": rate_bps,
        "season_year": season_year,
        "maturity_date": maturity_date,
        "status": "DRAFT",
        "payment_posture": "CURRENT",
        "consecutive_delinquent_reviews": 0,
        "outstanding_principal_cents": 0,
        "accrued_interest_cents": 0,
        "last_accrual_date": None,
        "borrowing_base_cents": 0,
    })
    STORE.loans[loan["id"]] = loan
    return ok_object(ser_loan(loan), code=201)


@bp.route("/loan-accounts/<lid>", methods=["GET"])
def get_loan(lid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_loan(get_loan_or_404(lid)))


@bp.route("/loan-accounts", methods=["GET"])
def list_loans():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.loans.values(), ser_loan,
        [("borrower_id", lambda e: e["borrower_id"]),
         ("association_id", lambda e: e["association_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/loan-accounts/<lid>/submit", methods=["POST"])
def submit_loan(lid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    loan = get_loan_or_404(lid)
    if loan["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT loan can be submitted")
    loan["status"] = "SUBMITTED"
    touch(loan)
    return ok_object(ser_loan(loan))


@bp.route("/loan-accounts/<lid>/approve", methods=["POST"])
def approve_loan(lid):
    auth_uid, role = auth()
    require_role(role, ["CreditCommittee"])
    loan = get_loan_or_404(lid)
    b = body()
    approved = as_pos_int(need(b, "approved_commitment_cents"), "approved_commitment_cents")
    if approved > loan["requested_commitment_cents"]:
        raise_err("ERR_INVALID_REQUEST",
                  "approved_commitment_cents must not exceed requested_commitment_cents")
    if loan["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED loan can be approved")
    loan["approved_commitment_cents"] = approved
    loan["status"] = "APPROVED"
    recompute_borrowing_base(loan)  # commitment cap now in force
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_loan(loan))


@bp.route("/loan-accounts/<lid>/activate", methods=["POST"])
def activate_loan(lid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    loan = get_loan_or_404(lid)
    if loan["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED loan can be activated")
    # Gates in PRD order: insurance, then perfection, then maturity, then budget.
    if not has_assigned_active_policy(loan):
        raise_err("ERR_INSURANCE_NOT_ASSIGNED",
                  "No ACTIVE policy ASSIGNED to this loan")
    if not has_perfected_pledged_collateral(loan):
        raise_err("ERR_COLLATERAL_UNPERFECTED",
                  "No PLEDGED collateral with PERFECTED perfection_state")
    if not (get_clock() < loan["maturity_date"]):
        raise_err("ERR_MATURITY_PASSED", "Logical clock is at or after maturity_date")
    if not any(b["status"] == "APPROVED" for b in budgets_of_loan(lid)):
        raise_err("ERR_BUDGET_NOT_APPROVED", "No APPROVED crop budget for this loan")
    loan["status"] = "ACTIVE"
    loan["last_accrual_date"] = get_clock().date()
    touch(loan)
    return ok_object(ser_loan(loan))


@bp.route("/loan-accounts/<lid>/charge_off", methods=["POST"])
def charge_off_loan(lid):
    auth_uid, role = auth()
    require_role(role, ["CreditCommittee"])
    loan = get_loan_or_404(lid)
    if loan["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE loan can be charged off")
    if loan["payment_posture"] != "DEFAULT":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Charge-off requires payment_posture DEFAULT")
    loan["status"] = "CHARGED_OFF"
    touch(loan)
    borrower = STORE.borrowers.get(loan["borrower_id"])
    if borrower is not None:
        borrower["patronage_eligible"] = False
    reevaluate_borrower(loan["borrower_id"])
    return ok_object(ser_loan(loan))


@bp.route("/loan-accounts/<lid>/foreclose", methods=["POST"])
def foreclose_loan(lid):
    auth_uid, role = auth()
    require_role(role, ["CreditCommittee"])
    loan = get_loan_or_404(lid)
    if loan["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE loan can be foreclosed")
    if not any(n["status"] == "ESCALATED" for n in notices_of_loan(lid)):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Foreclosure requires an ESCALATED margin call notice")
    loan["status"] = "FORECLOSED"
    touch(loan)
    # Cascade: release all PLEDGED collateral, terminate their live filings.
    for c in collaterals_of_loan(lid):
        if c["status"] == "PLEDGED":
            c["status"] = "RELEASED"
            touch(c)
            for f in filings_of_collateral(c["id"]):
                if f["status"] in ("FILED", "CONTINUED"):
                    f["status"] = "TERMINATED"
                    touch(f)
    return ok_object(ser_loan(loan))


@bp.route("/loan-accounts/<lid>/financial_summary", methods=["GET"])
def financial_summary(lid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    loan = get_loan_or_404(lid)
    return ok_object({
        "outstanding_principal_cents": loan["outstanding_principal_cents"],
        "accrued_interest_cents": loan["accrued_interest_cents"],
        "borrowing_base_cents": loan["borrowing_base_cents"],
        "pending_draw_cents": pending_draw_cents(loan),
        "available_credit_cents": available_credit_cents(loan),
        "coverage_cents": coverage_cents(loan),
        "payment_posture": loan["payment_posture"],
        "status": loan["status"],
    })
