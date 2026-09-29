"""Crop cycles, their lifecycle, hive placements and pollination checks."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import const
import fields
from authz import ALL_ROLES, GROWER_MANAGER, body, guard
from envelope import created, ok, paginated, public
from errors import ApiError
from helpers import fetch, filter_equals, terminal, to_status_enum, transition
from money import D, q2
from store import base_record, db, now, ordered, touch

bp = Blueprint("cycles", __name__)

ALLOWED = {
    "PLANNED": ("TRANSPLANTED",),
    "TRANSPLANTED": ("PRODUCTION", "ABORTED"),
    "PRODUCTION": ("TERMINATION_SCHEDULED", "ABORTED"),
    "TERMINATION_SCHEDULED": ("PRODUCTION", "TERMINATED"),
}


def _project_dates(cycle, variety):
    transplant = cycle["transplant_date"]
    cycle["planned_end_date"] = transplant + timedelta(
        days=variety["cycle_length_weeks"] * 7 - 1
    )
    cycle["first_harvest_allowed_date"] = transplant + timedelta(
        days=(variety["first_harvest_week"] - 1) * 7
    )


@bp.post("/crop-cycles")
@guard([GROWER_MANAGER])
def create_cycle():
    payload = body()
    zone_id = fields.string(payload, "zone_id")
    variety_id = fields.string(payload, "variety_id")
    transplant_date = fields.day(payload, "transplant_date")
    plants = fields.integer(payload, "plants_transplanted", lo=1)
    # priority 7 - body FKs in declared input order
    zone = fetch("zones", zone_id)
    variety = fetch("varieties", variety_id)
    # priority 32
    for other in db["crop_cycles"].values():
        if other["zone_id"] == zone_id and other["status"] in const.CYCLE_OCCUPYING:
            raise ApiError("ERR_ZONE_OCCUPIED")

    record = base_record()
    record.update({
        "zone_id": zone_id,
        "variety_id": variety_id,
        "transplant_date": transplant_date,
        "plants_transplanted": plants,
        "planned_end_date": None,
        "first_harvest_allowed_date": None,
        "status": "PLANNED",
        "density_factor": None,
        "expected_weekly_yield_lbs": [],
        "expected_total_yield_lbs": None,
        "baseline_total_yield_lbs": None,
        "cumulative_harvested_lbs": q2(0),
        "yield_variance_pct": q2(0),
        "hive_count_placed": 0,
        "hives_placed_at": None,
        "pollination_strength_index": q2(100),
        "pollination_risk_score": q2(0),
        "pollination_haircut_pct": q2(0),
        "nutrient_stress_flag": False,
        "labor_shortfall_flag": False,
        "termination_date": None,
    })
    _project_dates(record, variety)
    db["crop_cycles"][record["id"]] = record
    calc.project_yield(record)
    calc.refresh_zone(zone)
    return created(public(record))


@bp.get("/crop-cycles")
@guard(ALL_ROLES)
def list_cycles():
    rows = ordered("crop_cycles")
    rows = filter_equals(rows, "zone_id", request.args.get("zone_id"))
    rows = filter_equals(rows, "variety_id", request.args.get("variety_id"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return paginated(rows, public)


@bp.get("/crop-cycles/<cycle_id>")
@guard(ALL_ROLES)
def get_cycle(cycle_id):
    return ok(public(fetch("crop_cycles", cycle_id)))


@bp.post("/crop-cycles/<cycle_id>/transitions")
@guard([GROWER_MANAGER])
def transition_cycle(cycle_id):
    payload = body()
    target = fields.enum_slot(payload, "to_status")
    termination_date = None
    revised_plants = None
    if target == "TERMINATION_SCHEDULED":
        termination_date = fields.day(payload, "termination_date")
    if target == "TRANSPLANTED":
        revised_plants = fields.integer(
            payload, "plants_transplanted", required=False, lo=1
        )
    to_status_enum(target, const.CYCLE_STATUSES)
    cycle = fetch("crop_cycles", cycle_id)
    zone = db["zones"][cycle["zone_id"]]
    terminal(cycle["status"], const.CYCLE_TERMINAL)
    transition(ALLOWED, cycle["status"], target)

    if target == "TRANSPLANTED":
        for other in db["crop_cycles"].values():
            if other["id"] == cycle["id"]:
                continue
            if other["zone_id"] != cycle["zone_id"]:
                continue
            if other["status"] in const.CYCLE_OCCUPYING:
                raise ApiError("ERR_ZONE_OCCUPIED")
        cycle["status"] = "TRANSPLANTED"
        if revised_plants is not None and revised_plants != cycle["plants_transplanted"]:
            cycle["plants_transplanted"] = revised_plants
            calc.project_yield(cycle)
        touch(cycle)
        calc.refresh_zone(zone, force=True)

    elif target == "PRODUCTION":
        if cycle["status"] == "TRANSPLANTED":
            if now().date() < cycle["first_harvest_allowed_date"]:
                raise ApiError("ERR_PRODUCTION_TOO_EARLY")
            cycle["status"] = "PRODUCTION"
        else:
            cycle["status"] = "PRODUCTION"
            cycle["termination_date"] = None
        touch(cycle)
        calc.refresh_zone(zone)

    elif target == "TERMINATION_SCHEDULED":
        latest = cycle["planned_end_date"] + timedelta(
            days=const.TERMINATION_GRACE_DAYS
        )
        if termination_date < now().date() or termination_date > latest:
            raise ApiError("ERR_TERMINATION_DATE_OUT_OF_RANGE")
        cycle["status"] = "TERMINATION_SCHEDULED"
        cycle["termination_date"] = termination_date
        touch(cycle)
        calc.refresh_zone(zone)

    elif target == "TERMINATED":
        for task in db["labor_tasks"].values():
            if task["crop_cycle_id"] == cycle["id"] and task["status"] in const.TASK_COMMITTED:
                raise ApiError("ERR_OPEN_LABOR_TASKS")
        for lot in db["harvest_lots"].values():
            if lot["crop_cycle_id"] == cycle["id"] and lot["grading_status"] == "UNGRADED":
                raise ApiError("ERR_UNGRADED_LOTS_REMAIN")
        cycle["status"] = "TERMINATED"
        cycle["hive_count_placed"] = 0
        touch(cycle)
        calc.refresh_zone(zone, force=True)

    else:  # ABORTED
        cycle["status"] = "ABORTED"
        cycle["hive_count_placed"] = 0
        touch(cycle)
        calc.cascade_abort_tasks(cycle)
        calc.refresh_zone(zone, force=True)

    return ok(public(cycle))


@bp.post("/crop-cycles/<cycle_id>/hive-placements")
@guard([GROWER_MANAGER])
def place_hives(cycle_id):
    payload = body()
    hive_count = fields.integer(payload, "hive_count", lo=0)
    placed_at = fields.timestamp(payload, "placed_at")
    cycle = fetch("crop_cycles", cycle_id)
    zone = db["zones"][cycle["zone_id"]]
    terminal(cycle["status"], const.CYCLE_TERMINAL)
    if zone["ipm_posture"] == "LOCKED":
        raise ApiError("ERR_ZONE_IPM_LOCKED")
    # priority 27 - projected occupancy must stay inside capacity
    prospective = cycle["hive_count_placed"] + hive_count
    for other in db["crop_cycles"].values():
        if other["id"] == cycle["id"] or other["zone_id"] != zone["id"]:
            continue
        if other["status"] not in const.CYCLE_OCCUPYING:
            continue
        prospective += other["hive_count_placed"]
    if prospective > zone["hive_slot_capacity"]:
        raise ApiError("ERR_HIVE_SLOTS_EXCEEDED")

    cycle["hive_count_placed"] = cycle["hive_count_placed"] + hive_count
    cycle["hives_placed_at"] = placed_at
    touch(cycle)
    calc.refresh_zone(zone)
    return ok(public(cycle))


@bp.post("/crop-cycles/<cycle_id>/pollination-checks")
@guard([GROWER_MANAGER])
def pollination_check(cycle_id):
    payload = body()
    observed_at = fields.timestamp(payload, "observed_at")
    flower_visit_pct = fields.number(payload, "flower_visit_pct", lo=0)
    hive_activity_count = fields.integer(payload, "hive_activity_count", lo=0)
    cycle = fetch("crop_cycles", cycle_id)
    terminal(cycle["status"], const.CYCLE_TERMINAL)
    calc.pollination_check(cycle, observed_at, flower_visit_pct, hive_activity_count)
    touch(cycle)
    return ok(public(cycle))
