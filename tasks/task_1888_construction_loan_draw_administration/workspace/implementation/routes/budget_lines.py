from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import get_or_404, lines_of_loan, recompute_loan_money
from util import get_body, opt_bool, paginate, req_int, req_str, sort_created

bp = Blueprint("budget_lines", __name__)


@bp.post("/budget-lines")
def create_budget_line():
    require_role(g.role, {"LenderAdmin"})
    body = get_body()
    # Existence (4) before state (6) before structural (9) before fiscal (11).
    loan_id = body.get("loan_id")
    if loan_id is not None and loan_id not in db.loans:
        raise ApiError("ERR_NOT_FOUND", "Loan not found")
    loan = db.loans.get(loan_id) if isinstance(loan_id, str) else None
    if loan is not None and loan["status"] != "OPEN":
        raise ApiError("ERR_LOAN_NOT_OPEN", "Budget lines can only be added to an OPEN loan")
    cost_code = req_str(body, "cost_code")
    description = req_str(body, "description")
    original = req_int(body, "original_amount_cents", min_value=1)
    is_contingency = opt_bool(body, "is_contingency", False)
    loan_id = req_str(body, "loan_id")
    if any(
        l["loan_id"] == loan_id and l["cost_code"] == cost_code
        for l in db.budget_lines.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_COST_CODE",
            "cost_code already used by another BudgetLine of the same loan",
        )
    if (
        sum(l["original_amount_cents"] for l in lines_of_loan(loan_id)) + original
        > loan["commitment_amount_cents"]
    ):
        raise ApiError(
            "ERR_COMMITMENT_EXCEEDED",
            "Sum of budget-line original_amount_cents would exceed the loan commitment",
        )
    rec = db.base_record()
    rec.update(
        {
            "loan_id": loan_id,
            "cost_code": cost_code,
            "description": description,
            "original_amount_cents": original,
            "is_contingency": is_contingency,
            "status": "ACTIVE",
            "revised_amount_cents": original,
            "disbursed_cents": 0,
            "retained_cents": 0,
            "approved_unfunded_cents": 0,
        }
    )
    db.budget_lines[rec["id"]] = rec
    recompute_loan_money(loan)
    touch(loan)
    return success(pub(rec), 201)


@bp.get("/budget-lines/<rid>")
def get_budget_line(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(get_or_404(db.budget_lines, rid, "BudgetLine")))


@bp.get("/budget-lines")
def list_budget_lines():
    require_role(g.role, ALL_ROLES)
    items = list(db.budget_lines.values())
    f_loan = request.args.get("loan_id")
    f_cont = request.args.get("is_contingency")
    f_status = request.args.get("status")
    if f_loan is not None:
        items = [l for l in items if l["loan_id"] == f_loan]
    if f_cont is not None:
        want = f_cont.strip().lower() in ("true", "1", "yes")
        items = [l for l in items if l["is_contingency"] == want]
    if f_status is not None:
        items = [l for l in items if l["status"] == f_status]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)
