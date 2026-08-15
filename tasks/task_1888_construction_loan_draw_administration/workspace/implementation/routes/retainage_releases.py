from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_borrower_ownership, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import (
    get_or_404,
    has_accepted_100_inspection,
    recompute_loan_money,
)
from util import get_body, paginate, req_enum, req_int, req_str, sort_created

bp = Blueprint("retainage_releases", __name__)


def _rel_or_404(rid):
    return get_or_404(db.retainage_releases, rid, "RetainageRelease")


@bp.post("/retainage-releases")
def create_release():
    require_role(g.role, {"Borrower"})
    body = get_body()
    # Existence (4).
    loan_id = body.get("loan_id")
    if loan_id is not None and loan_id not in db.loans:
        raise ApiError("ERR_NOT_FOUND", "Loan not found")
    loan = db.loans.get(loan_id) if isinstance(loan_id, str) else None
    line_id = body.get("budget_line_id")
    if line_id is not None and line_id not in db.budget_lines:
        raise ApiError("ERR_NOT_FOUND", "BudgetLine not found")
    line = db.budget_lines.get(line_id) if isinstance(line_id, str) else None
    if loan is not None:
        # Borrower ownership (3).
        require_borrower_ownership(g.uid, loan)
        # Loan-open gating (6).
        if loan["status"] != "OPEN":
            raise ApiError(
                "ERR_LOAN_NOT_OPEN",
                "Retainage releases can only be requested on an OPEN loan",
            )
    # Structural (9).
    amount = req_int(body, "amount_cents", min_value=1)
    reason = req_str(body, "reason")
    loan_id = req_str(body, "loan_id")
    line_id = req_str(body, "budget_line_id")
    # Cross-entity readiness (10), PRD §3.6 prose order: releasability, then
    # budget-line-to-loan matching.
    if not (loan["milestone_reached"] or has_accepted_100_inspection(loan_id)):
        raise ApiError(
            "ERR_RETAINAGE_NOT_RELEASABLE",
            "Release requested before milestone_reached and without a 100.00 ACCEPTED inspection",
        )
    if line["loan_id"] != loan_id:
        raise ApiError(
            "ERR_BUDGET_LINE_LOAN_MISMATCH",
            "Budget line belongs to a different loan than the release references",
        )
    # Fiscal cap (11): amount vs the line's currently withheld retainage.
    if amount > line["retained_cents"]:
        raise ApiError(
            "ERR_RELEASE_EXCEEDS_RETAINED",
            "Release amount exceeds the line's current retained_cents",
        )
    rec = db.base_record()
    rec.update(
        {
            "loan_id": loan_id,
            "budget_line_id": line_id,
            "amount_cents": amount,
            "reason": reason,
            "status": "REQUESTED",
            "review_reason": None,
        }
    )
    db.retainage_releases[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/retainage-releases/<rid>")
def get_release(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(_rel_or_404(rid)))


@bp.get("/retainage-releases")
def list_releases():
    require_role(g.role, ALL_ROLES)
    items = list(db.retainage_releases.values())
    f_loan = request.args.get("loan_id")
    f_line = request.args.get("budget_line_id")
    f_status = request.args.get("status")
    if f_loan is not None:
        items = [r for r in items if r["loan_id"] == f_loan]
    if f_line is not None:
        items = [r for r in items if r["budget_line_id"] == f_line]
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)


@bp.post("/retainage-releases/<rid>/review")
def review_release(rid):
    require_role(g.role, {"CreditOfficer"})
    rec = _rel_or_404(rid)
    if rec["status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a REQUESTED retainage release can be reviewed"
        )
    body = get_body()
    decision = req_enum(body, "decision", ["APPROVED", "REJECTED"])
    if decision == "APPROVED":
        loan = db.loans[rec["loan_id"]]
        if loan["status"] != "OPEN":
            raise ApiError(
                "ERR_LOAN_NOT_OPEN", "Approving a release requires an OPEN loan"
            )
    else:
        rec["review_reason"] = req_str(body, "reason")
    rec["status"] = decision
    touch(rec)
    return success(pub(rec))


@bp.post("/retainage-releases/<rid>/pay")
def pay_release(rid):
    require_role(g.role, {"LoanServicer"})
    rec = _rel_or_404(rid)
    if rec["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an APPROVED retainage release can be paid"
        )
    loan = db.loans[rec["loan_id"]]
    if loan["status"] != "OPEN":
        raise ApiError("ERR_LOAN_NOT_OPEN", "Paying a release requires an OPEN loan")
    line = db.budget_lines[rec["budget_line_id"]]
    # Re-verified at payment time (priority 11).
    if line["retained_cents"] < rec["amount_cents"]:
        raise ApiError(
            "ERR_RELEASE_EXCEEDS_RETAINED",
            "Release amount exceeds the line's current retained_cents",
        )
    line["retained_cents"] -= rec["amount_cents"]
    line["disbursed_cents"] += rec["amount_cents"]
    touch(line)
    recompute_loan_money(loan)
    touch(loan)
    rec["status"] = "PAID"
    touch(rec)
    return success(pub(rec))
