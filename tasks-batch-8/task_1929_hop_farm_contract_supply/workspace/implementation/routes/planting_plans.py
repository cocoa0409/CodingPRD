"""Planting plan endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_FARM_MANAGER
from response import success_object, success_list, parse_pagination
from util import get_body, check_unknown_fields, req_str, req_int, req_enum
from errors import invalid_state, ApiError, ERR_FIELD_SEASON_CONFLICT, ERR_ACREAGE_EXCEEDED
from services.core import (
    base_record, touch, public, get_plan, get_field,
    projected_yield_lbs, filtered_sorted,
    VARIETIES, PLAN_STATUSES,
)

bp = Blueprint("planting_plans", __name__)

FM = [ROLE_FARM_MANAGER]


def _plan_has_lots(plan_id):
    return any(l["planting_plan_id"] == plan_id for l in store.harvest_lots.values())


@bp.route("/api/planting-plans", methods=["POST"])
def create_plan():
    require_roles(FM)
    body = get_body()
    check_unknown_fields(body, {"field_id", "crop_year", "variety", "planned_acreage"})
    field_id = req_str(body, "field_id")
    crop_year = req_int(body, "crop_year")
    variety = req_enum(body, "variety", VARIETIES)
    planned_acreage = req_int(body, "planned_acreage", min_v=1)

    field = get_field(field_id)

    # priority 8: field-season uniqueness (ahead of the priority-12 acreage ceiling)
    for p in store.planting_plans.values():
        if (p["field_id"] == field_id and p["crop_year"] == crop_year
                and p["status"] != "CANCELLED"):
            raise ApiError(ERR_FIELD_SEASON_CONFLICT, 409,
                           "A live PlantingPlan already exists for this field and crop year")

    # priority 12: acreage ceiling
    if planned_acreage > field["acreage"]:
        raise ApiError(ERR_ACREAGE_EXCEEDED, 422,
                       "planned_acreage exceeds field acreage")

    rec = base_record()
    rec.update({
        "field_id": field_id,
        "crop_year": crop_year,
        "variety": variety,
        "planned_acreage": planned_acreage,
        "projected_yield_lbs": projected_yield_lbs(planned_acreage, variety),
        "actual_yield_lbs": None,
        "status": "DRAFT",
    })
    store.planting_plans[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/api/planting-plans/<plan_id>", methods=["GET"])
def get_plan_endpoint(plan_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_plan(plan_id)))


@bp.route("/api/planting-plans", methods=["GET"])
def list_plans():
    require_roles(ALL_ROLES)
    records = filtered_sorted(list(store.planting_plans.values()), request.args, {
        "field_id": ("str", "field_id"),
        "crop_year": ("int", "crop_year"),
        "status": ("enum", "status", PLAN_STATUSES),
    })
    limit, offset = parse_pagination(request.args)
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/api/planting-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(plan_id):
    require_roles(FM)
    check_unknown_fields(get_body(), set())  # no declared inputs
    plan = get_plan(plan_id)
    if plan["status"] != "DRAFT":
        raise invalid_state("Plan is not DRAFT")
    plan["status"] = "GROWING"
    touch(plan)
    return success_object(public(plan))


@bp.route("/api/planting-plans/<plan_id>/revise", methods=["POST"])
def revise_plan(plan_id):
    require_roles(FM)
    check_unknown_fields(get_body(), set())
    plan = get_plan(plan_id)
    if plan["status"] != "GROWING":
        raise invalid_state("Plan is not GROWING")
    if _plan_has_lots(plan_id):
        raise invalid_state("Plan has linked harvest lots and can no longer be revised")
    plan["status"] = "DRAFT"
    touch(plan)
    return success_object(public(plan))


@bp.route("/api/planting-plans/<plan_id>/open-harvest", methods=["POST"])
def open_harvest_plan(plan_id):
    require_roles(FM)
    check_unknown_fields(get_body(), set())
    plan = get_plan(plan_id)
    if plan["status"] != "GROWING":
        raise invalid_state("Plan is not GROWING")
    plan["status"] = "HARVESTING"
    touch(plan)
    return success_object(public(plan))


@bp.route("/api/planting-plans/<plan_id>/complete", methods=["POST"])
def complete_plan(plan_id):
    require_roles(FM)
    check_unknown_fields(get_body(), set())
    plan = get_plan(plan_id)
    if plan["status"] != "HARVESTING":
        raise invalid_state("Plan is not HARVESTING")
    # kiln pipeline must be empty; DRIED and CONSUMED lots are allowed
    for lot in store.harvest_lots.values():
        if lot["planting_plan_id"] == plan_id and lot["status"] in (
                "HARVESTED", "IN_KILN", "MOISTURE_CHECK"):
            raise invalid_state("Plan still has harvest lots in the kiln pipeline")
    plan["actual_yield_lbs"] = sum(
        lot["dried_lbs"] for lot in store.harvest_lots.values()
        if lot["planting_plan_id"] == plan_id and lot["status"] in ("DRIED", "CONSUMED"))
    plan["status"] = "COMPLETE"
    touch(plan)
    # deliberately no mutation of linked insurance claims: the filing-time
    # estimate stands; the final indemnity variant is computed only at pay
    return success_object(public(plan))


@bp.route("/api/planting-plans/<plan_id>/cancel", methods=["POST"])
def cancel_plan(plan_id):
    require_roles(FM)
    check_unknown_fields(get_body(), set())
    plan = get_plan(plan_id)
    if plan["status"] not in ("DRAFT", "GROWING"):
        raise invalid_state("Plan is not DRAFT or GROWING")
    if _plan_has_lots(plan_id):
        raise invalid_state("Plan has linked harvest lots and can no longer be cancelled")
    plan["status"] = "CANCELLED"
    touch(plan)
    return success_object(public(plan))
