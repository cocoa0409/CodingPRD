"""CropBudget endpoints: create (OCC on loan version), approve, record_actuals."""
from flask import Blueprint

from db import STORE
from errors import raise_err
from middleware import ALL_ROLES, auth, require_owner, require_role
from response import ok_list, ok_object
from routes.loans import get_loan_or_404
from serialize import list_response, ser_budget
from services.core import (TERMINAL_LOAN_STATES, budgets_of_loan,
                           recompute_borrowing_base, standard_cascade,
                           stamp_new, touch)
from util import (as_int, as_nonneg_int, as_pos_int, as_str, body, need,
                  new_id)

bp = Blueprint("budgets", __name__)


def get_budget_or_404(budget_id):
    budget = STORE.budgets.get(budget_id)
    if budget is None:
        raise_err("ERR_NOT_FOUND", "Crop budget not found")
    return budget


@bp.route("/crop-budgets", methods=["POST"])
def create_budget():
    uid, role = auth()
    require_role(role, ["Borrower"])
    b = body()
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    season_year = as_int(need(b, "season_year"), "season_year")
    crop_type = as_str(need(b, "crop_type"), "crop_type")
    acres = as_pos_int(need(b, "acres"), "acres")
    proj_rev = as_nonneg_int(need(b, "projected_revenue_cents"), "projected_revenue_cents")
    proj_exp = as_nonneg_int(need(b, "projected_expenses_cents"), "projected_expenses_cents")
    expected_loan_version = as_int(need(b, "expected_loan_version"), "expected_loan_version")
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    require_owner(loan["borrower_id"] == uid)
    if season_year != loan["season_year"]:
        raise_err("ERR_INVALID_REQUEST", "season_year must equal the loan's season_year")
    if expected_loan_version != loan["version"]:
        raise_err("ERR_STALE_VERSION", "expected_loan_version does not match the loan version")
    if loan["status"] == "RESTRUCTURING" or loan["status"] in TERMINAL_LOAN_STATES:
        raise_err("ERR_LOAN_NOT_ACTIVE",
                  "Budget creation requires a non-terminal, non-RESTRUCTURING loan")
    borrower = STORE.borrowers.get(loan["borrower_id"])
    if borrower is not None and borrower["status"] == "SUSPENDED":
        raise_err("ERR_BORROWER_SUSPENDED",
                  "Suspended borrowers cannot create crop budgets")
    # A newer DRAFT supersedes an existing DRAFT of the same loan.
    for other in budgets_of_loan(loan["id"]):
        if other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            touch(other)
    budget = stamp_new({
        "id": new_id(),
        "loan_account_id": loan["id"],
        "season_year": season_year,
        "crop_type": crop_type,
        "acres": acres,
        "projected_revenue_cents": proj_rev,
        "projected_expenses_cents": proj_exp,
        "actual_revenue_cents": None,
        "status": "DRAFT",
    })
    STORE.budgets[budget["id"]] = budget
    touch(loan)  # budget creation increments the loan version
    return ok_object(ser_budget(budget), code=201)


@bp.route("/crop-budgets/<bid>", methods=["GET"])
def get_budget(bid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_budget(get_budget_or_404(bid)))


@bp.route("/crop-budgets", methods=["GET"])
def list_budgets():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.budgets.values(), ser_budget,
        [("loan_account_id", lambda e: e["loan_account_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/crop-budgets/<bid>/approve", methods=["POST"])
def approve_budget(bid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    budget = get_budget_or_404(bid)
    if budget["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT budget can be approved")
    loan = get_loan_or_404(budget["loan_account_id"])
    # Approval always belongs to the newest plan.
    for other in budgets_of_loan(loan["id"]):
        if (other["id"] != budget["id"] and other["status"] == "APPROVED"
                and other["_seq"] > budget["_seq"]):
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "A newer APPROVED budget exists for this loan")
    for other in budgets_of_loan(loan["id"]):
        if other["id"] != budget["id"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            touch(other)
    budget["status"] = "APPROVED"
    touch(budget)
    recompute_borrowing_base(loan)
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_budget(budget))


@bp.route("/crop-budgets/<bid>/record_actuals", methods=["POST"])
def record_actuals(bid):
    uid, role = auth()
    require_role(role, ["Borrower", "LoanOfficer"])
    b = body()
    actual = as_nonneg_int(need(b, "actual_revenue_cents"), "actual_revenue_cents")
    budget = get_budget_or_404(bid)
    if role == "Borrower":
        loan = get_loan_or_404(budget["loan_account_id"])
        require_owner(loan["borrower_id"] == uid)
    if budget["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only an APPROVED budget can be actualized")
    loan = get_loan_or_404(budget["loan_account_id"])
    budget["actual_revenue_cents"] = actual
    budget["status"] = "ACTUALIZED"
    touch(budget)
    recompute_borrowing_base(loan)  # harvest true-up variant
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_budget(budget))
