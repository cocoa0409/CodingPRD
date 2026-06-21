"""Borrower endpoints — PRD §3.1, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response
from services.common import (
    serialize, get_json_body, require_string, require_nonneg_int, optional_bool,
)

bp = Blueprint("borrowers", __name__)

BORROWER_READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


@bp.post("/sba/borrowers")
def create_borrower():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()

    lender_id = require_string(body, "lender_id")
    legal_name = require_string(body, "legal_name")
    naics_code = require_string(body, "naics_code")
    tnw = require_nonneg_int(body, "tangible_net_worth_cents")
    avg_ni = require_nonneg_int(body, "avg_net_income_cents")
    emp = require_nonneg_int(body, "affiliate_employee_count")
    is_eligible = optional_bool(body, "is_eligible_business_type", default=True)

    with db.LOCK:
        # FK target must exist (ERR_INVALID_REQUEST per §2.10 body tier).
        if lender_id not in db.lenders:
            raise errors.invalid_request("lender_id does not reference an existing Lender")
        rec = db.init_record({
            "lender_id": lender_id,
            "legal_name": legal_name,
            "naics_code": naics_code,
            "tangible_net_worth_cents": tnw,
            "avg_net_income_cents": avg_ni,
            "affiliate_employee_count": emp,
            "is_eligible_business_type": is_eligible,
        })
        db.borrowers[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/borrowers/<borrower_id>")
def get_borrower(borrower_id):
    user_id, role = get_user_context()
    require_roles(role, BORROWER_READ_ROLES)
    with db.LOCK:
        rec = db.borrowers.get(borrower_id)
        if rec is None:
            raise errors.not_found("Borrower not found")
        return object_response(serialize(rec), 200)
