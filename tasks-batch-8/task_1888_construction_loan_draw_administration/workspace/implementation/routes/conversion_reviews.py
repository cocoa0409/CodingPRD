from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_borrower_ownership, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import (
    ACTIVE_DRAW_STATES,
    cascade_close_budget_lines,
    get_or_404,
    has_accepted_100_inspection,
    sweep_reserve,
)
from util import get_body, paginate, req_enum, req_int, req_str, sort_created

bp = Blueprint("conversion_reviews", __name__)


def _conv_or_404(rid):
    return get_or_404(db.conversion_reviews, rid, "ConversionReview")


@bp.post("/conversion-reviews")
def create_conversion_review():
    require_role(g.role, {"Borrower"})
    body = get_body()
    loan_id = body.get("loan_id")
    if loan_id is not None and loan_id not in db.loans:
        raise ApiError("ERR_NOT_FOUND", "Loan not found")
    loan = db.loans.get(loan_id) if isinstance(loan_id, str) else None
    if loan is not None:
        require_borrower_ownership(g.uid, loan)
        if loan["status"] != "OPEN":
            raise ApiError(
                "ERR_LOAN_NOT_OPEN",
                "Conversion reviews can only be requested on an OPEN loan",
            )
    loan_id = req_str(body, "loan_id")
    if any(
        c["loan_id"] == loan_id and c["status"] in ("REQUESTED", "APPROVED")
        for c in db.conversion_reviews.values()
    ):
        raise ApiError(
            "ERR_CONVERSION_IN_PROGRESS",
            "A ConversionReview in REQUESTED or APPROVED already exists for the loan",
        )
    rec = db.base_record()
    rec.update(
        {
            "loan_id": loan_id,
            "status": "REQUESTED",
            "decline_reason": None,
            "permanent_interest_rate_annual_bps": None,
            "permanent_term_months": None,
        }
    )
    db.conversion_reviews[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/conversion-reviews/<rid>")
def get_conversion_review(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(_conv_or_404(rid)))


@bp.get("/conversion-reviews")
def list_conversion_reviews():
    require_role(g.role, ALL_ROLES)
    items = list(db.conversion_reviews.values())
    f_loan = request.args.get("loan_id")
    f_status = request.args.get("status")
    if f_loan is not None:
        items = [c for c in items if c["loan_id"] == f_loan]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)


@bp.post("/conversion-reviews/<rid>/review")
def review_conversion(rid):
    require_role(g.role, {"CreditOfficer"})
    rec = _conv_or_404(rid)
    if rec["status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a REQUESTED conversion review can be reviewed"
        )
    body = get_body()
    decision = req_enum(body, "decision", ["APPROVED", "DECLINED"])
    loan = db.loans[rec["loan_id"]]
    if decision == "DECLINED":
        rec["decline_reason"] = req_str(body, "reason")
        rec["status"] = "DECLINED"
        touch(rec)
        return success(pub(rec))
    # APPROVED is readiness-gated.
    if loan["status"] != "OPEN":
        raise ApiError("ERR_LOAN_NOT_OPEN", "Conversion approval requires an OPEN loan")
    has_active_draw = any(
        d["loan_id"] == loan["id"] and d["status"] in ACTIVE_DRAW_STATES
        for d in db.draws.values()
    )
    if (
        loan["retained_cents"] != 0
        or has_active_draw
        or not has_accepted_100_inspection(loan["id"])
    ):
        raise ApiError(
            "ERR_CONVERSION_PRECONDITIONS_UNMET",
            "Conversion approval blocked: retained_cents > 0, non-terminal draws exist, or no ACCEPTED 100.00 inspection",
        )
    rec["status"] = "APPROVED"
    touch(rec)
    return success(pub(rec))


@bp.post("/conversion-reviews/<rid>/convert")
def execute_conversion(rid):
    require_role(g.role, {"LoanServicer"})
    rec = _conv_or_404(rid)
    if rec["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an APPROVED conversion review can be executed"
        )
    loan = db.loans[rec["loan_id"]]
    if loan["status"] != "OPEN":
        raise ApiError("ERR_LOAN_NOT_OPEN", "Conversion requires an OPEN loan")
    body = get_body()
    perm_rate = req_int(body, "permanent_interest_rate_annual_bps", min_value=0)
    perm_term = req_int(body, "permanent_term_months", min_value=1)
    rec["permanent_interest_rate_annual_bps"] = perm_rate
    rec["permanent_term_months"] = perm_term
    rec["status"] = "CONVERTED"
    touch(rec)
    # Loan OPEN -> CONVERTED cascade.
    loan["status"] = "CONVERTED"
    loan["permanent_interest_rate_annual_bps"] = perm_rate
    loan["permanent_term_months"] = perm_term
    cascade_close_budget_lines(loan)
    sweep_reserve(loan)
    touch(loan)
    return success(pub(rec))
