"""Burn-in endpoints: scheduling, completion, abortion, reads."""

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import serializers
import store
import validators as v
from errors import ApiError
from numeric import to_fraction

bp = Blueprint("burnin", __name__)


@bp.route("/burn-in-runs", methods=["POST"])
def schedule_run():
    auth.require("QAEngineer")
    body = v.body()
    cabinet_id = v.get_id(body, "cabinet_id")
    chamber_id = v.get_id(body, "burn_in_chamber_id")
    window_start, window_end = v.get_window(body)
    slots_required = v.get_int(body, "slots_required", minimum=1)
    drive_pct = v.get_int(body, "drive_pct", minimum=1, maximum=100)
    ambient_c = v.get_num(body, "ambient_c", minimum=-20, maximum=70)

    chamber = store.burn_in_chambers.get(chamber_id)      # rung 4
    if chamber is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    cab = store.cabinets.get(cabinet_id)                   # rung 7
    if cab is None:
        raise ApiError("ERR_CABINET_NOT_FOUND")
    if cab["cabinet_state"] != "POPULATED":                # rung 20
        raise ApiError("ERR_INVALID_CABINET_STATE")
    model = aggregates.model_of_cabinet(cab)
    if drive_pct > min(model["max_drive_pct"], chamber["certified_max_drive_pct"]):
        raise ApiError("ERR_DRIVE_LEVEL_UNSAFE")           # rung 31
    duration_ms = store.ms(window_end) - store.ms(window_start)
    if duration_ms < model["burn_in_hours_required"] * 3600000:
        raise ApiError("ERR_BURN_IN_DURATION_TOO_SHORT")   # rung 32

    occupied_until = store.add_minutes(window_end, chamber["turnaround_minutes"])
    cand_start = store.ms(window_start)
    cand_end = store.ms(occupied_until)
    concurrent = slots_required
    for run in store.burn_in_runs.values():
        if run["burn_in_chamber_id"] != chamber_id or run["run_state"] != "SCHEDULED":
            continue
        ex_start = store.ms(run["window_start"])
        ex_end = store.ms(run["occupied_until"])
        if cand_start <= ex_end and ex_start <= cand_end:   # CLOSED-CLOSED overlap
            concurrent += run["slots_required"]
    if concurrent > chamber["slot_capacity"]:               # rung 35
        raise ApiError("ERR_CHAMBER_CAPACITY_EXCEEDED")

    rec = store.new_record({
        "cabinet_id": cabinet_id,
        "burn_in_chamber_id": chamber_id,
        "window_start": window_start,
        "window_end": window_end,
        "slots_required": slots_required,
        "drive_pct": drive_pct,
        "ambient_c": ambient_c,
        "occupied_until": occupied_until,
        "new_dead_pixel_count": None,
        "measured_brightness_nits": None,
        "measured_uniformity_pct": None,
        "cabinet_dead_pixel_ppm": None,
        "run_state": "SCHEDULED",
        "abort_reason": None,
        "completed_by_user_id": None,
    })
    store.burn_in_runs[rec["id"]] = rec

    store.touch(chamber)
    cab["cabinet_state"] = "BURN_IN"
    store.touch(cab)
    return envelope.object_response(serializers.burn_in_run(rec), 201)


@bp.route("/burn-in-runs/<burn_in_run_id>/complete", methods=["POST"])
def complete_run(burn_in_run_id):
    user_id, _ = auth.require("QAEngineer")
    body = v.body()
    new_dead = v.get_int(body, "new_dead_pixel_count", minimum=0)
    brightness = v.get_int(body, "measured_brightness_nits", minimum=0)
    uniformity = v.get_num(body, "measured_uniformity_pct", minimum=0)

    run = store.burn_in_runs.get(burn_in_run_id)           # rung 9
    if run is None:
        raise ApiError("ERR_RUN_NOT_FOUND")
    if run["run_state"] != "SCHEDULED":                    # rung 21
        raise ApiError("ERR_INVALID_RUN_STATE")
    if store.ms(store.logical_now()) < store.ms(run["window_end"]):   # rung 33
        raise ApiError("ERR_BURN_IN_WINDOW_NOT_ELAPSED")

    cab = store.cabinets.get(run["cabinet_id"])
    model = aggregates.model_of_cabinet(cab)
    ppm, _total = aggregates.cabinet_dead_pixel_ppm_with(cab, new_dead)

    run["new_dead_pixel_count"] = new_dead
    run["measured_brightness_nits"] = brightness
    run["measured_uniformity_pct"] = uniformity
    run["cabinet_dead_pixel_ppm"] = ppm
    run["completed_by_user_id"] = user_id

    passed = (to_fraction(ppm) <= to_fraction(model["dead_pixel_ppm_limit"])
              and brightness >= calc.BURN_IN_MIN_BRIGHTNESS_NITS
              and to_fraction(uniformity) >= calc.BURN_IN_MIN_UNIFORMITY_PCT)
    run["run_state"] = "PASSED" if passed else "FAILED"
    store.touch(run)

    chamber = store.burn_in_chambers.get(run["burn_in_chamber_id"])
    if chamber is not None:
        store.touch(chamber)

    if passed:
        mods = aggregates.installed_modules(cab["id"])
        samples = [(m["measured_brightness_nits"], m["measured_color_x"],
                    m["measured_color_y"]) for m in mods
                   if m["measured_brightness_nits"] is not None]
        cab["baseline_uniformity_score"] = calc.uniformity_score(samples)
        cab["baseline_module_ids"] = [m["id"] for m in mods]
        cab["cabinet_state"] = "BURN_IN_PASSED"
        store.touch(cab)
    else:
        cab["cabinet_state"] = "QUARANTINED"
        store.touch(cab)
        project = aggregates.project_of_cabinet(cab)
        if project is not None:
            aggregates.block_project(project)
    return envelope.object_response(serializers.burn_in_run(run))


@bp.route("/burn-in-runs/<burn_in_run_id>/abort", methods=["POST"])
def abort_run(burn_in_run_id):
    user_id, _ = auth.require("QAEngineer")
    body = v.body()
    reason = v.get_str(body, "reason", min_len=1)
    run = store.burn_in_runs.get(burn_in_run_id)           # rung 9
    if run is None:
        raise ApiError("ERR_RUN_NOT_FOUND")
    if run["run_state"] != "SCHEDULED":                    # rung 21
        raise ApiError("ERR_INVALID_RUN_STATE")

    run["run_state"] = "ABORTED"
    run["abort_reason"] = reason
    run["completed_by_user_id"] = user_id
    store.touch(run)

    chamber = store.burn_in_chambers.get(run["burn_in_chamber_id"])
    if chamber is not None:
        store.touch(chamber)
    cab = store.cabinets.get(run["cabinet_id"])
    if cab is not None:
        cab["cabinet_state"] = "POPULATED"
        store.touch(cab)
    return envelope.object_response(serializers.burn_in_run(run))


@bp.route("/burn-in-runs/<burn_in_run_id>", methods=["GET"])
def get_run(burn_in_run_id):
    auth.require(*auth.ALL_ROLES)
    run = store.burn_in_runs.get(burn_in_run_id)
    if run is None:
        raise ApiError("ERR_RUN_NOT_FOUND")
    return envelope.object_response(serializers.burn_in_run(run))


@bp.route("/burn-in-runs", methods=["GET"])
def list_runs():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    cabinet_id = v.query_str("cabinet_id")
    chamber_id = v.query_str("burn_in_chamber_id")
    state = v.query_enum("run_state", calc.RUN_STATES)
    rows = aggregates.by_created(store.burn_in_runs.values())
    if cabinet_id is not None:
        rows = [r for r in rows if r["cabinet_id"] == cabinet_id]
    if chamber_id is not None:
        rows = [r for r in rows if r["burn_in_chamber_id"] == chamber_id]
    if state is not None:
        rows = [r for r in rows if r["run_state"] == state]
    return envelope.paginated(rows, limit, offset, serializers.burn_in_run)
