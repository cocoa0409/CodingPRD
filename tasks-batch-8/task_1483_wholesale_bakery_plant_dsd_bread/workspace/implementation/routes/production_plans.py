"""ProductionPlan endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, parse_iso_date, make_entity, touch, lookup,
    list_response, public,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_DUPLICATE_PLAN_DATE, ERR_PLAN_NOT_RELEASABLE, ERR_SANITATION_REQUIRED,
)
from services.calculations import compute_production_requirement
from services.cascades import cascade_plan_created

bp = Blueprint("production_plans", __name__)


@bp.route("/bakery/production-plans", methods=["POST"])
def create_plan():
    _, role = get_auth()
    require_role(role, {"Planner"})
    data = body()
    plant_id = req_string(data, "plant_id")
    plant = lookup(DB.plants, plant_id, "plant")
    bake_date = req_string(data, "bake_date")
    parse_iso_date(bake_date, "bake_date")
    if "expected_plant_version" not in data:
        raise ApiError(ERR_INVALID_REQUEST, "expected_plant_version is required", 400)
    expected = data["expected_plant_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_plant_version must be an integer", 400)

    # OCC check
    if expected != plant.get("version"):
        raise ApiError(ERR_STALE_VERSION, "Stale plant version", 412)

    # Duplicate live plan guard
    for plan in DB.production_plans.values():
        if (
            plan.get("plant_id") == plant_id
            and plan.get("bake_date") == bake_date
            and plan.get("status") != "DRAFT"
            and plan.get("status") != "SUPERSEDED"
        ):
            raise ApiError(ERR_DUPLICATE_PLAN_DATE, "A live plan already exists for this plant+bake_date", 409)

    plan = make_entity({
        "plant_id": plant_id,
        "bake_date": bake_date,
        "status": "DRAFT",
        "planned_units_by_product": {},
        "batches_required_by_product": {},
        "total_planned_units": 0,
        "flour_required_kg": 0,
        "shortfall_units": 0,
    })
    DB.production_plans[plan["id"]] = plan

    cascade_plan_created(plant, bake_date, plan["id"])
    touch(plant)
    return success_object(public(plan), status=201)


@bp.route("/bakery/production-plans/<pid>", methods=["GET"])
def get_plan(pid):
    get_auth()
    plan = lookup(DB.production_plans, pid, "production plan")
    return success_object(public(plan))


@bp.route("/bakery/production-plans", methods=["GET"])
def list_plans():
    get_auth()
    filters = {
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(DB.production_plans.values()), filters)


@bp.route("/bakery/production-plans/<pid>/lock", methods=["POST"])
def lock_plan(pid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    plan = lookup(DB.production_plans, pid, "production plan")
    if plan.get("status") != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Plan is not DRAFT", 409)
    planned, batches_req, total, flour_kg = compute_production_requirement(plan)
    plan["planned_units_by_product"] = planned
    plan["batches_required_by_product"] = batches_req
    plan["total_planned_units"] = total
    plan["flour_required_kg"] = flour_kg
    plan["status"] = "LOCKED"
    touch(plan)
    return success_object(public(plan))


@bp.route("/bakery/production-plans/<pid>/unlock", methods=["POST"])
def unlock_plan(pid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    plan = lookup(DB.production_plans, pid, "production plan")
    if plan.get("status") != "LOCKED":
        raise ApiError(ERR_INVALID_STATE, "Plan is not LOCKED", 409)
    for batch in DB.batches.values():
        if batch.get("production_plan_id") == pid and batch.get("status") != "SCHEDULED":
            raise ApiError(ERR_PLAN_NOT_RELEASABLE, "A batch has already left SCHEDULED", 409)
    plan["planned_units_by_product"] = {}
    plan["batches_required_by_product"] = {}
    plan["total_planned_units"] = 0
    plan["flour_required_kg"] = 0
    plan["status"] = "DRAFT"
    touch(plan)
    return success_object(public(plan))


@bp.route("/bakery/production-plans/<pid>/release", methods=["POST"])
def release_plan(pid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    plan = lookup(DB.production_plans, pid, "production plan")
    if plan.get("status") != "LOCKED":
        raise ApiError(ERR_INVALID_STATE, "Plan is not LOCKED", 409)
    has_scheduled = any(
        b.get("production_plan_id") == pid and b.get("status") == "SCHEDULED"
        for b in DB.batches.values()
    )
    if not has_scheduled:
        raise ApiError(ERR_PLAN_NOT_RELEASABLE, "Plan has no SCHEDULED batch", 409)

    line_ids = {
        b.get("line_id") for b in DB.batches.values() if b.get("production_plan_id") == pid
    }
    for cycle in DB.sanitation_cycles.values():
        if cycle.get("line_id") in line_ids and cycle.get("status") in ("REQUESTED", "IN_PROGRESS"):
            raise ApiError(ERR_SANITATION_REQUIRED, "A sanitation cycle is pending on a line used by this plan", 409)

    plan["status"] = "RELEASED"
    touch(plan)
    return success_object(public(plan))


@bp.route("/bakery/production-plans/<pid>/reconcile", methods=["POST"])
def reconcile_plan(pid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    plan = lookup(DB.production_plans, pid, "production plan")
    if plan.get("status") != "RELEASED":
        raise ApiError(ERR_INVALID_STATE, "Plan is not RELEASED", 409)
    for batch in DB.batches.values():
        if batch.get("production_plan_id") != pid:
            continue
        if batch.get("status") not in ("RELEASED", "REJECTED", "ABORTED"):
            raise ApiError(ERR_INVALID_STATE, "Not all batches are terminal", 409)
    plan["status"] = "RECONCILED"
    touch(plan)
    return success_object(public(plan))
