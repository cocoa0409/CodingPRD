"""Blend orders: draft, approve (SoD), execute (mints result lot), cancel (PRD §3.7)."""

from decimal import Decimal

from flask import Blueprint, request

from db import public, sort_by_creation, stamp_new, store, touch
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import check_grower_on_blend, get_blend, get_lot
from services.calculations import blend_required_low_lbs, blend_result
from validation import get_body, paginate, req_num

bp = Blueprint("blends", __name__)

READ_ROLES = {"ElevatorManager", "Grower"}
BLEND_TERMINAL = {"EXECUTED", "CANCELLED"}


def _check_source_blendable(lot):
    if lot["status"] == "DAMAGE_HOLD":
        raise_err("ERR_LOT_ON_DAMAGE_HOLD", "Operation blocked while lot is in DAMAGE_HOLD")
    if lot["status"] in ("LOADED_OUT", "BLENDED_OUT"):
        raise_err("ERR_ALREADY_TERMINAL", "Lot is in a terminal state")
    if lot["status"] != "DRIED":
        raise_err("ERR_INVALID_STATE", "Blend sources must be DRIED")


@bp.post("/blend-orders")
def create_blend():
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    body = get_body()
    # priority 4: body FK existence (high then low, input order)
    high = None
    low = None
    if body.get("high_moisture_lot_id") is not None:
        high = get_lot(body["high_moisture_lot_id"])
    if body.get("low_moisture_lot_id") is not None:
        low = get_lot(body["low_moisture_lot_id"])
    # priority 5: shape
    if not isinstance(body.get("high_moisture_lot_id"), str) or not body["high_moisture_lot_id"]:
        raise_err("ERR_INVALID_REQUEST", "Field high_moisture_lot_id is required")
    if not isinstance(body.get("low_moisture_lot_id"), str) or not body["low_moisture_lot_id"]:
        raise_err("ERR_INVALID_REQUEST", "Field low_moisture_lot_id is required")
    target = req_num(body, "target_moisture_pct")
    # priority 6: both sources DRIED
    _check_source_blendable(high)
    _check_source_blendable(low)
    # priority 10: target strictly between the two source moistures
    high_m = Decimal(str(high["current_moisture_pct"]))
    low_m = Decimal(str(low["current_moisture_pct"]))
    t = Decimal(str(target))
    if not (low_m < t < high_m):
        raise_err("ERR_TARGET_MOISTURE_INVALID", "Target must lie strictly between the two source moistures")
    if high["commodity"] != low["commodity"]:
        raise_err("ERR_BLEND_COMMODITY_MISMATCH", "Blend sources have different commodities")
    if high["current_owner_id"] != low["current_owner_id"]:
        raise_err("ERR_BLEND_OWNERSHIP_MISMATCH", "Blend sources have different current owners")
    required_low = blend_required_low_lbs(high, low, target)
    rec = stamp_new(
        {
            "high_moisture_lot_id": high["id"],
            "low_moisture_lot_id": low["id"],
            "target_moisture_pct": target,
            "required_low_lot_lbs": required_low,
            "result_lot_id": None,
            "result_weight_lbs": None,
            "result_moisture_pct": None,
            "status": "DRAFT",
            "created_by_user_id": ctx["user_id"],
            "approved_by_user_id": None,
        }
    )
    store.blends[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.get("/blend-orders")
def list_blends():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = list(store.blends.values())
    if ctx["role"] == "Grower":
        records = [
            r for r in records
            if store.lots.get(r["high_moisture_lot_id"]) is not None
            and store.lots[r["high_moisture_lot_id"]]["customer_id"] == ctx["user_id"]
        ]
    for field in ("high_moisture_lot_id", "low_moisture_lot_id", "result_lot_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/blend-orders/<bid>")
def get_one_blend(bid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_blend(bid)
    check_grower_on_blend(ctx, rec)
    return success(public(rec))


@bp.post("/blend-orders/<bid>/approve")
def approve_blend(bid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_blend(bid)
    if rec["status"] in BLEND_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Blend order is in a terminal state")
    if rec["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT blend order may be approved")
    # priority 8: approver must differ from creator (§2.8)
    if rec["created_by_user_id"] == ctx["user_id"]:
        raise_err("ERR_BLEND_APPROVER_CONFLICT", "Blend-order approver equals its creator")
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = ctx["user_id"]
    touch(rec)
    return success(public(rec))


@bp.post("/blend-orders/<bid>/execute")
def execute_blend(bid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_blend(bid)
    if rec["status"] in BLEND_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Blend order is in a terminal state")
    if rec["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED blend order may be executed")
    high = store.lots.get(rec["high_moisture_lot_id"])
    low = store.lots.get(rec["low_moisture_lot_id"])
    # execution re-verifies the live lots; any non-DRIED source is ERR_INVALID_STATE
    if high is None or low is None or high["status"] != "DRIED" or low["status"] != "DRIED":
        raise_err("ERR_INVALID_STATE", "Both source lots must still stand DRIED")
    if rec["required_low_lot_lbs"] > low["final_dry_weight_lbs"]:
        raise_err("ERR_INSUFFICIENT_BLEND_GRAIN", "required_low_lot_lbs exceeds the low-moisture lot's available final weight")
    weight, moisture = blend_result(high, low, rec["required_low_lot_lbs"])
    # mint the result lot: sources' commodity, customer, and owner
    result = stamp_new(
        {
            "customer_id": high["customer_id"],
            "commodity": high["commodity"],
            "gross_weight_lbs": weight,
            "tare_weight_lbs": 0,
            "wet_net_weight_lbs": weight,
            "foreign_material_pct": 0.0,
            "target_moisture_pct": rec["target_moisture_pct"],
            "intake_moisture_pct": moisture,
            "current_moisture_pct": moisture,
            "certified_test_id": None,
            "provisional_shrink_pct": None,
            "provisional_dry_weight_lbs": None,
            "final_dry_weight_lbs": weight,
            "final_shrink_pct": None,
            "shrink_variance_lbs": None,
            "status": "DRIED",
            "ownership": "GROWER_HELD",
            "current_owner_id": high["current_owner_id"],
        }
    )
    store.lots[result["id"]] = result
    # consume both sources
    for lot in (high, low):
        lot["status"] = "BLENDED_OUT"
        touch(lot)
    rec["result_lot_id"] = result["id"]
    rec["result_weight_lbs"] = weight
    rec["result_moisture_pct"] = moisture
    rec["status"] = "EXECUTED"
    touch(rec)
    return success(public(rec))


@bp.post("/blend-orders/<bid>/cancel")
def cancel_blend(bid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_blend(bid)
    if rec["status"] in BLEND_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Blend order is in a terminal state")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(public(rec))
