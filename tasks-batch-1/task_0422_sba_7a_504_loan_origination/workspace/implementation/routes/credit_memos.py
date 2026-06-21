"""CreditMemo endpoints — PRD §3.4, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services import calculations as calc
from services.common import (
    serialize, get_json_body, require_string, require_number, require_int,
    require_enum, paginate, sort_by_created,
)

bp = Blueprint("credit_memos", __name__)

READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


@bp.post("/sba/credit-memos")
def create_credit_memo():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    dscr = require_number(body, "dscr")
    risk_rating = require_int(body, "risk_rating")
    recommendation = require_enum(body, "recommendation", {"APPROVE", "DECLINE"})
    # risk_rating constrained 1..8.
    if not (1 <= risk_rating <= 8):
        raise errors.invalid_request("risk_rating must be between 1 and 8")
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.invalid_request("application_id does not reference an existing Application")
        rec = db.init_record({
            "application_id": application_id,
            "authored_by_user_id": user_id,  # X-User-ID of authoring LoanOfficer
            "dscr": dscr,
            "risk_rating": risk_rating,
            "recommendation": recommendation,
            "status": "DRAFT",
        })
        db.credit_memos[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/credit-memos")
def list_credit_memos(application_id):
    user_id, role = get_user_context()
    require_roles(role, READ_ROLES)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [m for m in db.credit_memos.values() if m["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/sba/credit-memos/<credit_memo_id>/submit")
def submit_credit_memo(credit_memo_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        memo = db.credit_memos.get(credit_memo_id)
        if memo is None:
            raise errors.not_found("CreditMemo not found")
        app = db.applications.get(memo["application_id"])
        # state: memo DRAFT and application UNDERWRITING for the transition.
        if memo["status"] != "DRAFT" or app["status"] != "UNDERWRITING":
            raise errors.invalid_state("CreditMemo/Application not in a submittable state")
        # business preconditions in PRD §3.4 order:
        # 1. FormPackage CLEARED.
        cleared = any(
            f["application_id"] == app["id"] and f["status"] == "CLEARED"
            for f in db.form_packages.values()
        )
        if not cleared:
            raise errors.err(errors.ERR_FORM_PACKAGE_NOT_CLEARED, 409,
                             "FormPackage is not CLEARED")
        # 2. collateral coverage.
        items = [c for c in db.collateral.values() if c["application_id"] == app["id"]]
        if not calc.collateral_coverage_ok(items, app["maturity_months"], app["requested_amount_cents"]):
            raise errors.err(errors.ERR_COLLATERAL_SHORTFALL, 409,
                             "Discounted collateral coverage is insufficient")
        memo["status"] = "SUBMITTED"
        db.touch(memo)
        app["status"] = "PENDING_APPROVAL"
        db.touch(app)
        return object_response(serialize(memo), 200)
