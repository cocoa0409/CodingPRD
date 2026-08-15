"""ForeclosureCase routes: intake, list, read, computed summary."""
from flask import Blueprint, request

import db
from db import stamp_new
from errors import err_invalid_request, err_not_found
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services.domain import (get_case, view, check_beneficiary_owns_case,
                             case_summary)
from services.validate import (get_body, check_unknown, req_string, req_int,
                               req_number, req_enum, opt_bool, req_date)
from util import format_date

bp = Blueprint("cases", __name__)

DISTRIBUTION_METHODS = ("STATUTORY_PRIORITY", "PRO_RATA")

CASE_CREATE_FIELDS = {
    "beneficiary_id", "loan_reference", "borrower_name", "property_address",
    "county_code", "unpaid_principal_balance_cents", "monthly_payment_cents",
    "months_in_arrears", "late_fee_per_month_cents", "note_rate_pct",
    "last_interest_paid_date", "distribution_method", "prepayment_penalty_applies",
}


@bp.route("/api/foreclosure-cases", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def create_case(user_id, role):
    body = get_body()
    check_unknown(body, CASE_CREATE_FIELDS)
    beneficiary_id = req_string(body, "beneficiary_id")
    ben = db.beneficiaries.get(beneficiary_id)
    if ben is None:
        raise err_not_found("Beneficiary not found: " + str(beneficiary_id))
    loan_reference = req_string(body, "loan_reference")
    if any(c["loan_reference"] == loan_reference for c in db.foreclosure_cases.values()):
        raise err_invalid_request("loan_reference must be unique across all cases")
    borrower_name = req_string(body, "borrower_name")
    property_address = req_string(body, "property_address")
    county_code = req_string(body, "county_code")
    upb = req_int(body, "unpaid_principal_balance_cents", minimum=1)
    monthly = req_int(body, "monthly_payment_cents", minimum=1)
    months = req_int(body, "months_in_arrears", minimum=1)
    late_fee = req_int(body, "late_fee_per_month_cents", minimum=0)
    rate = req_number(body, "note_rate_pct")
    lipd = req_date(body, "last_interest_paid_date")
    method = req_enum(body, "distribution_method", DISTRIBUTION_METHODS)
    penalty = opt_bool(body, "prepayment_penalty_applies", default=False)
    case = {
        "beneficiary_id": beneficiary_id,
        "loan_reference": loan_reference,
        "borrower_name": borrower_name,
        "property_address": property_address,
        "county_code": county_code,
        "unpaid_principal_balance_cents": upb,
        "monthly_payment_cents": monthly,
        "months_in_arrears": months,
        "late_fee_per_month_cents": late_fee,
        "note_rate_pct": rate,
        "last_interest_paid_date": format_date(lipd),
        "prepayment_penalty_applies": penalty,
        "distribution_method": method,
        "lifecycle_status": "REFERRED",
        "hold_status": "CLEAR",
        "reinstatement_deadline_date": None,
        "undistributed_surplus_cents": 0,
        "_dist_run_count": 0,
    }
    stamp_new(case)
    db.foreclosure_cases[case["id"]] = case
    return success_object(view(case), status=201)


@bp.route("/api/foreclosure-cases", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer")
def list_cases(user_id, role):
    items = list(db.foreclosure_cases.values())
    beneficiary_id = request.args.get("beneficiary_id")
    lifecycle_status = request.args.get("lifecycle_status")
    if beneficiary_id is not None:
        items = [c for c in items if c["beneficiary_id"] == beneficiary_id]
    if lifecycle_status is not None:
        items = [c for c in items if c["lifecycle_status"] == lifecycle_status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination(request.args)
    page = [view(c) for c in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/foreclosure-cases/<case_id>", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "Beneficiary")
def read_case(user_id, role, case_id):
    case = get_case(case_id)
    check_beneficiary_owns_case(case, user_id, role)
    return success_object(view(case))


@bp.route("/api/foreclosure-cases/<case_id>/summary", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Beneficiary")
def read_case_summary(user_id, role, case_id):
    case = get_case(case_id)
    return success_object(case_summary(case))
