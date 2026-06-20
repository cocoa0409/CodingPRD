"""CropPlan endpoints + lifecycle state machine (PRD §3.1, §3.2, §3.7).

State machine (SCAFFOLD §1.2):
  DRAFT -> APPROVED (approve, FarmManager, OCC on parcel version)
  APPROVED -> UNDER_REVISION (request-revision, Agronomist)
  UNDER_REVISION -> APPROVED (approve, FarmManager)
  APPROVED -> GROWING (begin-growing, Agronomist)
  GROWING -> HARVESTING (begin-harvest, Agronomist, PHI gate)
  HARVESTING -> CLOSED (close, FarmManager)
  DRAFT -> ABANDONED (abandon, FarmManager)
  APPROVED -> ABANDONED (abandon, FarmManager)
"""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import lookups
import serializers
from errors import err
from helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_number,
    require_str,
)
from middleware import require_roles
from response import array_response, object_response
from services import compute
from timeutil import parse_iso

bp = Blueprint("crop_plans", __name__)

CROPS = {"CORN", "SOY", "WHEAT", "COTTON", "ALFALFA"}
ALL_ROLES = ("FarmManager", "Agronomist", "Applicator", "SalesAgent")


def _init_plan_computed(plan):
    plan["revision_count"] = 0
    plan["planted_acres"] = 0
    plan["harvested_acres"] = 0
    plan["actual_input_cost"] = 0
    plan["actual_labor_cost"] = 0
    plan["actual_equipment_cost"] = 0
    plan["final_cost_per_acre"] = None
    plan["total_yield_units"] = compute.round2(0)
    plan["provisional_cost_per_acre"] = compute.compute_provisional_cost_per_acre(plan)


@bp.post("/crop-plans")
@require_roles("Agronomist", "FarmManager")
def create_crop_plan():
    body = get_json_body()
    parcel_id = require_str(body, "parcel_id")
    crop = require_enum(body, "crop", CROPS)
    season_year = require_int(body, "season_year")
    planned_acres = require_number(body, "planned_acres")
    budget_input_cost = require_number(body, "budget_input_cost")
    budget_labor_cost = require_number(body, "budget_labor_cost")
    budget_equipment_cost = require_number(body, "budget_equipment_cost")

    # Existence (PRD §2.7) before range checks at request-shape gate?
    # PRD §2.10 order: existence (404) precedes request-shape (400). Resolve FK first.
    lookups.parcel(parcel_id)

    if season_year < 2000:
        raise err("ERR_INVALID_REQUEST", "season_year must be >= 2000.")
    if planned_acres <= 0:
        raise err("ERR_INVALID_REQUEST", "planned_acres must be > 0.")

    rec = db.new_entity(
        {
            "parcel_id": parcel_id,
            "crop": crop,
            "season_year": season_year,
            "planned_acres": planned_acres,
            "budget_input_cost": budget_input_cost,
            "budget_labor_cost": budget_labor_cost,
            "budget_equipment_cost": budget_equipment_cost,
            "status": "DRAFT",
        }
    )
    _init_plan_computed(rec)
    db.crop_plans[rec["id"]] = rec
    return object_response(serializers.crop_plan(rec), 201)


@bp.get("/crop-plans/<pid>")
@require_roles(*ALL_ROLES)
def get_crop_plan(pid):
    rec = lookups.crop_plan(pid)
    return object_response(serializers.crop_plan(rec))


@bp.get("/crop-plans")
@require_roles(*ALL_ROLES)
def list_crop_plans():
    limit, offset = parse_pagination()
    records = list(db.crop_plans.values())
    parcel_id = request.args.get("parcel_id")
    crop = request.args.get("crop")
    status = request.args.get("status")
    season_year = request.args.get("season_year")
    if parcel_id is not None:
        records = [r for r in records if r["parcel_id"] == parcel_id]
    if crop is not None:
        records = [r for r in records if r["crop"] == crop]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if season_year is not None:
        try:
            sy = int(season_year)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "season_year must be an integer.")
        records = [r for r in records if r["season_year"] == sy]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.crop_plan(r) for r in page], limit, offset, total
    )


def _has_recorded_planting(plan_id):
    return any(
        pe["crop_plan_id"] == plan_id and pe["status"] == "RECORDED"
        for pe in db.planting_events.values()
    )


def _approve(plan):
    """Shared approve path for DRAFT->APPROVED and UNDER_REVISION->APPROVED.

    Preconditions ordering follows PRD §3.1 / §2.10:
      parcel available (ERR_PARCEL_NOT_AVAILABLE),
      planned acres within acreage (ERR_PLANNED_ACRES_EXCEED_PARCEL),
      OCC last (ERR_STALE_PARCEL_VERSION) — §2.10 places OCC last among domain rules.
    """
    body = get_json_body()
    # expected_parcel_version is a non-optional field (PRD §2.6).
    if "expected_parcel_version" not in body or body.get("expected_parcel_version") is None:
        raise err("ERR_INVALID_REQUEST", "expected_parcel_version is required.")
    expected = body.get("expected_parcel_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_parcel_version must be an integer.")

    parcel = lookups.parcel(plan["parcel_id"])

    if parcel["status"] != "AVAILABLE":
        raise err("ERR_PARCEL_NOT_AVAILABLE", "Parcel is not AVAILABLE.")
    if plan["planned_acres"] > parcel["acreage"]:
        raise err(
            "ERR_PLANNED_ACRES_EXCEED_PARCEL",
            "planned_acres exceeds parcel acreage.",
        )
    if expected != parcel["version"]:
        raise err("ERR_STALE_PARCEL_VERSION", "expected_parcel_version is stale.")

    plan["status"] = "APPROVED"
    db.touch(plan)

    compute.recompute_active_crop_plan_count(parcel)
    db.touch(parcel)
    return plan


@bp.post("/crop-plans/<pid>/approve")
@require_roles("FarmManager")
def approve_crop_plan(pid):
    plan = lookups.crop_plan(pid)
    if plan["status"] not in ("DRAFT", "UNDER_REVISION"):
        raise err("ERR_INVALID_STATE", "Plan is not in DRAFT or UNDER_REVISION.")
    _approve(plan)
    return object_response(serializers.crop_plan(plan))


@bp.post("/crop-plans/<pid>/request-revision")
@require_roles("Agronomist")
def request_revision(pid):
    plan = lookups.crop_plan(pid)
    if plan["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Plan is not APPROVED.")
    if _has_recorded_planting(plan["id"]):
        raise err("ERR_PLAN_ALREADY_PLANTED", "A RECORDED planting exists for the plan.")

    plan["status"] = "UNDER_REVISION"
    plan["revision_count"] = plan["revision_count"] + 1
    db.touch(plan)

    parcel = db.parcels.get(plan["parcel_id"])
    if parcel:
        compute.recompute_active_crop_plan_count(parcel)
        db.touch(parcel)
    return object_response(serializers.crop_plan(plan))


@bp.post("/crop-plans/<pid>/begin-growing")
@require_roles("Agronomist")
def begin_growing(pid):
    plan = lookups.crop_plan(pid)
    if plan["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Plan is not APPROVED.")
    if plan["planned_acres"] is None or plan["planted_acres"] <= 0:
        raise err("ERR_NO_PLANTING_RECORDED", "No planting recorded (planted_acres must be > 0).")

    plan["status"] = "GROWING"
    compute.recompute_provisional_cost_per_acre(plan)
    db.touch(plan)
    return object_response(serializers.crop_plan(plan))


@bp.post("/crop-plans/<pid>/begin-harvest")
@require_roles("Agronomist")
def begin_harvest(pid):
    plan = lookups.crop_plan(pid)
    if plan["status"] != "GROWING":
        raise err("ERR_INVALID_STATE", "Plan is not GROWING.")

    # PHI gate (PRD §3.2, §3.4): for every non-voided restricted application on
    # the plan, current clock >= applied_at + preharvest_interval_days (whole days).
    now = clock.now()
    for ar in db.application_records.values():
        if ar["crop_plan_id"] != plan["id"]:
            continue
        if ar["status"] == "VOIDED":
            continue
        if not ar.get("is_restricted"):
            continue
        applied_at = parse_iso(ar.get("applied_at"))
        if applied_at is None:
            continue
        product = db.input_products.get(ar["input_product_id"])
        phi_days = product.get("preharvest_interval_days", 0) if product else 0
        earliest = applied_at + timedelta(days=phi_days)
        if now < earliest:
            raise err(
                "ERR_PREHARVEST_INTERVAL_ACTIVE",
                "Pre-harvest interval has not elapsed for a restricted application.",
            )

    plan["status"] = "HARVESTING"
    db.touch(plan)
    return object_response(serializers.crop_plan(plan))


@bp.post("/crop-plans/<pid>/close")
@require_roles("FarmManager")
def close_plan(pid):
    plan = lookups.crop_plan(pid)
    if plan["status"] != "HARVESTING":
        raise err("ERR_INVALID_STATE", "Plan is not HARVESTING.")
    if plan["harvested_acres"] <= 0:
        raise err("ERR_NO_HARVEST_RECORDED", "harvested_acres must be > 0 to close.")

    plan["status"] = "CLOSED"
    plan["final_cost_per_acre"] = compute.compute_final_cost_per_acre(plan)
    compute.recompute_total_yield_units(plan)
    db.touch(plan)

    parcel = db.parcels.get(plan["parcel_id"])
    if parcel:
        compute.recompute_active_crop_plan_count(parcel)
        db.touch(parcel)
    return object_response(serializers.crop_plan(plan))


@bp.post("/crop-plans/<pid>/abandon")
@require_roles("FarmManager")
def abandon_plan(pid):
    plan = lookups.crop_plan(pid)
    if plan["status"] not in ("DRAFT", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Plan is not DRAFT or APPROVED.")

    was_approved = plan["status"] == "APPROVED"
    if was_approved and _has_recorded_planting(plan["id"]):
        raise err("ERR_PLAN_ALREADY_PLANTED", "A RECORDED planting exists for the plan.")

    plan["status"] = "ABANDONED"
    db.touch(plan)

    if was_approved:
        parcel = db.parcels.get(plan["parcel_id"])
        if parcel:
            compute.recompute_active_crop_plan_count(parcel)
            db.touch(parcel)
    return object_response(serializers.crop_plan(plan))
