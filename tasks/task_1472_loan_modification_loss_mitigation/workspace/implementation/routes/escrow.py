from flask import Blueprint, request

import store
from auth import ALL_ROLES, NON_BORROWER_ROLES, authenticate, authorize
from errors import (
    ERR_ANALYSIS_NOT_DRAFT,
    ERR_ANALYSIS_VOID_BLOCKED,
    ERR_ESCROW_ANALYSIS_NOT_FOUND,
    ERR_ESCROW_YEAR_OVERLAP,
    ERR_INVALID_COMP_MONTHS,
    ERR_LOAN_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from services import (
    ANALYSIS_TYPES,
    analysis_out,
    create_escrow_analysis,
    escrow_window_overlaps,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    req_enum,
    req_int,
    req_str,
    success_object,
    valid_year_month,
)

bp = Blueprint("escrow", __name__)


@bp.route("/loans/<rid>/escrow-analyses", methods=["POST"])
def create_analysis(rid):
    _, role = authenticate()
    authorize(role, ["ServicingOps"])
    body = body_json()
    analysis_type = req_enum(body, "analysis_type", ANALYSIS_TYPES)
    comp_year_start_month = req_str(body, "comp_year_start_month")
    if not valid_year_month(comp_year_start_month):
        raise_err(ERR_VALIDATION, "comp_year_start_month must be YYYY-MM")
    comp_year_months = req_int(body, "comp_year_months")
    disbursements = req_int(body, "projected_annual_disbursements_cents")

    loan = get_or_404(store.loans, rid, ERR_LOAN_NOT_FOUND, "Loan")

    # structural (priority 10): window overlap, then computation-month bounds
    if escrow_window_overlaps(loan["id"], comp_year_start_month, comp_year_months):
        raise_err(ERR_ESCROW_YEAR_OVERLAP,
                  "Computation window overlaps an existing analysis for this loan")
    if analysis_type == "STANDARD_ANNUAL":
        if comp_year_months != 12:
            raise_err(ERR_INVALID_COMP_MONTHS,
                      "STANDARD_ANNUAL requires comp_year_months == 12")
    else:
        if not (1 <= comp_year_months <= 12):
            raise_err(ERR_INVALID_COMP_MONTHS,
                      "POST_MODIFICATION requires 1 <= comp_year_months <= 12")

    rec = create_escrow_analysis(loan, analysis_type, comp_year_start_month,
                                 comp_year_months, disbursements)
    return success_object(analysis_out(rec), 201)


@bp.route("/escrow-analyses/<rid>", methods=["GET"])
def get_analysis(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.analyses, rid, ERR_ESCROW_ANALYSIS_NOT_FOUND, "EscrowAnalysis")
    return success_object(analysis_out(rec))


@bp.route("/escrow-analyses", methods=["GET"])
def list_analyses():
    _, role = authenticate()
    authorize(role, NON_BORROWER_ROLES)
    records = list(store.analyses.values())
    loan_id = request.args.get("loan_id")
    modification_id = request.args.get("modification_id")
    if loan_id is not None:
        records = [a for a in records if a["loan_id"] == loan_id]
    if modification_id is not None:
        records = [a for a in records if a.get("modification_id") == modification_id]
    return list_response(records, analysis_out)


@bp.route("/loans/<rid>/escrow-analyses", methods=["GET"])
def list_loan_analyses(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    loan = get_or_404(store.loans, rid, ERR_LOAN_NOT_FOUND, "Loan")
    records = [a for a in store.analyses.values() if a["loan_id"] == loan["id"]]
    return list_response(records, analysis_out)


@bp.route("/escrow-analyses/<rid>/apply", methods=["POST"])
def apply_analysis(rid):
    _, role = authenticate()
    authorize(role, ["ServicingOps"])
    rec = get_or_404(store.analyses, rid, ERR_ESCROW_ANALYSIS_NOT_FOUND, "EscrowAnalysis")
    if rec["status"] != "DRAFT":
        raise_err(ERR_ANALYSIS_NOT_DRAFT,
                  "Analysis in %s cannot be applied" % rec["status"])
    loan = store.loans[rec["loan_id"]]
    rec["_prev_escrow_monthly_cents"] = loan["escrow_monthly_cents"]
    loan["escrow_monthly_cents"] = rec["new_monthly_escrow_cents"]
    if rec["refund_cents"] > 0:
        loan["escrow_balance_cents"] -= rec["refund_cents"]
    bump(loan)
    rec["status"] = "APPLIED"
    bump(rec)
    return success_object(analysis_out(rec))


@bp.route("/escrow-analyses/<rid>/void", methods=["POST"])
def void_analysis(rid):
    _, role = authenticate()
    authorize(role, ["ServicingOps"])
    rec = get_or_404(store.analyses, rid, ERR_ESCROW_ANALYSIS_NOT_FOUND, "EscrowAnalysis")
    if rec["status"] != "APPLIED":
        raise_err(ERR_ANALYSIS_NOT_DRAFT,
                  "Analysis in %s cannot be voided" % rec["status"])

    # blocked when a later APPLIED (non-VOIDED) analysis exists for the loan
    for other in store.analyses.values():
        if (other["loan_id"] == rec["loan_id"] and other["id"] != rec["id"]
                and other["status"] == "APPLIED"
                and (other["created_at"], other["_seq"]) > (rec["created_at"], rec["_seq"])):
            raise_err(ERR_ANALYSIS_VOID_BLOCKED,
                      "A later applied analysis exists for this loan")

    loan = store.loans[rec["loan_id"]]
    if "_prev_escrow_monthly_cents" in rec:
        loan["escrow_monthly_cents"] = rec["_prev_escrow_monthly_cents"]
    if rec["refund_cents"] > 0:
        loan["escrow_balance_cents"] += rec["refund_cents"]
    bump(loan)
    rec["status"] = "VOIDED"
    bump(rec)
    return success_object(analysis_out(rec))
