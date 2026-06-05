"""Machine, run-log, and OEE endpoints (PRD §3.2, §3.3)."""
from flask import Blueprint, request

import db
import errors
import lookups
import validators as V
from middleware import authenticate, authorize, get_json_body
from response import object_response, array_response
from serialize import public, public_list
from services import calc

bp = Blueprint("machines", __name__)

MACHINE_STATUSES = {"AVAILABLE", "RUNNING", "DOWN"}


@bp.route("/machines", methods=["POST"])
def create_machine():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "PlantAdmin"])
    body = get_json_body()

    machine_code = V.as_string(V.require(body, "machine_code"), "machine_code")
    work_center = V.as_string(V.require(body, "work_center"), "work_center")
    planned = V.as_int(V.require(body, "planned_production_secs"), "planned_production_secs")
    if planned <= 0:
        raise errors.invalid_request("planned_production_secs must be > 0.")

    with db.LOCK:
        for m in db.machines.values():
            if m["machine_code"] == machine_code:
                raise errors.invalid_request("machine_code must be unique.")
        rec = db.new_record()
        rec.update({
            "machine_code": machine_code,
            "work_center": work_center,
            "status": "AVAILABLE",
            "planned_production_secs": planned,
            "oee_availability": 0,
            "oee_performance": 0,
            "oee_quality": 0,
            "oee_overall": 0,
            "quality_flagged": False,
        })
        db.machines[rec["id"]] = rec
        return object_response(public(rec), 201)


@bp.route("/machines/<rid>", methods=["GET"])
def get_machine(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    return object_response(public(lookups.machine(rid)))


@bp.route("/machines/<rid>/operations", methods=["GET"])
def list_machine_operations(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator", "PlantAdmin"])
    lookups.machine(rid)
    limit, offset = V.parse_pagination(request.args)
    rows = [o for o in db.operations.values() if o["machine_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.route("/machines/<rid>/status", methods=["POST"])
def set_machine_status(rid):
    _, role = authenticate()
    authorize(role, ["MachineOperator", "PlantAdmin"])
    body = get_json_body()
    with db.LOCK:
        machine = lookups.machine(rid)
        status = V.as_enum(V.require(body, "status"), "status", MACHINE_STATUSES)
        machine["status"] = status
        db.touch(machine)
        return object_response(public(machine))


@bp.route("/machines/<rid>/run-logs", methods=["POST"])
def add_run_log(rid):
    _, role = authenticate()
    authorize(role, ["MachineOperator", "PlantAdmin"])
    body = get_json_body()
    with db.LOCK:
        machine = lookups.machine(rid)

        window_start = V.as_datetime(V.require(body, "window_start"), "window_start")
        window_end = V.as_datetime(V.require(body, "window_end"), "window_end")
        run_time = V.as_int(V.require(body, "run_time_secs"), "run_time_secs")
        total_units = V.as_int(V.require(body, "total_units"), "total_units")
        good_units = V.as_int(V.require(body, "good_units"), "good_units")

        ws = V.parse_dt(window_start)
        we = V.parse_dt(window_end)
        if we <= ws:
            raise errors.invalid_request("window_end must be strictly after window_start.")
        duration = (we - ws).total_seconds()
        if run_time < 0 or run_time > duration:
            raise errors.invalid_request("run_time_secs must be >= 0 and <= window duration.")
        if total_units < 0:
            raise errors.invalid_request("total_units must be >= 0.")
        if good_units < 0 or good_units > total_units:
            raise errors.invalid_request("good_units must be >= 0 and <= total_units.")

        # ERR_RUNLOG_OVERLAP (priority 9): half-open [start, end). Touching ends OK.
        for log in db.machine_run_logs.values():
            if log["machine_id"] != rid:
                continue
            ls = V.parse_dt(log["window_start"])
            le = V.parse_dt(log["window_end"])
            if ws < le and ls < we:  # genuine overlap of half-open intervals
                raise errors.ApiError(errors.ERR_RUNLOG_OVERLAP,
                                      "Run-log window overlaps an existing window.", 409)

        rec = db.new_record()
        rec.update({
            "machine_id": rid,
            "window_start": window_start,
            "window_end": window_end,
            "run_time_secs": run_time,
            "total_units": total_units,
            "good_units": good_units,
        })
        db.machine_run_logs[rec["id"]] = rec
        return object_response(public(rec), 201)


@bp.route("/machines/<rid>/run-logs", methods=["GET"])
def list_run_logs(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    lookups.machine(rid)
    limit, offset = V.parse_pagination(request.args)
    rows = [l for l in db.machine_run_logs.values() if l["machine_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.route("/machines/<rid>/recompute-oee", methods=["POST"])
def recompute_oee(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "QualityInspector", "PlantAdmin"])
    with db.LOCK:
        machine = lookups.machine(rid)
        calc.recompute_oee(machine)
        db.touch(machine)
        return object_response(public(machine))
