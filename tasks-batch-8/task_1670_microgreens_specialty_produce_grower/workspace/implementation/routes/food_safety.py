"""FoodSafetyPlan and SanitationLog endpoints (PRD 3.3 / 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_FOOD_SAFETY_NOT_APPROVED,
    ERR_FOOD_SAFETY_PLAN_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SANITATION_LOG_NOT_FOUND,
    ERR_TRAY_BATCH_NOT_FOUND,
)
from middleware import get_body, req_bool, req_int, req_str, require_roles
from response import success, serialize
from services import new_log, new_resource, touch
from routes.listing import list_response

bp = Blueprint("food_safety", __name__)

RW = ("Grower", "OpsManager")


@bp.post("/food-safety-plans")
@require_roles("OpsManager")
def create_plan():
    body = get_body()
    plan_code = req_str(body, "plan_code")
    water_test_current = req_bool(body, "water_test_current")
    sop_version = req_str(body, "sanitation_sop_version")
    for p in db.food_safety_plans.values():
        if p["plan_code"] == plan_code:
            raise ApiError(400, ERR_INVALID_REQUEST, "plan_code must be unique.")
    rec = new_resource(
        {
            "plan_code": plan_code,
            "water_test_current": water_test_current,
            "sanitation_sop_version": sop_version,
            "approved_at": None,
            "status": "DRAFT",
        }
    )
    db.food_safety_plans[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/food-safety-plans/<pid>")
@require_roles(*RW)
def get_plan(pid):
    rec = db.food_safety_plans.get(pid)
    if rec is None:
        raise ApiError(
            404, ERR_FOOD_SAFETY_PLAN_NOT_FOUND, "food safety plan id does not exist."
        )
    return success(serialize(rec), "object", 200)


@bp.post("/food-safety-plans/<pid>/approve")
@require_roles("OpsManager")
def approve_plan(pid):
    rec = db.food_safety_plans.get(pid)
    if rec is None:
        raise ApiError(
            404, ERR_FOOD_SAFETY_PLAN_NOT_FOUND, "food safety plan id does not exist."
        )
    if rec["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError(
            409, ERR_INVALID_STATE, "Only a DRAFT or SUSPENDED plan can be approved."
        )
    if not rec["water_test_current"]:
        raise ApiError(
            409,
            ERR_FOOD_SAFETY_NOT_APPROVED,
            "Approval requires a current passing water test.",
        )
    rec["status"] = "APPROVED"
    from response import now_iso

    rec["approved_at"] = now_iso()  # stamped from the logical clock
    touch(rec)
    return success(serialize(rec), "object", 200)


@bp.post("/food-safety-plans/<pid>/suspend")
@require_roles("OpsManager")
def suspend_plan(pid):
    rec = db.food_safety_plans.get(pid)
    if rec is None:
        raise ApiError(
            404, ERR_FOOD_SAFETY_PLAN_NOT_FOUND, "food safety plan id does not exist."
        )
    if rec["status"] != "APPROVED":
        raise ApiError(409, ERR_INVALID_STATE, "Only an APPROVED plan can be suspended.")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(serialize(rec), "object", 200)


@bp.post("/sanitation-logs")
@require_roles("Grower")
def create_sanitation_log():
    body = get_body()
    harvest_batch_id = req_str(body, "harvest_batch_id")
    surface_swab_passed = req_bool(body, "surface_swab_passed")
    wash_water_ppm = req_int(body, "wash_water_ppm")
    logged_by = req_str(body, "logged_by")
    if harvest_batch_id not in db.tray_batches:
        raise ApiError(404, ERR_TRAY_BATCH_NOT_FOUND, "tray batch id does not exist.")
    # Immutable append-only record: id + created_at only (PRD 2.4).
    rec = new_log(
        {
            "harvest_batch_id": harvest_batch_id,
            "surface_swab_passed": surface_swab_passed,
            "wash_water_ppm": wash_water_ppm,
            "logged_by": logged_by,
        }
    )
    db.sanitation_logs[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/sanitation-logs")
@require_roles(*RW)
def list_sanitation_logs():
    harvest_batch_id = request.args.get("harvest_batch_id")
    records = list(db.sanitation_logs.values())
    if harvest_batch_id is not None:
        records = [r for r in records if r["harvest_batch_id"] == harvest_batch_id]
    return list_response(records)


@bp.get("/sanitation-logs/<sid>")
@require_roles(*RW)
def get_sanitation_log(sid):
    rec = db.sanitation_logs.get(sid)
    if rec is None:
        raise ApiError(
            404, ERR_SANITATION_LOG_NOT_FOUND, "sanitation log id does not exist."
        )
    return success(serialize(rec), "object", 200)
