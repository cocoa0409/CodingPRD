"""Expenditure routes: create (routing + OCC), approve, deny, disburse."""

from flask import Blueprint, request

from clock import clock
from db import db, stamp_create, stamp_update
from errors import err
from middleware import get_identity, require_role
from response import object_response, array_response
from validators import (
    ALL_ROLES,
    get_json_body,
    require_string,
    require_int,
    require_enum,
    parse_pagination,
    paginate,
)
from services import (
    resolve_path,
    resolve_ref,
    accounts_for_case,
    expenditures_for_case,
    touch_account,
    touch_case,
)
from calculations import expenditure_requires_court_approval

bp = Blueprint("expenditures", __name__)


def _account_for_case(case_id):
    accounts = accounts_for_case(case_id)
    return accounts[0] if accounts else None


def _check_budget_cap(expenditure, budget):
    """Cap check (calc budget_cap_check): disbursed-spend + outstanding-approved
    holds in this category + this charge must not exceed the cap. Tie at cap allowed.
    """
    category = expenditure["category"]
    cap = budget[f"{category.lower()}_cap_cents"]
    already = budget[f"{category.lower()}_spent_cents"]
    held = sum(
        x["amount_cents"]
        for x in expenditures_for_case(expenditure["case_id"])
        if x["budget_id"] == budget["id"]
        and x["category"] == category
        and x["status"] == "APPROVED"
        and x["id"] != expenditure["id"]
    )
    if already + held + expenditure["amount_cents"] > cap:
        raise err("ERR_BUDGET_CAP_EXCEEDED", "Expenditure would exceed the category cap")


def _check_and_encumber(expenditure):
    """Run cap + funds checks, then encumber the account. Raises on failure."""
    budget = db.budgets.get(expenditure["budget_id"])
    # Only an APPROVED budget governs spending.
    if budget is None or budget["status"] != "APPROVED":
        raise err("ERR_BUDGET_CAP_EXCEEDED", "No governing APPROVED budget")
    _check_budget_cap(expenditure, budget)
    account = _account_for_case(expenditure["case_id"])
    if account is None or account["available_balance_cents"] < expenditure["amount_cents"]:
        raise err("ERR_INSUFFICIENT_RESTRICTED_FUNDS", "Insufficient restricted funds")
    account["encumbered_cents"] += expenditure["amount_cents"]
    touch_account(account)


@bp.route("/gc/expenditures", methods=["POST"])
def create_expenditure():
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    budget_id = require_string(body, "budget_id")
    category = require_enum(body, "category", {"CARE", "MEDICAL", "ADMIN"})
    amount_cents = require_int(body, "amount_cents", exclusive_min=0)
    payee_name = require_string(body, "payee_name")
    expected_version = require_int(body, "expected_case_version")
    case = resolve_ref(db.cases, case_id)
    resolve_ref(db.budgets, budget_id)

    # OCC (priority 7) — before any state/fiscal check.
    if expected_version != case["version"]:
        raise err("ERR_STALE_CASE_VERSION", "expected_case_version does not match the case")

    requires_court = expenditure_requires_court_approval(amount_cents, category)
    record = {
        "case_id": case_id,
        "budget_id": budget_id,
        "category": category,
        "amount_cents": amount_cents,
        "payee_name": payee_name,
        "requires_court_approval": requires_court,
        "disbursed_at": None,
        "status": "REQUESTED",
    }
    stamp_create(record)

    with db.lock:
        if requires_court:
            record["status"] = "PENDING_COURT"
        else:
            # Auto-approve path: run fiscal checks and encumber.
            _check_and_encumber(record)
            record["status"] = "APPROVED"
        db.expenditures[record["id"]] = record
        # Creating an expenditure increments the case version by one.
        touch_case(case)
    return object_response(record, 201)


@bp.route("/gc/expenditures/<eid>", methods=["GET"])
def get_expenditure(eid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.expenditures, eid), 200)


@bp.route("/gc/expenditures", methods=["GET"])
def list_expenditures():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.expenditures.values())
    case_id = request.args.get("case_id")
    budget_id = request.args.get("budget_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [e for e in items if e["case_id"] == case_id]
    if budget_id is not None:
        items = [e for e in items if e["budget_id"] == budget_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/expenditures/<eid>/approve", methods=["POST"])
def approve_expenditure(eid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    exp = resolve_path(db.expenditures, eid)
    if exp["status"] != "PENDING_COURT":
        raise err("ERR_INVALID_STATE", "Expenditure must be PENDING_COURT")
    _check_and_encumber(exp)
    exp["status"] = "APPROVED"
    stamp_update(exp)
    return object_response(exp, 200)


@bp.route("/gc/expenditures/<eid>/deny", methods=["POST"])
def deny_expenditure(eid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    exp = resolve_path(db.expenditures, eid)
    if exp["status"] not in ("PENDING_COURT", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Expenditure must be PENDING_COURT or APPROVED")
    was_approved = exp["status"] == "APPROVED"
    exp["status"] = "DENIED"
    stamp_update(exp)
    if was_approved:
        # Release the hold.
        account = _account_for_case(exp["case_id"])
        if account is not None:
            account["encumbered_cents"] -= exp["amount_cents"]
            touch_account(account)
            case = db.cases.get(exp["case_id"])
            if case is not None:
                touch_case(case)
    return object_response(exp, 200)


@bp.route("/gc/expenditures/<eid>/disburse", methods=["POST"])
def disburse_expenditure(eid):
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    exp = resolve_path(db.expenditures, eid)
    if exp["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Expenditure must be APPROVED")
    account = _account_for_case(exp["case_id"])
    if account is None or account["status"] != "OPEN":
        raise err("ERR_ACCOUNT_FROZEN", "Restricted account is not OPEN")

    exp["disbursed_at"] = clock.now_iso()
    exp["status"] = "DISBURSED"
    stamp_update(exp)
    account["encumbered_cents"] -= exp["amount_cents"]
    account["principal_balance_cents"] -= exp["amount_cents"]
    touch_account(account)
    budget = db.budgets.get(exp["budget_id"])
    if budget is not None:
        budget[f"{exp['category'].lower()}_spent_cents"] += exp["amount_cents"]
        stamp_update(budget)
    case = db.cases.get(exp["case_id"])
    if case is not None:
        touch_case(case)
    return object_response(exp, 200)
