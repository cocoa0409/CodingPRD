"""Plating runs and the hydrogen embrittlement relief bake (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint, g

import enums
from db import db, new_record, order_key, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok, ok_list
from services import calc
from services.lookup import (
    compute_pre_test_risk,
    guard_disposition,
    lot_plating_runs,
    plating_run_or_404,
    production_lot_or_404,
    spec_for_lot,
)
from util import dec, dt_of
from validate import (
    field_enum,
    field_int,
    field_num,
    field_str,
    paginate,
    pagination,
    query_enum,
)

bp = Blueprint("plating", __name__)

CREATE_ROLES = ("HeatTreatOperator", "ProcessEngineer")


@bp.post("/plating-runs")
@endpoint(CREATE_ROLES)
def create_plating_run():
    body = g.body
    production_lot_id = field_str(body, "production_lot_id")
    # Both plating_spec and load_mass_kg are named by the payload but the server
    # derives the stored values itself.
    field_enum(body, "plating_spec", enums.PLATING_SPECS)
    field_num(body, "load_mass_kg")

    lot = production_lot_or_404(production_lot_id)
    guard_disposition(lot)

    if not lot["heat_treat_completed"]:
        raise ApiError("ERR_HEAT_TREAT_NOT_PASSED")

    for existing in lot_plating_runs(production_lot_id):
        if existing["status"] in ("SCHEDULED", "PLATED"):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    spec = spec_for_lot(lot)
    run = new_record(
        {
            "production_lot_id": production_lot_id,
            "plating_spec": spec["plating_spec"],
            "load_mass_kg": calc.load_mass_kg(lot["available_count"], spec["blank_mass_g"]),
            "plated_at": None,
            "bake_started_at": None,
            "bake_temp_c": None,
            "bake_duration_min": None,
            "bake_delay_hours": None,
            "bake_completed_at": None,
            "status": "SCHEDULED",
        }
    )
    db.plating_runs[run["id"]] = run
    return created(run)


@bp.get("/production-lots/<lot_id>/plating-runs")
@endpoint(ANY_ROLE)
def list_plating_runs(lot_id):
    limit, offset = pagination()
    status = query_enum("status", enums.PLATING_STATUSES)
    production_lot_or_404(lot_id)

    records = sorted(lot_plating_runs(lot_id), key=order_key, reverse=True)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


def _lot_of(run):
    lot = db.production_lots.get(run["production_lot_id"])
    if lot is None:
        raise ApiError("ERR_PRODUCTION_LOT_NOT_FOUND")
    return lot


@bp.post("/plating-runs/<run_id>/complete-plating")
@endpoint("HeatTreatOperator")
def complete_plating(run_id):
    run = plating_run_or_404(run_id)
    lot = _lot_of(run)
    guard_disposition(lot)

    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_PROCESS_RUN_STATE")
    if not lot["heat_treat_completed"]:
        raise ApiError("ERR_HEAT_TREAT_NOT_PASSED")

    run["status"] = "PLATED"
    run["plated_at"] = db.now_iso()
    touch(run)
    lot["process_state"] = "PLATED"
    touch(lot)
    return ok(run)


@bp.post("/plating-runs/<run_id>/start-bake")
@endpoint("HeatTreatOperator")
def start_bake(run_id):
    body = g.body
    bake_temp_c = field_num(body, "bake_temp_c")
    bake_duration_min = field_int(body, "bake_duration_min", minimum=0)

    run = plating_run_or_404(run_id)
    lot = _lot_of(run)
    guard_disposition(lot)

    if run["status"] != "PLATED":
        raise ApiError("ERR_INVALID_PROCESS_RUN_STATE")

    spec = spec_for_lot(lot)

    plated_at = dt_of(run, "plated_at")
    now = db.now()
    delay = calc.bake_delay_hours(plated_at, now) if plated_at else calc.D(0)
    if delay > calc.BAKE_DELAY_MAX_HOURS:
        raise ApiError("ERR_HE_BAKE_WINDOW_MISSED")

    if not (calc.BAKE_TEMP_MIN <= dec(bake_temp_c) <= calc.BAKE_TEMP_MAX):
        raise ApiError("ERR_HE_BAKE_PARAMS_INVALID")
    if bake_duration_min < int(spec["he_bake_min_minutes"] or 0):
        raise ApiError("ERR_HE_BAKE_PARAMS_INVALID")

    if not spec.get("he_bake_required"):
        raise ApiError("ERR_BAKE_NOT_REQUIRED")

    run["bake_temp_c"] = bake_temp_c
    run["bake_duration_min"] = bake_duration_min
    run["bake_delay_hours"] = delay
    run["bake_started_at"] = db.now_iso()
    run["status"] = "BAKING"
    touch(run)
    return ok(run)


@bp.post("/plating-runs/<run_id>/complete-bake")
@endpoint("HeatTreatOperator")
def complete_bake(run_id):
    run = plating_run_or_404(run_id)
    lot = _lot_of(run)
    guard_disposition(lot)

    spec = spec_for_lot(lot)
    bake_required = bool(spec.get("he_bake_required"))

    if run["status"] == "BAKING":
        started = dt_of(run, "bake_started_at")
        duration = int(run["bake_duration_min"] or 0)
        if started is None or db.now() < started + timedelta(minutes=duration):
            raise ApiError("ERR_BAKE_DURATION_NOT_ELAPSED")
    elif run["status"] == "PLATED" and not bake_required:
        pass
    else:
        raise ApiError("ERR_INVALID_PROCESS_RUN_STATE")

    run["status"] = "BAKE_COMPLETE"
    run["bake_completed_at"] = db.now_iso()
    touch(run)

    lot["process_state"] = "BAKED"
    lot["risk_score_pre_test"] = compute_pre_test_risk(lot)
    touch(lot)
    return ok(run)
