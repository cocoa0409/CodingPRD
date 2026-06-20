"""LaborEntry endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
import lookups
import serializers
from errors import err
from helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    require_number,
    require_str,
    round2,
)
from middleware import require_roles
from response import array_response, object_response
from services import compute

bp = Blueprint("labor_entries", __name__)
READ_ROLES = ("FarmManager", "Agronomist")


@bp.post("/labor-entries")
@require_roles("Agronomist", "FarmManager")
def create_labor():
    body = get_json_body()
    crop_plan_id = require_str(body, "crop_plan_id")
    worker_name = require_str(body, "worker_name")
    hours = require_number(body, "hours")
    hourly_rate = require_number(body, "hourly_rate")

    plan = lookups.crop_plan(crop_plan_id)

    if hours <= 0:
        raise err("ERR_INVALID_REQUEST", "hours must be > 0.")
    if hourly_rate < 0:
        raise err("ERR_INVALID_REQUEST", "hourly_rate must be >= 0.")

    labor_cost = round2(hours * hourly_rate)

    rec = db.new_entity(
        {
            "crop_plan_id": crop_plan_id,
            "worker_name": worker_name,
            "hours": hours,
            "hourly_rate": hourly_rate,
            "labor_cost": labor_cost,
        }
    )
    db.labor_entries[rec["id"]] = rec

    compute.recompute_actual_labor_cost(plan)
    compute.recompute_provisional_cost_per_acre(plan)
    db.touch(plan)

    return object_response(serializers.labor_entry(rec), 201)


@bp.get("/labor-entries/<lid>")
@require_roles(*READ_ROLES)
def get_labor(lid):
    rec = lookups.labor_entry(lid)
    return object_response(serializers.labor_entry(rec))


@bp.get("/labor-entries")
@require_roles(*READ_ROLES)
def list_labor():
    limit, offset = parse_pagination()
    records = list(db.labor_entries.values())
    val = request.args.get("crop_plan_id")
    if val is not None:
        records = [r for r in records if r["crop_plan_id"] == val]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.labor_entry(r) for r in page], limit, offset, total
    )
