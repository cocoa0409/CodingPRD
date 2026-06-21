"""Application endpoints — the origination axis plus the servicing/guaranty axes
that begin here. PRD §3.1, §3.4, §3.5, §3.6, §3.7, §3.10, §4."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services import calculations as calc
from services.common import (
    serialize, get_json_body, require_string, require_positive_int,
    require_number, paginate, sort_by_created,
)

bp = Blueprint("applications", __name__)

APP_READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover", "InvestorServicer"]
APP_LIST_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


# --- create / read -----------------------------------------------------------

@bp.post("/sba/applications")
def create_application():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()

    borrower_id = require_string(body, "borrower_id")
    requested = require_positive_int(body, "requested_amount_cents")
    guaranty_pct = require_number(body, "guaranty_pct")
    maturity = require_positive_int(body, "maturity_months")

    # guaranty_pct strictly > 0 and <= 0.90 (PRD §3.1).
    if not (0 < guaranty_pct <= 0.90):
        raise errors.invalid_request("guaranty_pct must be > 0 and <= 0.90")

    with db.LOCK:
        borrower = db.borrowers.get(borrower_id)
        if borrower is None:
            raise errors.invalid_request("borrower_id does not reference an existing Borrower")
        rec = db.init_record({
            "borrower_id": borrower_id,
            "lender_id": borrower["lender_id"],  # denormalized from Borrower
            "requested_amount_cents": requested,
            "guaranty_pct": guaranty_pct,
            "maturity_months": maturity,
            "size_eligible": False,
            "guaranteed_amount_cents": 0,
            "guaranty_fee_cents": 0,
            "disbursed_amount_cents": 0,
            "outstanding_principal_cents": 0,
            "sold_guaranteed_principal_cents": 0,
            "status": "DRAFT",
            "servicing_status": "NOT_SERVICING",
            "guaranty_status": "RETAINED",
        })
        db.applications[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>")
def get_application(application_id):
    user_id, role = get_user_context()
    require_roles(role, APP_READ_ROLES)
    with db.LOCK:
        rec = db.applications.get(application_id)
        if rec is None:
            raise errors.not_found("Application not found")
        return object_response(serialize(rec), 200)


@bp.get("/sba/applications")
def list_applications():
    user_id, role = get_user_context()
    require_roles(role, APP_LIST_ROLES)
    lender_id = request.args.get("lender_id")
    borrower_id = request.args.get("borrower_id")
    status = request.args.get("status")
    with db.LOCK:
        items = list(db.applications.values())
        if lender_id is not None:
            items = [a for a in items if a["lender_id"] == lender_id]
        if borrower_id is not None:
            items = [a for a in items if a["borrower_id"] == borrower_id]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


# --- helpers -----------------------------------------------------------------

def _get_app_or_404(application_id):
    rec = db.applications.get(application_id)
    if rec is None:
        raise errors.not_found("Application not found")
    return rec


def _credit_memos_for(application_id):
    return [m for m in db.credit_memos.values() if m["application_id"] == application_id]


def _submitted_memo(application_id):
    for m in _credit_memos_for(application_id):
        if m["status"] == "SUBMITTED":
            return m
    return None


def _draft_memo(application_id):
    for m in _credit_memos_for(application_id):
        if m["status"] == "DRAFT":
            return m
    return None


# --- origination axis transitions -------------------------------------------

@bp.post("/sba/applications/<application_id>/submit")
def submit_application(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        # state precedence (ERR_INVALID_STATE) before business rules.
        if app["status"] != "DRAFT":
            raise errors.invalid_state("Application is not in DRAFT")
        borrower = db.borrowers[app["borrower_id"]]
        # business rules in the order stated in PRD §3.4.
        if not borrower["is_eligible_business_type"]:
            raise errors.err(errors.ERR_INELIGIBLE_BUSINESS, 409,
                             "Borrower business type is ineligible")
        items = [p for p in db.proceeds.values() if p["application_id"] == application_id]
        if len(items) == 0:
            raise errors.err(errors.ERR_NO_PROCEEDS, 409, "No proceeds line items")
        total = sum(p["amount_cents"] for p in items)
        if total != app["requested_amount_cents"]:
            raise errors.err(errors.ERR_PROCEEDS_MISMATCH, 422,
                             "Proceeds sum does not equal requested amount")
        # size standard side effect.
        eligible = calc.size_standard(borrower)
        app["size_eligible"] = eligible
        if not eligible:
            # No transition; size_eligible is still written.
            db.touch(app)
            raise errors.err(errors.ERR_SIZE_STANDARD_EXCEEDED, 409,
                             "Application fails the size standard")
        app["status"] = "UNDERWRITING"
        db.touch(app)
        return object_response(serialize(app), 200)


@bp.post("/sba/applications/<application_id>/request-revision")
def request_revision(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditApprover"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        if app["status"] != "PENDING_APPROVAL":
            raise errors.invalid_state("Application is not PENDING_APPROVAL")
        memo = _submitted_memo(application_id)
        if memo is None:
            raise errors.err(errors.ERR_NO_CREDIT_MEMO, 409,
                             "No SUBMITTED credit memo exists")
        memo["status"] = "REJECTED"
        db.touch(memo)
        app["status"] = "REVISION"
        db.touch(app)
        return object_response(serialize(app), 200)


@bp.post("/sba/applications/<application_id>/resubmit")
def resubmit_application(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        if app["status"] != "REVISION":
            raise errors.invalid_state("Application is not in REVISION")
        if _draft_memo(application_id) is None:
            raise errors.err(errors.ERR_NO_CREDIT_MEMO, 409,
                             "No DRAFT credit memo exists for the revision")
        app["status"] = "UNDERWRITING"
        db.touch(app)
        return object_response(serialize(app), 200)


@bp.post("/sba/applications/<application_id>/approve")
def approve_application(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditApprover"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        if app["status"] != "PENDING_APPROVAL":
            raise errors.invalid_state("Application is not PENDING_APPROVAL")
        memo = _submitted_memo(application_id)
        if memo is None:
            # A pending application always has a submitted memo; defensive guard.
            raise errors.err(errors.ERR_NO_CREDIT_MEMO, 409,
                             "No SUBMITTED credit memo exists")
        # Four-eyes precedes the recommendation check (PRD §3.5 order).
        if user_id == memo["authored_by_user_id"]:
            raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, 409,
                             "Approver may not be the memo author")
        if memo["recommendation"] != "APPROVE":
            raise errors.err(errors.ERR_MEMO_NOT_APPROVABLE, 409,
                             "Memo recommendation is not APPROVE")
        memo["status"] = "APPROVED"
        db.touch(memo)
        app["status"] = "APPROVED"
        db.touch(app)
        return object_response(serialize(app), 200)


@bp.post("/sba/applications/<application_id>/decline")
def decline_application(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditApprover"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        if app["status"] != "PENDING_APPROVAL":
            raise errors.invalid_state("Application is not PENDING_APPROVAL")
        memo = _submitted_memo(application_id)
        if memo is None:
            raise errors.err(errors.ERR_NO_CREDIT_MEMO, 409,
                             "No SUBMITTED credit memo exists")
        if user_id == memo["authored_by_user_id"]:
            raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, 409,
                             "Decliner may not be the memo author")
        memo["status"] = "REJECTED"
        db.touch(memo)
        app["status"] = "DECLINED"
        db.touch(app)
        return object_response(serialize(app), 200)


@bp.post("/sba/applications/<application_id>/authorize")
def authorize_application(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["SbaOfficer"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        if app["status"] != "APPROVED":
            raise errors.invalid_state("Application is not APPROVED")
        if not app["size_eligible"]:
            raise errors.err(errors.ERR_SIZE_STANDARD_EXCEEDED, 409,
                             "Application fails the size standard")
        # Freeze guaranteed amount and guaranty fee.
        app["guaranteed_amount_cents"] = calc.guaranty_amount(
            app["requested_amount_cents"], app["guaranty_pct"])
        app["guaranty_fee_cents"] = calc.guaranty_fee(
            app["requested_amount_cents"], app["guaranty_pct"])
        app["status"] = "AUTHORIZED"
        # guaranty_status stays RETAINED, servicing_status stays NOT_SERVICING.
        db.touch(app)
        return object_response(serialize(app), 200)


@bp.post("/sba/applications/<application_id>/close")
def close_application(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        if app["status"] != "DISBURSING":
            raise errors.invalid_state("Application is not DISBURSING")
        if app["disbursed_amount_cents"] != app["requested_amount_cents"]:
            raise errors.err(errors.ERR_NOT_FULLY_DISBURSED, 409,
                             "Application is not fully disbursed")
        app["status"] = "CLOSED"
        db.touch(app)
        return object_response(serialize(app), 200)


@bp.post("/sba/applications/<application_id>/withdraw")
def withdraw_application(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        if app["status"] not in ("DRAFT", "UNDERWRITING", "REVISION"):
            raise errors.invalid_state("Application cannot be withdrawn from its current state")
        app["status"] = "WITHDRAWN"
        db.touch(app)
        return object_response(serialize(app), 200)


@bp.post("/sba/applications/<application_id>/declare-default")
def declare_default(application_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        app = _get_app_or_404(application_id)
        # servicing axis transition DELINQUENT -> DEFAULTED.
        if app["servicing_status"] != "DELINQUENT":
            raise errors.invalid_state("Application is not DELINQUENT")
        # Most-recent ACCEPTED ServicingReport days_past_due >= 90.
        last = _last_accepted_report(application_id)
        if last is None or last["days_past_due"] < 90:
            raise errors.err(errors.ERR_NOT_DELINQUENT_ENOUGH, 409,
                             "Most recent accepted report is not 90+ days past due")
        app["servicing_status"] = "DEFAULTED"
        db.touch(app)
        return object_response(serialize(app), 200)


def _last_accepted_report(application_id):
    accepted = [r for r in db.servicing_reports.values()
                if r["application_id"] == application_id and r["status"] == "ACCEPTED"]
    if not accepted:
        return None
    # "Most-recent" by the latest covered period (period_end_month), then creation.
    accepted.sort(key=lambda r: (r["period_end_month"], r["_seq"]))
    return accepted[-1]
