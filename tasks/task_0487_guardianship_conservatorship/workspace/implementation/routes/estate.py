"""RestrictedAccount, Inventory, and Budget routes."""

from flask import Blueprint, request

from db import db, stamp_create, stamp_update
from errors import err
from middleware import get_identity, require_role
from response import object_response, array_response
from validators import (
    ALL_ROLES,
    get_json_body,
    require_string,
    require_int,
    parse_pagination,
    paginate,
)
from services import (
    resolve_path,
    resolve_ref,
    accounts_for_case,
    touch_account,
    touch_case,
    budgets_for_case,
)

bp = Blueprint("estate", __name__)


# ---------------------------------------------------------------------------
# RestrictedAccount
# ---------------------------------------------------------------------------
@bp.route("/gc/restricted-accounts", methods=["POST"])
def create_account():
    _, role = get_identity()
    require_role(role, ["Fiduciary", "CourtClerk"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    institution_name = require_string(body, "institution_name")
    resolve_ref(db.cases, case_id)

    record = {
        "case_id": case_id,
        "institution_name": institution_name,
        "principal_balance_cents": 0,
        "encumbered_cents": 0,
        "available_balance_cents": 0,
        "status": "OPEN",
    }
    stamp_create(record)
    with db.lock:
        db.restricted_accounts[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/restricted-accounts/<aid>", methods=["GET"])
def get_account(aid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.restricted_accounts, aid), 200)


@bp.route("/gc/restricted-accounts", methods=["GET"])
def list_accounts():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.restricted_accounts.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [a for a in items if a["case_id"] == case_id]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
@bp.route("/gc/inventories", methods=["POST"])
def create_inventory():
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    real_property = require_int(body, "real_property_cents", minimum=0)
    liquid_assets = require_int(body, "liquid_assets_cents", minimum=0)
    tangible = require_int(body, "tangible_property_cents", minimum=0)
    resolve_ref(db.cases, case_id)

    record = {
        "case_id": case_id,
        "real_property_cents": real_property,
        "liquid_assets_cents": liquid_assets,
        "tangible_property_cents": tangible,
        "total_estate_cents": real_property + liquid_assets + tangible,
        "status": "DRAFT",
    }
    stamp_create(record)
    with db.lock:
        db.inventories[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/inventories/<iid>", methods=["GET"])
def get_inventory(iid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.inventories, iid), 200)


@bp.route("/gc/inventories", methods=["GET"])
def list_inventories():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.inventories.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [i for i in items if i["case_id"] == case_id]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/inventories/<iid>/file", methods=["POST"])
def file_inventory(iid):
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    inv = resolve_path(db.inventories, iid)
    if inv["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Inventory must be DRAFT")
    case = db.cases.get(inv["case_id"])
    if case is None or case["status"] != "ACTIVE":
        raise err("ERR_CASE_NOT_ACTIVE", "Case must be ACTIVE to file inventory")
    inv["status"] = "FILED"
    stamp_update(inv)
    return object_response(inv, 200)


@bp.route("/gc/inventories/<iid>/approve", methods=["POST"])
def approve_inventory(iid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    inv = resolve_path(db.inventories, iid)
    if inv["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Inventory must be FILED")
    open_accounts = [a for a in accounts_for_case(inv["case_id"]) if a["status"] == "OPEN"]
    if not open_accounts:
        raise err("ERR_NO_RESTRICTED_ACCOUNT", "An OPEN restricted account is required")
    account = open_accounts[0]
    inv["status"] = "APPROVED"
    stamp_update(inv)
    account["principal_balance_cents"] += inv["liquid_assets_cents"]
    touch_account(account)
    case = db.cases.get(inv["case_id"])
    if case is not None:
        touch_case(case)
    return object_response(inv, 200)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
@bp.route("/gc/budgets", methods=["POST"])
def create_budget():
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    period_year = require_int(body, "period_year")
    care_cap = require_int(body, "care_cap_cents", minimum=0)
    medical_cap = require_int(body, "medical_cap_cents", minimum=0)
    admin_cap = require_int(body, "admin_cap_cents", minimum=0)
    resolve_ref(db.cases, case_id)

    record = {
        "case_id": case_id,
        "period_year": period_year,
        "care_cap_cents": care_cap,
        "medical_cap_cents": medical_cap,
        "admin_cap_cents": admin_cap,
        "care_spent_cents": 0,
        "medical_spent_cents": 0,
        "admin_spent_cents": 0,
        "status": "DRAFT",
    }
    stamp_create(record)
    with db.lock:
        db.budgets[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/budgets/<bid>", methods=["GET"])
def get_budget(bid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.budgets, bid), 200)


@bp.route("/gc/budgets", methods=["GET"])
def list_budgets():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.budgets.values())
    case_id = request.args.get("case_id")
    period_year = request.args.get("period_year")
    if case_id is not None:
        items = [b for b in items if b["case_id"] == case_id]
    if period_year is not None:
        try:
            py = int(period_year)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "period_year must be an integer")
        items = [b for b in items if b["period_year"] == py]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/budgets/<bid>/submit", methods=["POST"])
def submit_budget(bid):
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    budget = resolve_path(db.budgets, bid)
    if budget["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Budget must be DRAFT")
    budget["status"] = "SUBMITTED"
    stamp_update(budget)
    return object_response(budget, 200)


@bp.route("/gc/budgets/<bid>/approve", methods=["POST"])
def approve_budget(bid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    body = get_json_body()
    # OCC field is required for this write (PRD §2.8). Missing/ill-typed -> 400.
    expected_version = require_int(body, "expected_case_version")
    budget = resolve_path(db.budgets, bid)
    case = db.cases.get(budget["case_id"])

    # Validation order (PRD §3.9): OCC (priority 7) before invalid_state (9) and
    # case_not_active. Stale version surfaces first.
    if case is None or expected_version != case["version"]:
        raise err("ERR_STALE_CASE_VERSION", "expected_case_version does not match the case")
    if budget["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Budget must be SUBMITTED")
    if case["status"] != "ACTIVE":
        raise err("ERR_CASE_NOT_ACTIVE", "Case must be ACTIVE to approve a budget")

    budget["status"] = "APPROVED"
    stamp_update(budget)
    # Supersede any other APPROVED budget on the same case for the same year.
    for other in budgets_for_case(case["id"]):
        if (
            other["id"] != budget["id"]
            and other["period_year"] == budget["period_year"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "SUPERSEDED"
            stamp_update(other)
    # Increment the case version by one.
    touch_case(case)
    return object_response(budget, 200)
