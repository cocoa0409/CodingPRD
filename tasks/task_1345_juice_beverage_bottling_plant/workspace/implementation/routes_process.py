"""ProcessRun endpoints: schedule, start, complete, abort, QA disposition."""
from decimal import Decimal

from flask import Blueprint

from domain import (HPP_MINOR_PRESSURE_DROP_MPA, HPP_MINOR_TIME_S,
                    PASTE_MINOR_TEMP_DROP_C, PASTE_MINOR_TIME_S, ser_process_run)
from errors import err
from routes_batches import compute_loss, get_batch_or_404
from routes_formulas import get_formula_or_404
from services import condemn_cascade
from store import db, stamp, touch
from util import body, ok, req_field, require_any, require_roles

bp = Blueprint("process_runs", __name__)


def get_process_run_or_404(run_id):
    run = db.process_runs.get(run_id)
    if run is None:
        raise err("ERR_PROCESS_RUN_NOT_FOUND", f"ProcessRun {run_id} not found")
    return run


def _num(v):
    return Decimal(str(v))


@bp.post("/v1/process-runs")
def create_process_run():
    require_roles("BlendOperator")
    data = body()
    batch_id = req_field(data, "batch_id", "str")
    batch = get_batch_or_404(batch_id)
    for sibling in db.process_runs.values():
        if sibling["batch_id"] == batch_id and sibling["status"] in ("SCHEDULED", "RUNNING"):
            raise err("ERR_PROCESS_RUN_ACTIVE_EXISTS",
                      "Batch already has a SCHEDULED or RUNNING process run")
    if batch["status"] != "QA_PASSED":
        raise err("ERR_BATCH_STATE_INVALID",
                  "Process runs can only be scheduled for QA_PASSED batches")
    formula = get_formula_or_404(batch["formula_id"])
    process_type = formula["process_type"]
    if process_type == "PASTEURIZATION":
        setpoint_temp = req_field(data, "setpoint_temp_c", "num")
        setpoint_hold = req_field(data, "setpoint_hold_seconds", "int")
        setpoint_pressure = None
        setpoint_pressure_hold = None
    else:
        setpoint_pressure = req_field(data, "setpoint_pressure_mpa", "num")
        setpoint_pressure_hold = req_field(data, "setpoint_pressure_hold_seconds", "int")
        setpoint_temp = None
        setpoint_hold = None
    run = {
        "batch_id": batch_id,
        "process_type": process_type,
        "setpoint_temp_c": setpoint_temp,
        "setpoint_hold_seconds": setpoint_hold,
        "setpoint_pressure_mpa": setpoint_pressure,
        "setpoint_pressure_hold_seconds": setpoint_pressure_hold,
        "min_temp_c": None,
        "time_below_setpoint_seconds": None,
        "min_pressure_mpa": None,
        "pressure_hold_shortfall_seconds": None,
        "deviation_class": None,
        "status": "SCHEDULED",
    }
    stamp(run)
    db.process_runs[run["id"]] = run
    return ok(ser_process_run(run), 201)


@bp.get("/v1/process-runs/<run_id>")
def get_process_run(run_id):
    require_any()
    return ok(ser_process_run(get_process_run_or_404(run_id)))


@bp.post("/v1/process-runs/<run_id>/start")
def start_process_run(run_id):
    require_roles("BlendOperator")
    run = get_process_run_or_404(run_id)
    if run["status"] != "SCHEDULED":
        raise err("ERR_PROCESS_RUN_STATE_INVALID", "start requires status SCHEDULED")
    batch = get_batch_or_404(run["batch_id"])
    if batch["status"] != "QA_PASSED":
        raise err("ERR_BATCH_STATE_INVALID", "Batch must stand in QA_PASSED")
    run["status"] = "RUNNING"
    touch(run)
    batch["status"] = "PROCESSING"
    touch(batch)
    tank = db.tanks.get(batch["tank_id"])
    if tank is not None and tank["posture"] == "OCCUPIED" and tank.get("occupying_batch_id") == batch["id"]:
        tank["posture"] = "AWAITING_CIP"
        tank["occupying_batch_id"] = None
        touch(tank)
    return ok(ser_process_run(run))


@bp.post("/v1/process-runs/<run_id>/complete")
def complete_process_run(run_id):
    require_roles("BlendOperator")
    run = get_process_run_or_404(run_id)
    data = body()
    if run["status"] != "RUNNING":
        raise err("ERR_PROCESS_RUN_STATE_INVALID", "complete requires status RUNNING")
    batch = get_batch_or_404(run["batch_id"])
    if run["process_type"] == "PASTEURIZATION":
        min_temp = _num(req_field(data, "min_temp_c", "num"))
        time_below = req_field(data, "time_below_setpoint_seconds", "int")
        run["min_temp_c"] = data["min_temp_c"]
        run["time_below_setpoint_seconds"] = time_below
        setpoint = _num(run["setpoint_temp_c"])
        if min_temp >= setpoint and time_below == 0:
            status, deviation = "VALIDATED", "NONE"
        elif min_temp >= setpoint - _num(PASTE_MINOR_TEMP_DROP_C) and time_below <= PASTE_MINOR_TIME_S:
            status, deviation = "DEVIATED", "MINOR"
        else:
            status, deviation = "DEVIATED", "MAJOR"
    else:
        min_pressure = _num(req_field(data, "min_pressure_mpa", "num"))
        shortfall = req_field(data, "pressure_hold_shortfall_seconds", "int")
        run["min_pressure_mpa"] = data["min_pressure_mpa"]
        run["pressure_hold_shortfall_seconds"] = shortfall
        setpoint = _num(run["setpoint_pressure_mpa"])
        if min_pressure >= setpoint and shortfall == 0:
            status, deviation = "VALIDATED", "NONE"
        elif min_pressure >= setpoint - _num(HPP_MINOR_PRESSURE_DROP_MPA) and shortfall <= HPP_MINOR_TIME_S:
            status, deviation = "DEVIATED", "MINOR"
        else:
            status, deviation = "DEVIATED", "MAJOR"
    run["status"] = status
    run["deviation_class"] = deviation
    touch(run)
    if status == "VALIDATED":
        batch["status"] = "PROCESSED"
        compute_loss(batch)
        touch(batch)
    return ok(ser_process_run(run))


@bp.post("/v1/process-runs/<run_id>/abort")
def abort_process_run(run_id):
    require_roles("BlendOperator")
    run = get_process_run_or_404(run_id)
    if run["status"] not in ("SCHEDULED", "RUNNING"):
        raise err("ERR_PROCESS_RUN_STATE_INVALID",
                  "abort requires status SCHEDULED or RUNNING")
    was_running = run["status"] == "RUNNING"
    run["status"] = "ABORTED"
    touch(run)
    if was_running:
        batch = get_batch_or_404(run["batch_id"])
        if batch["status"] == "PROCESSING":
            batch["status"] = "QA_PASSED"
            touch(batch)
    return ok(ser_process_run(run))


@bp.post("/v1/process-runs/<run_id>/qa-disposition")
def qa_disposition(run_id):
    user_id, _ = require_roles("QAInspector")
    run = get_process_run_or_404(run_id)
    data = body()
    disposition = req_field(data, "disposition", "str")
    if disposition not in ("RELEASE", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "disposition must be RELEASE or REJECT")
    if run["status"] != "DEVIATED":
        raise err("ERR_PROCESS_RUN_STATE_INVALID", "qa-disposition requires status DEVIATED")
    batch = get_batch_or_404(run["batch_id"])
    if user_id == batch["blended_by_user_id"]:
        raise err("ERR_SOD_QA_SELF_APPROVAL",
                  "QA actor must differ from the blending operator")
    if disposition == "RELEASE":
        run["status"] = "DISPOSITION_RELEASED"
        touch(run)
        batch["status"] = "PROCESSED"
        compute_loss(batch)
        touch(batch)
    else:
        run["status"] = "DISPOSITION_REJECTED"
        touch(run)
        condemn_cascade(batch)
        batch["status"] = "CONDEMNED"
        touch(batch)
    return ok(ser_process_run(run))
