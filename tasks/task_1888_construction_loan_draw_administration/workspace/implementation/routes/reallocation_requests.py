from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import get_or_404
from util import (
    get_body,
    paginate,
    req_int,
    req_str,
    sort_created,
)

bp = Blueprint("reallocation_requests", __name__)


def _req_or_404(rid):
    return get_or_404(db.reallocation_requests, rid, "ReallocationRequest")


@bp.post("/reallocation-requests")
def create_reallocation():
    require_role(g.role, {"LenderAdmin"})
    body = get_body()
    # Existence (4): loan, then from/to lines.
    loan_id = body.get("loan_id")
    if loan_id is not None and loan_id not in db.loans:
        raise ApiError("ERR_NOT_FOUND", "Loan not found")
    loan = db.loans.get(loan_id) if isinstance(loan_id, str) else None
    from_id = body.get("from_budget_line_id")
    if from_id is not None and from_id not in db.budget_lines:
        raise ApiError("ERR_NOT_FOUND", "from_budget_line_id not found")
    to_id = body.get("to_budget_line_id")
    if to_id is not None and to_id not in db.budget_lines:
        raise ApiError("ERR_NOT_FOUND", "to_budget_line_id not found")
    # OCC stale-version guard (5): only when the field is present.
    expected = body.get("expected_loan_version")
    if expected is not None and loan is not None:
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field 'expected_loan_version' must be an integer"
            )
        if int(expected) != loan["version"]:
            raise ApiError(
                "ERR_STALE_LOAN_VERSION",
                "expected_loan_version does not match the current Loan.version",
            )
    # Loan-open gating (6).
    if loan is not None and loan["status"] != "OPEN":
        raise ApiError(
            "ERR_LOAN_NOT_OPEN", "Reallocations can only be drafted on an OPEN loan"
        )
    # Structural rules (9).
    amount = req_int(body, "amount_cents", min_value=1)
    justification = req_str(body, "justification")
    if expected is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'expected_loan_version' is required"
        )
    expected = int(expected)
    loan_id = req_str(body, "loan_id")
    from_id = req_str(body, "from_budget_line_id")
    to_id = req_str(body, "to_budget_line_id")
    if from_id == to_id:
        raise ApiError(
            "ERR_REALLOCATION_SAME_LINE", "from_budget_line_id == to_budget_line_id"
        )
    to_line = db.budget_lines[to_id]
    if to_line["is_contingency"]:
        raise ApiError(
            "ERR_CONTINGENCY_DIRECTION_VIOLATION",
            "Reallocation target must not be a contingency line",
        )
    # Cross-entity linkage (10).
    from_line = db.budget_lines[from_id]
    if from_line["loan_id"] != loan_id or to_line["loan_id"] != loan_id:
        raise ApiError(
            "ERR_BUDGET_LINE_LOAN_MISMATCH",
            "Both budget lines must belong to the named loan",
        )
    rec = db.base_record()
    rec.update(
        {
            "loan_id": loan_id,
            "from_budget_line_id": from_id,
            "to_budget_line_id": to_id,
            "amount_cents": amount,
            "justification": justification,
            "status": "PENDING",
            "review_reason": None,
            "created_loan_version": expected,
        }
    )
    db.reallocation_requests[rec["id"]] = rec
    # Drafting is itself a loan-mutating operation.
    touch(loan)
    return success(pub(rec), 201)


@bp.get("/reallocation-requests/<rid>")
def get_reallocation(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(_req_or_404(rid)))


@bp.get("/reallocation-requests")
def list_reallocations():
    require_role(g.role, ALL_ROLES)
    items = list(db.reallocation_requests.values())
    f_loan = request.args.get("loan_id")
    f_from = request.args.get("from_budget_line_id")
    f_to = request.args.get("to_budget_line_id")
    f_status = request.args.get("status")
    if f_loan is not None:
        items = [r for r in items if r["loan_id"] == f_loan]
    if f_from is not None:
        items = [r for r in items if r["from_budget_line_id"] == f_from]
    if f_to is not None:
        items = [r for r in items if r["to_budget_line_id"] == f_to]
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)


@bp.post("/reallocation-requests/<rid>/review")
def review_reallocation(rid):
    require_role(g.role, {"CreditOfficer"})
    rec = _req_or_404(rid)
    if rec["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a PENDING reallocation can be reviewed"
        )
    body = get_body()
    decision = req_str(body, "decision")
    if decision not in ("APPROVED", "REJECTED"):
        raise ApiError(
            "ERR_INVALID_REQUEST", "decision must be APPROVED or REJECTED"
        )
    if decision == "REJECTED":
        rec["review_reason"] = req_str(body, "reason")
    rec["status"] = decision
    touch(rec)
    return success(pub(rec))


@bp.post("/reallocation-requests/<rid>/apply")
def apply_reallocation(rid):
    require_role(g.role, {"LoanServicer"})
    rec = _req_or_404(rid)
    if rec["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an APPROVED reallocation can be applied"
        )
    loan = db.loans[rec["loan_id"]]
    if loan["status"] != "OPEN":
        raise ApiError("ERR_LOAN_NOT_OPEN", "Apply requires an OPEN loan")
    from_line = db.budget_lines[rec["from_budget_line_id"]]
    to_line = db.budget_lines[rec["to_budget_line_id"]]
    floor = (
        from_line["disbursed_cents"]
        + from_line["retained_cents"]
        + from_line["approved_unfunded_cents"]
    )
    if from_line["revised_amount_cents"] - rec["amount_cents"] < floor:
        raise ApiError(
            "ERR_REALLOCATION_BELOW_FLOOR",
            "Apply would drop the from-line revised amount below disbursed + retained + approved_unfunded",
        )
    from_line["revised_amount_cents"] -= rec["amount_cents"]
    to_line["revised_amount_cents"] += rec["amount_cents"]
    touch(from_line)
    touch(to_line)
    rec["status"] = "APPLIED"
    touch(rec)
    touch(loan)
    return success(pub(rec))


@bp.post("/reallocation-requests/<rid>/cancel")
def cancel_reallocation(rid):
    require_role(g.role, {"LenderAdmin"})
    rec = _req_or_404(rid)
    if rec["status"] not in ("PENDING", "APPROVED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a PENDING or APPROVED reallocation can be cancelled",
        )
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(pub(rec))
