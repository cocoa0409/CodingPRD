"""Tunnel-kiln scheduling, loading, light-off and the grading cascade."""

from datetime import timedelta
from decimal import Decimal

import response
import services as svc
from auth import ALL_ROLES, endpoint, require_plant_scope
from errors import ApiError
from routes import apply_filters
from store import db, new_row, touch
from validation import bad, body, raw_id, v_datetime, v_id, v_int, v_num, v_str

from flask import Blueprint

bp = Blueprint("kiln_runs", __name__)

D = Decimal


def _buffer(kiln):
    seconds = int(D(kiln["cooldown_buffer_hours"]) * D("3600"))
    return timedelta(seconds=seconds)


@bp.get("/kiln-runs/<rid>")
@endpoint(ALL_ROLES)
def get_kiln_run(rid):
    return response.entity(svc.kiln_run_or_404(rid))


@bp.get("/kiln-runs")
@endpoint(ALL_ROLES)
def list_kiln_runs():
    rows = apply_filters(
        db.kiln_runs.values(),
        {"kiln_id": "kiln_id", "formulation_id": "formulation_id", "status": "status"},
    )
    return response.collection(rows)


# --------------------------------------------------------------------------
# POST /kiln-runs
# --------------------------------------------------------------------------
@bp.post("/kiln-runs")
@endpoint(["PlantOperator"])
def schedule_kiln_run():
    payload = body()
    kiln_hint = db.kilns.get(raw_id(payload, "kiln_id"))
    if kiln_hint is not None:
        require_plant_scope(kiln_hint["plant_id"])

    kiln_id = v_id(payload, "kiln_id")
    formulation_id = v_id(payload, "formulation_id")
    run_code = v_str(payload, "run_code")
    start_at = v_datetime(payload, "start_at")
    end_at = v_datetime(payload, "end_at")
    planned_peak = v_int(payload, "planned_peak_temp_c", minv=800, maxv=1300)
    planned_soak = v_num(payload, "planned_soak_hours", 2, minv="0.50", maxv="24.00")
    if end_at <= start_at:
        raise bad("end_at must be strictly later than start_at.")

    kiln = svc.kiln_or_404(kiln_id)
    formulation = svc.formulation_or_404(formulation_id)

    svc.require_plant_active(db.plants.get(kiln["plant_id"]))
    if formulation["status"] != "QUALIFIED":
        raise ApiError("ERR_FORMULATION_NOT_QUALIFIED", "The body formulation is not QUALIFIED.")
    svc.require_unique(db.kiln_runs, "run_code", run_code)

    # Ladder rule 38 — CLOSED, buffer-inflated intervals; touching endpoints collide.
    buffer = _buffer(kiln)
    new_end = end_at + buffer
    for other in db.kiln_runs.values():
        if other["kiln_id"] != kiln_id or other["status"] == "ABORTED":
            continue
        other_end = other["_end_at"] + buffer
        if start_at <= other_end and other["_start_at"] <= new_end:
            raise ApiError(
                "ERR_KILN_WINDOW_CONFLICT",
                "The firing window collides with an existing window on this kiln.",
            )

    row = new_row(
        kiln_id=kiln_id,
        formulation_id=formulation_id,
        run_code=run_code,
        start_at=payload["start_at"],
        end_at=payload["end_at"],
        planned_peak_temp_c=planned_peak,
        planned_soak_hours=planned_soak,
        actual_peak_temp_c=None,
        actual_soak_hours=None,
        base_cdi=None,
        firing_curve_deviation=None,
        loaded_units=0,
        graded_by_user_id=None,
        status="SCHEDULED",
    )
    row["_start_at"] = start_at
    row["_end_at"] = end_at
    db.kiln_runs[row["id"]] = row
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /kiln-runs/{id}/load
# --------------------------------------------------------------------------
@bp.post("/kiln-runs/<rid>/load")
@endpoint(["PlantOperator"])
def load_kiln_run(rid):
    kiln_run = svc.kiln_run_or_404(rid)
    kiln = db.kilns.get(kiln_run["kiln_id"])
    payload = body()

    if kiln is not None:
        require_plant_scope(kiln["plant_id"])
    run_hint = db.production_runs.get(raw_id(payload, "production_run_id"))
    if run_hint is not None:
        require_plant_scope(run_hint["plant_id"])

    production_run_id = v_id(payload, "production_run_id")
    kiln_position = v_int(payload, "kiln_position")
    expected = v_int(payload, "expected_kiln_run_version")

    run = svc.run_or_404(production_run_id)

    if expected != int(kiln_run["version"]):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_kiln_run_version does not match the kiln run's current version.",
        )

    svc.require_plant_active(db.plants.get(kiln["plant_id"]))
    if run["status"] != "SET":
        raise ApiError("ERR_PRODUCTION_RUN_STATE_INVALID", "The production run is not SET.")
    if kiln_run["status"] != "SCHEDULED":
        raise ApiError("ERR_KILN_RUN_STATE_INVALID", "The kiln run is not SCHEDULED.")
    if run["formulation_id"] != kiln_run["formulation_id"]:
        raise bad("The production run's formulation_id must equal the kiln run's formulation_id.")
    if kiln_position < 1 or kiln_position > int(kiln["position_count"]):
        raise ApiError(
            "ERR_INVALID_KILN_POSITION",
            "kiln_position must lie inside the kiln's position range.",
        )
    for other in svc.runs_of_kiln_run(rid):
        if int(other.get("kiln_position") or 0) == kiln_position:
            raise ApiError(
                "ERR_KILN_POSITION_OCCUPIED",
                "That kiln position is already taken on this kiln run.",
            )

    # Ladder rule 39 — HALF-OPEN car occupancy, zero buffer; adjacency is allowed.
    for other in db.production_runs.values():
        if other["id"] == run["id"] or other["kiln_car_id"] != run["kiln_car_id"]:
            continue
        other_kiln_run = db.kiln_runs.get(other.get("kiln_run_id"))
        if other_kiln_run is None or other_kiln_run["status"] == "ABORTED":
            continue
        if other_kiln_run["id"] == rid:
            continue
        if (
            kiln_run["_start_at"] < other_kiln_run["_end_at"]
            and other_kiln_run["_start_at"] < kiln_run["_end_at"]
        ):
            raise ApiError(
                "ERR_KILN_CAR_OCCUPIED",
                "The kiln car is already committed to an overlapping firing window.",
            )

    run["status"] = "LOADED"
    run["kiln_run_id"] = rid
    run["kiln_position"] = kiln_position
    touch(run)

    car = db.kiln_cars.get(run["kiln_car_id"])
    if car is not None:
        car["status"] = "IN_KILN"
        touch(car)

    kiln_run["loaded_units"] = sum(
        int(r.get("net_green_units") or 0) for r in svc.runs_of_kiln_run(rid)
    )
    touch(kiln_run)
    return response.entity(kiln_run)


# --------------------------------------------------------------------------
# POST /kiln-runs/{id}/start
# --------------------------------------------------------------------------
@bp.post("/kiln-runs/<rid>/start")
@endpoint(["PlantOperator"])
def start_kiln_run(rid):
    kiln_run = svc.kiln_run_or_404(rid)
    kiln = db.kilns.get(kiln_run["kiln_id"])
    if kiln is not None:
        require_plant_scope(kiln["plant_id"])
    svc.require_plant_active(db.plants.get(kiln["plant_id"]))

    if kiln_run["status"] != "SCHEDULED":
        raise ApiError("ERR_KILN_RUN_STATE_INVALID", "The kiln run is not SCHEDULED.")
    loaded = [r for r in svc.runs_of_kiln_run(rid) if r["status"] == "LOADED"]
    if not loaded:
        raise ApiError("ERR_KILN_RUN_STATE_INVALID", "No production run is loaded on this run.")
    if kiln["status"] != "AVAILABLE":
        raise ApiError("ERR_KILN_RUN_STATE_INVALID", "The owning kiln is not AVAILABLE.")

    kiln_run["status"] = "FIRING"
    touch(kiln_run)
    return response.entity(kiln_run)


# --------------------------------------------------------------------------
# POST /kiln-runs/{id}/grade
# --------------------------------------------------------------------------
@bp.post("/kiln-runs/<rid>/grade")
@endpoint(["PlantOperator"])
def grade_kiln_run(rid):
    kiln_run = svc.kiln_run_or_404(rid)
    kiln = db.kilns.get(kiln_run["kiln_id"])
    if kiln is not None:
        require_plant_scope(kiln["plant_id"])

    payload = body()
    actual_peak = v_int(payload, "actual_peak_temp_c", minv=800, maxv=1300)
    actual_soak = v_num(payload, "actual_soak_hours", 2, minv="0.00", maxv="24.00")

    svc.require_plant_active(db.plants.get(kiln["plant_id"]))
    if kiln_run["status"] != "FIRING":
        raise ApiError("ERR_KILN_RUN_STATE_INVALID", "The kiln run is not FIRING.")

    formulation = db.formulations.get(kiln_run["formulation_id"])
    svc.grade_cascade(kiln_run, kiln, formulation, actual_peak, actual_soak)
    return response.entity(kiln_run)
