"""HedgeRecommendation endpoints."""

from decimal import Decimal
from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, req_body, require_fields, req_int, req_number, opt_number, req_enum,
    opt_string, check_contract_month, pagination_params, page_slice, get_or_404, touch,
    latest_settlement_tick, to_float,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_recommendation, ser_position
from services import (
    recompute_plan_counters, position_initial_margin, position_maintenance_margin,
    position_unrealized_pnl, recompute_margin_account,
)


bp = Blueprint("recommendations", __name__)


@bp.route("/advisory/hedge-recommendations", methods=["POST"])
def create_recommendation():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["plan_id", "instrument", "contract_month", "bushels"])
    plan_id = body["plan_id"]
    if not isinstance(plan_id, str):
        raise ApiError("ERR_VALIDATION", "plan_id must be a string", 400)
    instrument = req_enum(body, "instrument", {"FUTURES_SHORT", "LONG_PUT"})
    cm = check_contract_month(body["contract_month"])
    bushels = req_int(body, "bushels", positive=True)
    strike = opt_number(body, "strike_price")
    premium = opt_number(body, "premium_per_bushel")
    rationale = opt_string(body, "rationale")

    if instrument == "LONG_PUT":
        if strike is None or premium is None:
            raise ApiError("ERR_VALIDATION", "strike_price and premium_per_bushel required for LONG_PUT", 400)
    else:
        # FUTURES_SHORT: strike/premium do not apply
        if strike is not None or premium is not None:
            raise ApiError("ERR_VALIDATION", "strike_price/premium_per_bushel do not apply to FUTURES_SHORT", 400)

    plan = DB.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", f"MarketingPlan not found: {plan_id}", 404)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"Plan in state {plan['status']} cannot accept new recommendations", 409)

    rid = db.new_id()
    now = db.now_iso()
    rec = {
        "id": rid,
        "plan_id": plan_id,
        "price_target_id": None,
        "instrument": instrument,
        "contract_month": cm,
        "bushels": bushels,
        "strike_price": strike,
        "premium_per_bushel": premium,
        "rationale": rationale,
        "created_by_user_id": user_id,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.recommendations[rid] = rec
    recompute_plan_counters(plan)
    return success_object(ser_recommendation(rec), status=201)


@bp.route("/advisory/hedge-recommendations/<recommendationId>", methods=["GET"])
def get_recommendation(recommendationId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    r = get_or_404(DB.recommendations, recommendationId, "HedgeRecommendation")
    plan = DB.plans.get(r["plan_id"])
    if plan:
        check_grower_ownership(user_id, role, plan["operation_id"])
    return success_object(ser_recommendation(r))


@bp.route("/advisory/hedge-recommendations", methods=["GET"])
def list_recommendations():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    limit, offset = pagination_params()
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    pt_id = request.args.get("price_target_id")
    items = list(DB.recommendations.values())
    if role == "Grower":
        items = [
            r for r in items
            if (DB.plans.get(r["plan_id"]) or {}).get("operation_id") == user_id
        ]
    if plan_id is not None:
        items = [r for r in items if r["plan_id"] == plan_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if pt_id is not None:
        items = [r for r in items if r.get("price_target_id") == pt_id]
    items.sort(key=lambda r: r["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_recommendation(r) for r in slice_], limit, offset, total)


@bp.route("/advisory/hedge-recommendations/<recommendationId>/accept", methods=["POST"])
def accept_recommendation(recommendationId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    r = get_or_404(DB.recommendations, recommendationId, "HedgeRecommendation")
    plan = DB.plans.get(r["plan_id"])
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", f"MarketingPlan not found: {r['plan_id']}", 404)
    check_grower_ownership(user_id, role, plan["operation_id"])
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", f"Recommendation in state {r['status']} cannot be accepted", 409)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"Plan in state {plan['status']} cannot accept recommendations", 409)
    op = DB.operations[plan["operation_id"]]
    if op["over_sold_flag"]:
        raise ApiError("ERR_OVER_SOLD_POSITION", "Operation over_sold_flag is set", 409)
    # Coverage cap: hedged + this.bushels + priced <= cap (equality allowed)
    if plan["hedged_bushels"] + r["bushels"] + plan["priced_contract_bushels"] > plan["coverage_cap_bushels"]:
        raise ApiError("ERR_COVERAGE_CAP_EXCEEDED", "Coverage cap exceeded", 409)
    r["status"] = "ACCEPTED"
    touch(r)
    recompute_plan_counters(plan)
    return success_object(ser_recommendation(r))


@bp.route("/advisory/hedge-recommendations/<recommendationId>/reject", methods=["POST"])
def reject_recommendation(recommendationId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    r = get_or_404(DB.recommendations, recommendationId, "HedgeRecommendation")
    plan = DB.plans.get(r["plan_id"])
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", f"MarketingPlan not found: {r['plan_id']}", 404)
    check_grower_ownership(user_id, role, plan["operation_id"])
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", f"Recommendation in state {r['status']} cannot be rejected", 409)
    r["status"] = "REJECTED"
    touch(r)
    if r.get("price_target_id"):
        pt = DB.price_targets.get(r["price_target_id"])
        if pt and pt["status"] == "TRIGGERED":
            pt["status"] = "LAPSED"
            touch(pt)
    recompute_plan_counters(plan)
    return success_object(ser_recommendation(r))


@bp.route("/advisory/hedge-recommendations/<recommendationId>/execute", methods=["POST"])
def execute_recommendation(recommendationId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    r = get_or_404(DB.recommendations, recommendationId, "HedgeRecommendation")
    plan = DB.plans.get(r["plan_id"])
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", f"MarketingPlan not found: {r['plan_id']}", 404)
    if r["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", f"Recommendation in state {r['status']} cannot be executed", 409)
    op = DB.operations[plan["operation_id"]]
    # Margin account status gate
    account = next(
        (a for a in DB.margin_accounts.values() if a["operation_id"] == op["id"]),
        None,
    )
    if account is None:
        raise ApiError("ERR_NOT_FOUND", "MarginAccount for the operation does not exist", 404)
    if account["status"] == "CALL_OUTSTANDING":
        raise ApiError("ERR_MARGIN_CALL_OUTSTANDING", "Margin account has an outstanding call", 409)
    if account["status"] == "RESTRICTED":
        raise ApiError("ERR_MARGIN_ACCOUNT_RESTRICTED", "Margin account is restricted", 409)
    # Settlement tick
    tick = latest_settlement_tick(op["primary_commodity"], r["contract_month"])
    if tick is None:
        raise ApiError("ERR_NO_SETTLEMENT_PRICE", "No SETTLEMENT MarketTick for the required commodity/month", 409)
    entry_price = D(tick["price"])

    # Compute margin deltas for new position
    im = position_initial_margin(r["instrument"], r["bushels"], r.get("premium_per_bushel"))
    mm = position_maintenance_margin(r["instrument"], r["bushels"], r.get("premium_per_bushel"))
    unreal = position_unrealized_pnl(
        {
            "instrument": r["instrument"],
            "entry_price": entry_price,
            "bushels": r["bushels"],
            "strike_price": r.get("strike_price"),
            "premium_per_bushel": r.get("premium_per_bushel"),
        },
        entry_price,
    )

    # Post-trade solvency: simulate after opening
    premium_cost = Decimal("0")
    if r["instrument"] == "LONG_PUT":
        premium_cost = D(r["bushels"]) * D(r["premium_per_bushel"])
    new_cash = D(account["cash_balance"]) - premium_cost
    existing_open = [p for p in DB.positions.values() if p["margin_account_id"] == account["id"] and p["status"] == "OPEN"]
    new_im_total = sum(D(p["initial_margin_dollars"]) for p in existing_open) + im
    new_mm_total = sum(D(p["maintenance_margin_dollars"]) for p in existing_open) + mm
    new_unreal_total = sum(D(p["unrealized_pnl"]) for p in existing_open) + unreal
    new_equity = new_cash + new_unreal_total
    if new_cash < new_im_total or new_equity < new_mm_total:
        raise ApiError("ERR_INSUFFICIENT_MARGIN_EQUITY", "Post-execution solvency check failed", 409)

    # Mint position
    pid = db.new_id()
    now = db.now_iso()
    pos = {
        "id": pid,
        "recommendation_id": r["id"],
        "plan_id": plan["id"],
        "operation_id": op["id"],
        "margin_account_id": account["id"],
        "instrument": r["instrument"],
        "contract_month": r["contract_month"],
        "bushels": r["bushels"],
        "strike_price": r.get("strike_price"),
        "premium_per_bushel": r.get("premium_per_bushel"),
        "entry_price": entry_price,
        "exit_price": None,
        "initial_margin_dollars": im,
        "maintenance_margin_dollars": mm,
        "unrealized_pnl": unreal,
        "realized_pnl": None,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.positions[pid] = pos

    if r["instrument"] == "LONG_PUT":
        account["cash_balance"] = to_float(new_cash)
    recompute_margin_account(account)

    r["status"] = "EXECUTED"
    touch(r)
    if r.get("price_target_id"):
        pt = DB.price_targets.get(r["price_target_id"])
        if pt and pt["status"] == "TRIGGERED":
            pt["status"] = "FILLED"
            touch(pt)
    recompute_plan_counters(plan)
    return success_object(ser_position(pos), status=200)
