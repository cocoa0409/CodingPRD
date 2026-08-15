"""StorageLot endpoints + breakeven."""

import math
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, r2, to_float, req_body, require_fields, req_string, req_int, req_number,
    pagination_params, page_slice, get_or_404, touch, parse_date,
    latest_settlement_tick,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_lot


bp = Blueprint("storage", __name__)


@bp.route("/advisory/storage-lots", methods=["POST"])
def create_lot():
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    body = req_body()
    require_fields(body, [
        "operation_id", "bin_id", "bushels", "start_date", "planned_end_date",
        "cost_per_bushel_month", "annual_interest_rate",
    ])
    operation_id = body["operation_id"]
    if not isinstance(operation_id, str):
        raise ApiError("ERR_VALIDATION", "operation_id must be a string", 400)
    bin_id = req_string(body, "bin_id")
    bushels = req_int(body, "bushels", positive=True)
    start_raw = body["start_date"]
    end_raw = body["planned_end_date"]
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise ApiError("ERR_VALIDATION", "start_date/planned_end_date must be strings", 400)
    start = parse_date(start_raw)
    planned_end = parse_date(end_raw)
    if planned_end < start:
        raise ApiError("ERR_VALIDATION", "planned_end_date must be >= start_date", 400)
    cost = req_number(body, "cost_per_bushel_month", minimum=0)
    rate = req_number(body, "annual_interest_rate", minimum=0)

    op = DB.operations.get(operation_id)
    if op is None:
        raise ApiError("ERR_NOT_FOUND", f"GrowerOperation not found: {operation_id}", 404)
    check_grower_ownership(user_id, role, operation_id)

    # 7-day bin buffer rule against other STORED lots in same bin
    buffer_days = timedelta(days=7)
    for lot in DB.storage_lots.values():
        if lot["bin_id"] != bin_id:
            continue
        if lot["status"] != "STORED":
            continue
        if lot["operation_id"] != operation_id:
            # The rule says "same bin" — bin codes are elevator-scoped, so bin clash applies
            # regardless of operation? PRD §2.8: "a new lot in the same bin as an existing
            # STORED lot". Scaffold: "new lot in the same bin conflicts with a STORED lot".
            # We scope by same bin_id only.
            pass
        es = parse_date(lot["start_date"])
        ee = parse_date(lot["planned_end_date"])
        # allowed only if new.start >= existing.planned_end + 7d OR new.planned_end <= existing.start - 7d
        if start >= ee + buffer_days:
            continue
        if planned_end <= es - buffer_days:
            continue
        raise ApiError("ERR_STORAGE_BIN_OVERLAP", "Storage lot violates the 7-day bin buffer", 409)

    lid = db.new_id()
    now = db.now_iso()
    lot = {
        "id": lid,
        "operation_id": operation_id,
        "bin_id": bin_id,
        "bushels": bushels,
        "start_date": start_raw,
        "planned_end_date": end_raw,
        "cost_per_bushel_month": cost,
        "annual_interest_rate": rate,
        "actual_end_date": None,
        "status": "STORED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.storage_lots[lid] = lot
    return success_object(ser_lot(lot), status=201)


@bp.route("/advisory/storage-lots/<lotId>", methods=["GET"])
def get_lot(lotId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    lot = get_or_404(DB.storage_lots, lotId, "StorageLot")
    check_grower_ownership(user_id, role, lot["operation_id"])
    return success_object(ser_lot(lot))


@bp.route("/advisory/storage-lots", methods=["GET"])
def list_lots():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    limit, offset = pagination_params()
    operation_id = request.args.get("operation_id")
    bin_id = request.args.get("bin_id")
    status = request.args.get("status")
    items = list(DB.storage_lots.values())
    if role == "Grower":
        items = [l for l in items if l["operation_id"] == user_id]
    if operation_id is not None:
        items = [l for l in items if l["operation_id"] == operation_id]
    if bin_id is not None:
        items = [l for l in items if l["bin_id"] == bin_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: l["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_lot(l) for l in slice_], limit, offset, total)


@bp.route("/advisory/storage-lots/<lotId>/withdraw", methods=["POST"])
def withdraw_lot(lotId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    lot = get_or_404(DB.storage_lots, lotId, "StorageLot")
    check_grower_ownership(user_id, role, lot["operation_id"])
    if lot["status"] != "STORED":
        raise ApiError("ERR_INVALID_STATE", f"StorageLot in state {lot['status']} cannot be withdrawn", 409)
    lot["actual_end_date"] = db.logical_now().date().isoformat()
    lot["status"] = "WITHDRAWN"
    touch(lot)
    return success_object(ser_lot(lot))


@bp.route("/advisory/storage-lots/<lotId>/breakeven", methods=["GET"])
def breakeven(lotId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    lot = get_or_404(DB.storage_lots, lotId, "StorageLot")
    check_grower_ownership(user_id, role, lot["operation_id"])
    op = DB.operations[lot["operation_id"]]
    tick = latest_settlement_tick(op["primary_commodity"])
    if tick is None:
        raise ApiError("ERR_NO_SETTLEMENT_PRICE", "No SETTLEMENT MarketTick for the operation commodity", 409)
    harvest_value = D(tick["price"])

    start = parse_date(lot["start_date"])
    end_ref = parse_date(lot["actual_end_date"]) if lot.get("actual_end_date") else parse_date(lot["planned_end_date"])
    days = (end_ref - start).days
    months = math.ceil(days / 30) if days > 0 else 0
    bushels = D(lot["bushels"])
    carry = r2(bushels * D(lot["cost_per_bushel_month"]) * months)
    interest = r2(bushels * harvest_value * D(lot["annual_interest_rate"]) * months / 12)
    breakeven = r2((bushels * harvest_value + carry + interest) / bushels)
    result = {
        "months": months,
        "carry_dollars": to_float(carry),
        "interest_dollars": to_float(interest),
        "breakeven_sale_price": to_float(breakeven),
    }
    return success_object(result)
