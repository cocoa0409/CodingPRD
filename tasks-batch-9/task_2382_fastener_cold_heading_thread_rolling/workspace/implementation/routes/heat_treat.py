"""Heat treat runs (PRD 3.5)."""

from datetime import timedelta

from flask import Blueprint, g

import enums
from db import db, new_record, sorted_records, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok, ok_list
from services import calc
from services.lookup import (
    furnace_or_404,
    guard_disposition,
    heat_treat_run_or_404,
    production_lot_or_404,
    required_ops_satisfied,
    spec_for_lot,
)
from util import dec, dt_of
from validate import (
    field_dt,
    field_enum,
    field_int,
    field_num,
    field_str,
    paginate,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("heat_treat", __name__)

BOOK_ROLES = ("HeatTreatOperator", "ProcessEngineer")


@bp.post("/heat-treat-runs")
@endpoint(BOOK_ROLES)
def create_heat_treat_run():
    body = g.body
    production_lot_id = field_str(body, "production_lot_id")
    furnace_id = field_str(body, "furnace_id")
    window_start = field_dt(body, "window_start_at")
    window_end = field_dt(body, "window_end_at")
    austenitize_temp_c = field_num(body, "austenitize_temp_c")
    quench_medium = field_enum(body, "quench_medium", enums.QUENCH_MEDIA)
    temper_temp_c = field_num(body, "temper_temp_c")
    temper_time_min = field_int(body, "temper_time_min", minimum=1)
    carbon_potential_pct = field_num(body, "carbon_potential_pct")
    if window_end <= window_start:
        raise ApiError("ERR_VALIDATION", "window_end_at must be later than window_start_at.")

    lot = production_lot_or_404(production_lot_id)
    furnace = furnace_or_404(furnace_id)

    guard_disposition(lot)

    # tier 15 - furnace window plus cooldown
    cooldown = timedelta(minutes=int(furnace["cooldown_minutes"] or 0))
    for other in db.heat_treat_runs.values():
        if other["furnace_id"] != furnace_id:
            continue
        if other["status"] not in ("PLANNED", "RUNNING"):
            continue
        other_start = dt_of(other, "window_start_at")
        other_end = dt_of(other, "window_end_at")
        if other_start is None or other_end is None:
            continue
        if window_start <= other_end + cooldown and window_end >= other_start:
            raise ApiError("ERR_FURNACE_WINDOW_CONFLICT")

    # tier 16 - the stage's required secondary operations must be finished
    spec = spec_for_lot(lot)
    if not required_ops_satisfied(lot, spec):
        raise ApiError("ERR_SECONDARY_OPS_INCOMPLETE")

    # tier 17 - furnace charge capacity
    charge_mass = calc.charge_mass_kg(lot["available_count"], spec["blank_mass_g"])
    if charge_mass > dec(furnace["max_charge_mass_kg"]):
        raise ApiError("ERR_FURNACE_CAPACITY_EXCEEDED")

    run = new_record(
        {
            "production_lot_id": production_lot_id,
            "furnace_id": furnace_id,
            "window_start_at": body["window_start_at"],
            "window_end_at": body["window_end_at"],
            "austenitize_temp_c": austenitize_temp_c,
            "quench_medium": quench_medium,
            "temper_temp_c": temper_temp_c,
            "temper_time_min": temper_time_min,
            "carbon_potential_pct": carbon_potential_pct,
            "charge_mass_kg": charge_mass,
            "core_hardness_hv": None,
            "surface_decarb_depth_mm": None,
            "total_decarb_depth_mm": None,
            "result": "PENDING",
            "status": "PLANNED",
            "started_at": None,
            "completed_at": None,
        }
    )
    db.heat_treat_runs[run["id"]] = run
    return created(run)


@bp.get("/heat-treat-runs/<run_id>")
@endpoint(ANY_ROLE)
def get_heat_treat_run(run_id):
    return ok(heat_treat_run_or_404(run_id))


@bp.get("/heat-treat-runs")
@endpoint(ANY_ROLE)
def list_heat_treat_runs():
    limit, offset = pagination()
    production_lot_id = query_str("production_lot_id")
    furnace_id = query_str("furnace_id")
    status = query_enum("status", enums.HT_STATUSES)

    records = sorted_records(db.heat_treat_runs.values())
    if production_lot_id is not None:
        records = [r for r in records if r["production_lot_id"] == production_lot_id]
    if furnace_id is not None:
        records = [r for r in records if r["furnace_id"] == furnace_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/heat-treat-runs/<run_id>/start")
@endpoint("HeatTreatOperator")
def start_heat_treat_run(run_id):
    run = heat_treat_run_or_404(run_id)
    lot = db.production_lots.get(run["production_lot_id"])
    if lot is None:
        raise ApiError("ERR_PRODUCTION_LOT_NOT_FOUND")

    guard_disposition(lot)

    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_PROCESS_RUN_STATE")

    furnace = db.furnaces.get(run["furnace_id"])
    if furnace is None or furnace["status"] != "IDLE":
        raise ApiError("ERR_FURNACE_OCCUPIED")

    now = db.now()
    start = dt_of(run, "window_start_at")
    end = dt_of(run, "window_end_at")
    if now < start or now > end:
        raise ApiError("ERR_OUTSIDE_RUN_WINDOW")

    if lot["process_state"] != "SECONDARY_DONE":
        raise ApiError("ERR_INVALID_LOT_STATE")

    run["status"] = "RUNNING"
    run["started_at"] = db.now_iso()
    touch(run)
    furnace["status"] = "OCCUPIED"
    touch(furnace)
    return ok(run)


@bp.post("/heat-treat-runs/<run_id>/results")
@endpoint("QualityInspector")
def record_heat_treat_results(run_id):
    body = g.body
    core_hardness_hv = field_num(body, "core_hardness_hv")
    surface_decarb_depth_mm = field_num(body, "surface_decarb_depth_mm")

    run = heat_treat_run_or_404(run_id)
    lot = db.production_lots.get(run["production_lot_id"])
    if lot is None:
        raise ApiError("ERR_PRODUCTION_LOT_NOT_FOUND")

    guard_disposition(lot)

    if run["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_PROCESS_RUN_STATE")

    spec = spec_for_lot(lot)
    total_decarb = calc.total_decarb_depth_mm(
        surface_decarb_depth_mm, run["carbon_potential_pct"]
    )
    result = calc.metallurgy_result(spec, core_hardness_hv, total_decarb)

    now_iso = db.now_iso()
    run["core_hardness_hv"] = core_hardness_hv
    run["surface_decarb_depth_mm"] = surface_decarb_depth_mm
    run["total_decarb_depth_mm"] = total_decarb
    run["result"] = result
    run["status"] = "COMPLETED"
    run["completed_at"] = now_iso
    touch(run)

    furnace = db.furnaces.get(run["furnace_id"])
    if furnace is not None:
        furnace["status"] = "IDLE"
        furnace["last_run_end_at"] = now_iso
        touch(furnace)

    if result == "PASS":
        lot["heat_treat_completed"] = True
        if lot["process_state"] == "SECONDARY_DONE":
            lot["process_state"] = "HEAT_TREATED"
    else:
        lot["disposition"] = "HOLD"
        lot["hold_source"] = "HT_FAILURE"
    touch(lot)
    return ok(run)
