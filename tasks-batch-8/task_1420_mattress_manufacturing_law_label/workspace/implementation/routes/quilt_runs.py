"""QuiltRun scheduling endpoints."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_enum, as_string, body, require
from services import calc, cascade

bp = Blueprint("quilt_runs", __name__)

SIZES = {"TWIN", "FULL", "QUEEN", "KING", "CAL_KING"}


def run_view(r):
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "machine_id": r["machine_id"],
        "size": r["size"],
        "start_at": r["start_at"],
        "end_at": r["end_at"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def get_run(run_id):
    r = db.quilt_runs.get(run_id)
    if r is None:
        errors.raise_err(errors.ERR_QUILT_RUN_NOT_FOUND, "quilt run not found")
    return r


@bp.route("/quilt-runs", methods=["POST"])
def create_run():
    middleware.require_roles(["LineSupervisor"])
    data = body()
    order_id = as_string(require(data, "order_id"), "order_id")
    if order_id not in db.orders:
        errors.raise_err(errors.ERR_ORDER_NOT_FOUND, "order not found")
    machine_id = as_string(require(data, "machine_id"), "machine_id")
    size = as_enum(require(data, "size"), "size", SIZES)
    start_raw = require(data, "start_at")
    end_raw = require(data, "end_at")
    start = clock.try_parse(start_raw) if isinstance(start_raw, str) else None
    end = clock.try_parse(end_raw) if isinstance(end_raw, str) else None
    if start is None or end is None:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "start_at and end_at must be ISO8601 timestamps")
    if not end > start:
        errors.raise_err(errors.ERR_INVALID_TIME_RANGE, "end_at must be strictly after start_at")
    # tier 8: pairwise machine exclusion (half-open)
    if calc.quilt_machine_conflict(machine_id, start, end):
        errors.raise_err(errors.ERR_MACHINE_TIME_CONFLICT, "machine time conflict")
    run = {
        "id": db.new_id(),
        "order_id": order_id,
        "machine_id": machine_id,
        "size": size,
        # input-supplied datetimes are echoed verbatim (comparisons parse them)
        "start_at": start_raw,
        "end_at": end_raw,
        "status": "SCHEDULED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.quilt_runs, run)
    return response.success_object(run_view(run), 201)


@bp.route("/quilt-runs", methods=["GET"])
def list_runs():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.quilt_runs.values())
    q = request.args.get("machine_id")
    if q is not None:
        items = [r for r in items if r["machine_id"] == q]
    q = request.args.get("order_id")
    if q is not None:
        items = [r for r in items if r["order_id"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [r for r in items if r["status"] == q]
    items.sort(key=lambda r: r["_seq"])
    return response.success_list([run_view(r) for r in items])


@bp.route("/quilt-runs/<runId>", methods=["GET"])
def get_one_run(runId):
    middleware.require_roles(middleware.ALL_ROLES)
    r = get_run(runId)
    return response.success_object(run_view(r))


@bp.route("/quilt-runs/<runId>/start", methods=["POST"])
def start_run(runId):
    middleware.require_roles(["LineSupervisor"])
    run = get_run(runId)
    if run["status"] != "SCHEDULED":
        errors.raise_err(errors.ERR_RUN_NOT_SCHEDULED, "run must be SCHEDULED")
    if clock.now() < clock.iso_parse(run["start_at"]):
        errors.raise_err(errors.ERR_RUN_WINDOW_NOT_REACHED, "run window not reached")
    run["status"] = "RUNNING"
    cascade.bump(run)
    return response.success_object(run_view(run))


@bp.route("/quilt-runs/<runId>/complete", methods=["POST"])
def complete_run(runId):
    middleware.require_roles(["LineSupervisor"])
    run = get_run(runId)
    if run["status"] != "RUNNING":
        errors.raise_err(errors.ERR_RUN_NOT_RUNNING, "run must be RUNNING")
    run["status"] = "COMPLETE"
    cascade.bump(run)
    return response.success_object(run_view(run))


@bp.route("/quilt-runs/<runId>/cancel", methods=["POST"])
def cancel_run(runId):
    middleware.require_roles(["LineSupervisor"])
    run = get_run(runId)
    if run["status"] != "SCHEDULED":
        errors.raise_err(errors.ERR_RUN_NOT_SCHEDULED, "run must be SCHEDULED")
    run["status"] = "CANCELLED"
    cascade.bump(run)
    return response.success_object(run_view(run))
