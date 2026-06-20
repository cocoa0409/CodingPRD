"""NonBorrowingSpouseDeferral endpoints (§3.10)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common
from services.clock import clock_date

bp = Blueprint("deferrals", __name__)

READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}


def _active_deferral_exists(loan_id):
    for d in db.nbs_deferrals.values():
        if d["loan_id"] == loan_id and d["status"] == "ACTIVE":
            return True
    return False


@bp.route("/nbs-deferrals", methods=["POST"])
def create_deferral():
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    body = common.get_json_body()
    common.require_fields(body, ["loan_id", "borrower_id", "maturity_event_id"])
    # existence left to right: loan, borrower, maturity_event
    loan = db.loans.get(body["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    borrower = db.borrowers.get(body["borrower_id"])
    if borrower is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Borrower not found")
    event = db.maturity_events.get(body["maturity_event_id"])
    if event is None:
        raise errors.err(errors.ERR_NOT_FOUND, "MaturityEvent not found")

    # a loan already carrying an ACTIVE deferral cannot open another
    if _active_deferral_exists(loan["id"]):
        raise errors.err(errors.ERR_DEFERRAL_ACTIVE, "Loan already has an active deferral")
    # state: loan must be DUE_AND_PAYABLE to enter deferral
    if loan["disposition_status"] != "DUE_AND_PAYABLE":
        raise errors.err(errors.ERR_INVALID_STATE, "Loan not due-and-payable")
    # triggering event must be a death
    if event["event_type"] != "BORROWER_DEATH":
        raise errors.err(errors.ERR_DEFERRAL_NOT_ELIGIBLE, "Only a borrower death opens deferral eligibility")
    # named spouse must qualify
    if not (borrower.get("is_non_borrowing_spouse") and borrower.get("nbs_qualifies")):
        raise errors.err(errors.ERR_NBS_NOT_QUALIFIED, "Named borrower is not a qualifying non-borrowing spouse")

    rec = {
        "loan_id": loan["id"],
        "borrower_id": borrower["id"],
        "maturity_event_id": event["id"],
        "period_start": event["event_date"],
        "period_end": None,
        "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.nbs_deferrals[rec["id"]] = rec
    loan["disposition_status"] = "DEFERRED"
    db.touch(loan)
    return success(public(rec), status=201)


@bp.route("/nbs-deferrals/<deferral_id>", methods=["GET"])
def get_deferral(deferral_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    rec = db.nbs_deferrals.get(deferral_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "NonBorrowingSpouseDeferral not found")
    return success(public(rec))


@bp.route("/nbs-deferrals", methods=["GET"])
def list_deferrals():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.nbs_deferrals.values())
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    borrower_id = request.args.get("borrower_id")
    if borrower_id is not None:
        rows = [r for r in rows if r["borrower_id"] == borrower_id]
    event_id = request.args.get("maturity_event_id")
    if event_id is not None:
        rows = [r for r in rows if r["maturity_event_id"] == event_id]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)


@bp.route("/nbs-deferrals/<deferral_id>/terminate", methods=["POST"])
def terminate(deferral_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    rec = db.nbs_deferrals.get(deferral_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "NonBorrowingSpouseDeferral not found")
    if rec["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Deferral not ACTIVE")
    loan = db.loans.get(rec["loan_id"])
    lender = db.lenders[loan["lender_id"]] if loan else None
    rec["status"] = "TERMINATED"
    rec["period_end"] = clock_date(lender).isoformat() if lender else None
    db.touch(rec)
    if loan is not None and loan["disposition_status"] == "DEFERRED":
        loan["disposition_status"] = "DUE_AND_PAYABLE"
        db.touch(loan)
    return success(public(rec))
