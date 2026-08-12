"""BrokeragePosition and MarginAccount endpoints."""

from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, r2, to_float, req_body, require_fields, req_number,
    pagination_params, page_slice, get_or_404, touch, latest_settlement_tick,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_position, ser_account
from services import (
    recompute_plan_counters, recompute_margin_account, position_unrealized_pnl,
    position_realized_pnl,
)


bp = Blueprint("positions_margin", __name__)


# ---------------------------------------------------------------------------
# BrokeragePosition
# ---------------------------------------------------------------------------

@bp.route("/advisory/brokerage-positions/<positionId>", methods=["GET"])
def get_position(positionId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    p = get_or_404(DB.positions, positionId, "BrokeragePosition")
    check_grower_ownership(user_id, role, p["operation_id"])
    return success_object(ser_position(p))


@bp.route("/advisory/brokerage-positions", methods=["GET"])
def list_positions():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    limit, offset = pagination_params()
    operation_id = request.args.get("operation_id")
    margin_account_id = request.args.get("margin_account_id")
    recommendation_id = request.args.get("recommendation_id")
    status = request.args.get("status")
    items = list(DB.positions.values())
    if role == "Grower":
        items = [p for p in items if p["operation_id"] == user_id]
    if operation_id is not None:
        items = [p for p in items if p["operation_id"] == operation_id]
    if margin_account_id is not None:
        items = [p for p in items if p["margin_account_id"] == margin_account_id]
    if recommendation_id is not None:
        items = [p for p in items if p["recommendation_id"] == recommendation_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_position(p) for p in slice_], limit, offset, total)


@bp.route("/advisory/brokerage-positions/<positionId>/offset", methods=["POST"])
def offset_position(positionId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    p = get_or_404(DB.positions, positionId, "BrokeragePosition")
    if p["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Position in state {p['status']} cannot be offset", 409)
    op = DB.operations[p["operation_id"]]
    tick = latest_settlement_tick(op["primary_commodity"], p["contract_month"])
    if tick is None:
        raise ApiError("ERR_NO_SETTLEMENT_PRICE", "No SETTLEMENT MarketTick for the required commodity/month", 409)
    exit_price = D(tick["price"])
    realized = position_realized_pnl(p, exit_price)
    p["exit_price"] = exit_price
    p["realized_pnl"] = realized
    p["status"] = "OFFSET"
    touch(p)
    account = DB.margin_accounts[p["margin_account_id"]]
    account["cash_balance"] = to_float(D(account["cash_balance"]) + realized)
    recompute_margin_account(account)
    # call status re-evaluated: equity >= initial -> FUNDED
    if account["status"] == "CALL_OUTSTANDING":
        if D(account["margin_equity"]) >= D(account["initial_margin_required"]):
            account["status"] = "FUNDED"
            account["margin_call_amount"] = 0.0
            touch(account)
        else:
            # keep call outstanding, update margin_call_amount
            account["margin_call_amount"] = to_float(
                r2(D(account["initial_margin_required"]) - D(account["margin_equity"]))
            )
            touch(account)
    plan = DB.plans.get(p.get("plan_id"))
    if plan:
        recompute_plan_counters(plan)
    return success_object(ser_position(p))


# ---------------------------------------------------------------------------
# MarginAccount
# ---------------------------------------------------------------------------

@bp.route("/advisory/margin-accounts", methods=["POST"])
def create_account():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["operation_id", "initial_funding"])
    operation_id = body["operation_id"]
    if not isinstance(operation_id, str):
        raise ApiError("ERR_VALIDATION", "operation_id must be a string", 400)
    initial = req_number(body, "initial_funding", minimum=0)
    op = DB.operations.get(operation_id)
    if op is None:
        raise ApiError("ERR_NOT_FOUND", f"GrowerOperation not found: {operation_id}", 404)
    existing = next(
        (a for a in DB.margin_accounts.values() if a["operation_id"] == operation_id),
        None,
    )
    if existing is not None:
        raise ApiError("ERR_INVALID_STATE", "Margin account already exists for the operation", 409)
    aid = db.new_id()
    now = db.now_iso()
    account = {
        "id": aid,
        "operation_id": operation_id,
        "cash_balance": initial,
        "initial_margin_required": 0.0,
        "maintenance_margin_required": 0.0,
        "margin_equity": initial,
        "margin_call_amount": 0.0,
        "status": "FUNDED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.margin_accounts[aid] = account
    return success_object(ser_account(account), status=201)


@bp.route("/advisory/margin-accounts/<accountId>", methods=["GET"])
def get_account(accountId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    a = get_or_404(DB.margin_accounts, accountId, "MarginAccount")
    check_grower_ownership(user_id, role, a["operation_id"])
    return success_object(ser_account(a))


@bp.route("/advisory/margin-accounts", methods=["GET"])
def list_accounts():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    limit, offset = pagination_params()
    operation_id = request.args.get("operation_id")
    status = request.args.get("status")
    items = list(DB.margin_accounts.values())
    if role == "Grower":
        items = [a for a in items if a["operation_id"] == user_id]
    if operation_id is not None:
        items = [a for a in items if a["operation_id"] == operation_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_account(a) for a in slice_], limit, offset, total)


@bp.route("/advisory/margin-accounts/<accountId>/fund", methods=["POST"])
def fund_account(accountId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    a = get_or_404(DB.margin_accounts, accountId, "MarginAccount")
    check_grower_ownership(user_id, role, a["operation_id"])
    body = req_body()
    require_fields(body, ["amount"])
    amount = req_number(body, "amount", positive=True)
    a["cash_balance"] = to_float(D(a["cash_balance"]) + amount)
    recompute_margin_account(a)
    # Re-evaluate status
    if a["status"] == "CALL_OUTSTANDING":
        if D(a["margin_equity"]) >= D(a["initial_margin_required"]):
            a["status"] = "FUNDED"
            a["margin_call_amount"] = 0.0
            touch(a)
        else:
            a["margin_call_amount"] = to_float(
                r2(D(a["initial_margin_required"]) - D(a["margin_equity"]))
            )
            touch(a)
    elif a["status"] == "RESTRICTED":
        if D(a["cash_balance"]) >= 0:
            a["status"] = "FUNDED"
            touch(a)
    return success_object(ser_account(a))


@bp.route("/advisory/margin-accounts/<accountId>/liquidate", methods=["POST"])
def liquidate_account(accountId):
    user_id, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    a = get_or_404(DB.margin_accounts, accountId, "MarginAccount")
    if a["status"] != "CALL_OUTSTANDING":
        raise ApiError("ERR_LIQUIDATION_NOT_REQUIRED", "Account is not CALL_OUTSTANDING", 409)

    # (1) Mark every OPEN position at latest settlement, freeze prices
    op_positions = [p for p in DB.positions.values() if p["margin_account_id"] == a["id"] and p["status"] == "OPEN"]
    frozen_marks = {}
    for p in op_positions:
        op = DB.operations[p["operation_id"]]
        tick = latest_settlement_tick(op["primary_commodity"], p["contract_month"])
        if tick is None:
            raise ApiError("ERR_NO_SETTLEMENT_PRICE", "No SETTLEMENT MarketTick for an open position", 409)
        frozen_marks[p["id"]] = D(tick["price"])
        p["unrealized_pnl"] = to_float(position_unrealized_pnl(p, frozen_marks[p["id"]]))
        touch(p)
    recompute_margin_account(a)

    def deficit():
        return D(a["margin_equity"]) < D(a["maintenance_margin_required"])

    # (3) candidate order: initial_margin_dollars DESC, tie created_at ASC
    candidates = sorted(
        op_positions,
        key=lambda p: (-D(p["initial_margin_dollars"]), p["created_at"]),
    )

    # (4) while deficit and candidates remain: liquidate head
    for pos in candidates:
        if not deficit():
            break
        if pos["status"] != "OPEN":
            continue
        exit_price = frozen_marks[pos["id"]]
        realized = position_realized_pnl(pos, exit_price)
        pos["exit_price"] = exit_price
        pos["realized_pnl"] = realized
        pos["status"] = "LIQUIDATED"
        touch(pos)
        a["cash_balance"] = to_float(D(a["cash_balance"]) + realized)
        recompute_margin_account(a)
        plan = DB.plans.get(pos.get("plan_id"))
        if plan:
            recompute_plan_counters(plan)

    # (5) Post-state
    remaining_open = [p for p in DB.positions.values() if p["margin_account_id"] == a["id"] and p["status"] == "OPEN"]
    if remaining_open:
        # positions remain and equity >= maintenance (loop stopped due to deficit false)
        a["status"] = "FUNDED"
        a["margin_call_amount"] = 0.0
        touch(a)
    else:
        if D(a["margin_equity"]) >= 0:
            a["status"] = "FUNDED"
            a["margin_call_amount"] = 0.0
            touch(a)
        else:
            a["status"] = "RESTRICTED"
            a["margin_call_amount"] = 0.0
            touch(a)
    return success_object(ser_account(a))
