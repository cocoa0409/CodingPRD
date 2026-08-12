"""PriceTarget and MarketTick endpoints."""

from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, req_body, require_fields, req_int, req_number, req_enum,
    check_contract_month, pagination_params, page_slice, get_or_404, touch,
    parse_iso8601,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_target, ser_tick
from services import process_tick_cascade


bp = Blueprint("targets_ticks", __name__)


@bp.route("/advisory/price-targets", methods=["POST"])
def create_target():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["plan_id", "contract_month", "target_price", "increment_bushels"])
    plan_id = body["plan_id"]
    if not isinstance(plan_id, str):
        raise ApiError("ERR_VALIDATION", "plan_id must be a string", 400)
    cm = check_contract_month(body["contract_month"])
    tp = req_number(body, "target_price", positive=True)
    inc = req_int(body, "increment_bushels", positive=True)
    plan = DB.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", f"MarketingPlan not found: {plan_id}", 404)
    tid = db.new_id()
    now = db.now_iso()
    target = {
        "id": tid,
        "plan_id": plan_id,
        "contract_month": cm,
        "target_price": tp,
        "increment_bushels": inc,
        "status": "PENDING",
        "recommendation_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.price_targets[tid] = target
    return success_object(ser_target(target), status=201)


@bp.route("/advisory/price-targets/<targetId>", methods=["GET"])
def get_target(targetId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    t = get_or_404(DB.price_targets, targetId, "PriceTarget")
    plan = DB.plans.get(t["plan_id"])
    if plan:
        check_grower_ownership(user_id, role, plan["operation_id"])
    return success_object(ser_target(t))


@bp.route("/advisory/price-targets", methods=["GET"])
def list_targets():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    limit, offset = pagination_params()
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    rec_id = request.args.get("recommendation_id")
    items = list(DB.price_targets.values())
    if role == "Grower":
        items = [
            t for t in items
            if (DB.plans.get(t["plan_id"]) or {}).get("operation_id") == user_id
        ]
    if plan_id is not None:
        items = [t for t in items if t["plan_id"] == plan_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if rec_id is not None:
        items = [t for t in items if t.get("recommendation_id") == rec_id]
    items.sort(key=lambda t: t["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_target(t) for t in slice_], limit, offset, total)


@bp.route("/advisory/price-targets/<targetId>/cancel", methods=["POST"])
def cancel_target(targetId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    t = get_or_404(DB.price_targets, targetId, "PriceTarget")
    if t["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", f"PriceTarget in state {t['status']} cannot be cancelled", 409)
    t["status"] = "CANCELLED"
    touch(t)
    return success_object(ser_target(t))


# ---------------------------------------------------------------------------
# MarketTick
# ---------------------------------------------------------------------------

@bp.route("/advisory/market-ticks", methods=["POST"])
def create_tick():
    user_id, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = req_body()
    require_fields(body, ["commodity", "contract_month", "price", "kind", "price_date"])
    commodity = req_enum(body, "commodity", {"CORN", "SOYBEAN", "WHEAT"})
    cm = check_contract_month(body["contract_month"])
    price = req_number(body, "price", positive=True)
    kind = req_enum(body, "kind", {"QUOTE", "SETTLEMENT"})
    price_date = body["price_date"]
    if not isinstance(price_date, str):
        raise ApiError("ERR_VALIDATION", "price_date must be a string", 400)
    # Validate price_date parses as ISO date
    from helpers import parse_date
    parse_date(price_date)

    tid = db.new_id()
    tick = {
        "id": tid,
        "commodity": commodity,
        "contract_month": cm,
        "price": price,
        "kind": kind,
        "price_date": price_date,
        "created_at": db.now_iso(),
    }
    DB.market_ticks[tid] = tick
    # Cascade
    process_tick_cascade(tick)
    return success_object(ser_tick(tick), status=201)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/advisory/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = req_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"])
    db.set_logical_now(dt)
    # Return resulting current_utc in the 3-fractional-digit form
    return success_object({"current_utc": db.now_iso()})
