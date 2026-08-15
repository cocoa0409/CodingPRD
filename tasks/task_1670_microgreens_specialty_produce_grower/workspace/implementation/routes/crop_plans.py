"""CropPlan and TrayBatch endpoints (PRD 3.3 / 3.4)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_BATCH_NOT_READY,
    ERR_CROP_PLAN_NOT_FOUND,
    ERR_FOOD_SAFETY_NOT_APPROVED,
    ERR_INSUFFICIENT_SEED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SANITATION_FAILED,
    ERR_SANITATION_NOT_LOGGED,
    ERR_SEED_LOT_NOT_FOUND,
    ERR_SEED_LOT_NOT_RELEASED,
    ERR_STALE_VERSION,
    ERR_TRAY_BATCH_NOT_FOUND,
    ERR_VARIETY_NOT_FOUND,
)
from middleware import get_body, opt_int, req_int, req_num, req_str, require_roles
from response import now_iso, success, serialize
from services import (
    expected_harvest_date,
    food_safety_satisfied,
    new_resource,
    q3,
    run_allocation,
    touch,
)
from routes.listing import list_response

bp = Blueprint("crop_plans", __name__)

RW = ("Grower", "OpsManager")
ADVANCE = {"SOWN": "GERMINATING", "GERMINATING": "GROWING", "GROWING": "READY"}


@bp.post("/crop-plans")
@require_roles("Grower")
def create_crop_plan():
    body = get_body()
    variety_id = req_str(body, "variety_id")
    planned_sow_date = req_str(body, "planned_sow_date")
    planned_tray_count = req_int(body, "planned_tray_count")
    seed_grams_required = req_int(body, "seed_grams_required")
    variety = db.varieties.get(variety_id)
    if variety is None:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    if planned_tray_count <= 0 or seed_grams_required <= 0:
        raise ApiError(
            400, ERR_INVALID_REQUEST, "tray count and seed grams must be positive."
        )
    # base_harvest_kg fixed at creation; not recomputed on later variety edits.
    base = q3(
        Decimal(planned_tray_count)
        * Decimal(variety["expected_yield_grams_per_tray"])
        / Decimal(1000)
    )
    rec = new_resource(
        {
            "variety_id": variety_id,
            "planned_sow_date": planned_sow_date,
            "planned_tray_count": planned_tray_count,
            "seed_grams_required": seed_grams_required,
            "status": "PLANNED",
            "base_harvest_kg": base,
            "sown_tray_count": 0,
        }
    )
    db.crop_plans[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/crop-plans")
@require_roles(*RW)
def list_crop_plans():
    variety_id = request.args.get("variety_id")
    status = request.args.get("status")
    records = list(db.crop_plans.values())
    if variety_id is not None:
        records = [r for r in records if r["variety_id"] == variety_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@bp.get("/crop-plans/<pid>")
@require_roles(*RW)
def get_crop_plan(pid):
    rec = db.crop_plans.get(pid)
    if rec is None:
        raise ApiError(404, ERR_CROP_PLAN_NOT_FOUND, "crop plan id does not exist.")
    return success(serialize(rec), "object", 200)


@bp.post("/crop-plans/<pid>/sow")
@require_roles("Grower")
def sow_crop_plan(pid):
    plan = db.crop_plans.get(pid)
    if plan is None:
        raise ApiError(404, ERR_CROP_PLAN_NOT_FOUND, "crop plan id does not exist.")
    body = get_body()
    seed_lot_id = req_str(body, "seed_lot_id")
    expected_version = opt_int(body, "expected_crop_plan_version")
    lot = db.seed_lots.get(seed_lot_id)
    if lot is None:
        raise ApiError(404, ERR_SEED_LOT_NOT_FOUND, "seed_lot_id does not exist.")
    # Guards run in the PRD 2.9 order: state -> food safety -> seed -> OCC.
    if plan["status"] != "PLANNED":
        raise ApiError(409, ERR_INVALID_STATE, "Only a PLANNED crop plan can be sown.")
    if not food_safety_satisfied():
        raise ApiError(
            409, ERR_FOOD_SAFETY_NOT_APPROVED, "No APPROVED food-safety plan in effect."
        )
    if lot["status"] != "RELEASED":
        raise ApiError(
            409, ERR_SEED_LOT_NOT_RELEASED, "Seed lot is not in RELEASED status."
        )
    if plan["seed_grams_required"] > lot["seeds_on_hand_grams"]:
        raise ApiError(
            409, ERR_INSUFFICIENT_SEED, "seed_grams_required exceeds seeds on hand."
        )
    if expected_version is not None and expected_version != plan["version"]:
        raise ApiError(
            412, ERR_STALE_VERSION, "expected_crop_plan_version does not match."
        )
    # Side effects: create TrayBatch SOWN, draw down the lot, bump the plan.
    lot["seeds_on_hand_grams"] -= plan["seed_grams_required"]
    if lot["seeds_on_hand_grams"] == 0:
        lot["status"] = "DEPLETED"
    touch(lot)
    variety = db.varieties.get(plan["variety_id"])
    days = variety["days_to_harvest"] if variety is not None else 0
    batch = new_resource(
        {
            "crop_plan_id": plan["id"],
            "seed_lot_id": lot["id"],
            "tray_count": plan["planned_tray_count"],
            "sown_at": now_iso(),
            "expected_harvest_date": expected_harvest_date(db.clock, days),
            "status": "SOWN",
            "harvested_kg": 0,
        }
    )
    db.tray_batches[batch["id"]] = batch
    plan["sown_tray_count"] = plan["planned_tray_count"]
    plan["status"] = "SOWING"
    touch(plan)
    return success(serialize(plan), "object", 200)


@bp.post("/crop-plans/<pid>/cancel")
@require_roles("Grower")
def cancel_crop_plan(pid):
    plan = db.crop_plans.get(pid)
    if plan is None:
        raise ApiError(404, ERR_CROP_PLAN_NOT_FOUND, "crop plan id does not exist.")
    if plan["status"] != "PLANNED":
        raise ApiError(
            409, ERR_INVALID_STATE, "Only a PLANNED crop plan can be cancelled."
        )
    plan["status"] = "CANCELLED"
    touch(plan)
    return success(serialize(plan), "object", 200)


@bp.get("/tray-batches")
@require_roles(*RW)
def list_tray_batches():
    crop_plan_id = request.args.get("crop_plan_id")
    seed_lot_id = request.args.get("seed_lot_id")
    status = request.args.get("status")
    records = list(db.tray_batches.values())
    if crop_plan_id is not None:
        records = [r for r in records if r["crop_plan_id"] == crop_plan_id]
    if seed_lot_id is not None:
        records = [r for r in records if r["seed_lot_id"] == seed_lot_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@bp.get("/tray-batches/<bid>")
@require_roles(*RW)
def get_tray_batch(bid):
    rec = db.tray_batches.get(bid)
    if rec is None:
        raise ApiError(404, ERR_TRAY_BATCH_NOT_FOUND, "tray batch id does not exist.")
    return success(serialize(rec), "object", 200)


@bp.post("/tray-batches/<bid>/advance")
@require_roles("Grower")
def advance_tray_batch(bid):
    batch = db.tray_batches.get(bid)
    if batch is None:
        raise ApiError(404, ERR_TRAY_BATCH_NOT_FOUND, "tray batch id does not exist.")
    nxt = ADVANCE.get(batch["status"])
    if nxt is None:
        raise ApiError(
            409, ERR_INVALID_STATE, "Batch cannot be advanced from its current state."
        )
    batch["status"] = nxt
    touch(batch)
    # The parent crop plan follows its batch: SOWING -> GROWING once germination
    # is confirmed, and GROWING -> READY when the batch reaches READY.
    plan = db.crop_plans.get(batch["crop_plan_id"])
    if plan is not None:
        if nxt == "GERMINATING" and plan["status"] == "SOWING":
            plan["status"] = "GROWING"
            touch(plan)
        elif nxt == "READY" and plan["status"] == "GROWING":
            plan["status"] = "READY"
            touch(plan)
    return success(serialize(batch), "object", 200)


@bp.post("/tray-batches/<bid>/harvest")
@require_roles("Grower")
def harvest_tray_batch(bid):
    batch = db.tray_batches.get(bid)
    if batch is None:
        raise ApiError(404, ERR_TRAY_BATCH_NOT_FOUND, "tray batch id does not exist.")
    body = get_body()
    harvested_kg = req_num(body, "harvested_kg")
    if harvested_kg < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "harvested_kg must be >= 0.")
    if batch["status"] != "READY":
        raise ApiError(
            409, ERR_BATCH_NOT_READY, "Harvest requires batch status READY."
        )
    logs = [
        l
        for l in db.sanitation_logs.values()
        if l["harvest_batch_id"] == batch["id"]
    ]
    if not logs:
        raise ApiError(
            409, ERR_SANITATION_NOT_LOGGED, "No SanitationLog exists for this batch."
        )
    latest = max(logs, key=lambda l: l["_seq"])
    if not latest["surface_swab_passed"] or not (50 <= latest["wash_water_ppm"] <= 200):
        raise ApiError(
            409,
            ERR_SANITATION_FAILED,
            "Sanitation log shows failed swab or ppm outside [50, 200].",
        )
    batch["status"] = "HARVESTED"
    batch["harvested_kg"] = q3(harvested_kg)
    touch(batch)
    plan = db.crop_plans.get(batch["crop_plan_id"])
    if plan is not None and plan["status"] != "HARVESTED":
        plan["status"] = "HARVESTED"
        touch(plan)
        # Allocation waterfall over open demand for this variety.
        run_allocation(plan["variety_id"], harvested_kg)
    return success(serialize(batch), "object", 200)
