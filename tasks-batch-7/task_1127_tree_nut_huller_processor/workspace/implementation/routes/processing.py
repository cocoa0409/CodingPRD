"""Dryers, drying batches, and processing runs (PRD §3.3, §3.4)."""
from flask import Blueprint, request

import db
import response
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_DRYER_NOT_FOUND, ERR_LOT_NOT_FOUND,
    ERR_DRYING_BATCH_NOT_FOUND, ERR_PROCESSING_RUN_NOT_FOUND,
    ERR_STALE_LOT_VERSION, ERR_INVALID_STATE, ERR_DRYER_TIME_CONFLICT,
    ERR_SCHEDULE_WINDOW_NOT_OPEN, ERR_SHRINK_NEGATIVE,
)
from middleware import authenticate, require_roles, body
from validate import (
    req_string, req_number, req_int, opt_enum_filter, check_range, check_state,
    is_int, RUN_STATUSES, RUN_TERMINAL, BATCH_STATUSES, BATCH_TERMINAL,
    LOT_TERMINAL,
)
from services import calc
from services.serialize import dryer_out, batch_out, run_out

bp = Blueprint("processing", __name__)

RUN_ROLES = ["PlantAdmin", "PlantOperator"]


# ------------------------------------------------------------------ dryers

@bp.route("/dryers", methods=["POST"])
def create_dryer():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    b = body()
    dryer_code = req_string(b, "dryer_code")
    capacity = check_range(req_int(b, "capacity_lbs"), "capacity_lbs", gt=0)
    for d in db.store.dryers.values():
        if d["dryer_code"] == dryer_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "dryer_code must be unique across dryers")
    rec = db.stamp({"id": db.new_id(), "dryer_code": dryer_code, "capacity_lbs": capacity})
    db.store.dryers[rec["id"]] = rec
    return response.ok(dryer_out(rec), 201)


@bp.route("/dryers", methods=["GET"])
def list_dryers():
    auth = authenticate()
    require_roles(auth, RUN_ROLES)
    return response.paginate(list(db.store.dryers.values()), dryer_out)


# ----------------------------------------------------------- drying batches

@bp.route("/drying-batches", methods=["POST"])
def create_batch():
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    b = body()
    # existence (3): canonical FK order — lot_id before dryer_id
    lot_id = b.get("lot_id")
    if lot_id is not None and lot_id not in db.store.lots:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found: %s" % lot_id)
    dryer_id = b.get("dryer_id")
    if dryer_id is not None and dryer_id not in db.store.dryers:
        raise ApiError(ERR_DRYER_NOT_FOUND, 404, "Dryer not found: %s" % dryer_id)
    # shape (5)
    lot_id = req_string(b, "lot_id")
    dryer_id = req_string(b, "dryer_id")
    start_raw = req_string(b, "start_at")
    end_raw = req_string(b, "end_at")
    start_dt = db.parse_iso(start_raw)
    end_dt = db.parse_iso(end_raw)
    if start_dt is None or end_dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "start_at and end_at must be ISO 8601 timestamps")
    if not (end_dt > start_dt):
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_at must be strictly later than start_at")
    lot = db.store.lots[lot_id]
    # state gate (6): the lot must already have a recorded MOISTURE_KERNEL test
    if calc.latest_test(lot["id"], "MOISTURE_KERNEL") is None:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Lot has no recorded MOISTURE_KERNEL lab test")
    # temporal (8): half-open overlap on the same dryer
    if calc.dryer_conflict(dryer_id, start_dt, end_dt):
        raise ApiError(ERR_DRYER_TIME_CONFLICT, 409,
                       "Dryer reservation overlaps an existing SCHEDULED/DRYING batch")
    rec = db.stamp({
        "id": db.new_id(),
        "dryer_id": dryer_id,
        "lot_id": lot_id,
        "start_at": start_raw,
        "end_at": end_raw,
        "final_moisture_pct": None,
        "status": "SCHEDULED",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.store.batches[rec["id"]] = rec
    return response.ok(batch_out(rec), 201)


@bp.route("/drying-batches", methods=["GET"])
def list_batches():
    auth = authenticate()
    require_roles(auth, RUN_ROLES)
    dryer_id = request.args.get("dryer_id")
    lot_id = request.args.get("lot_id")
    status = opt_enum_filter(request.args, "status", BATCH_STATUSES)
    items = list(db.store.batches.values())
    if dryer_id is not None:
        items = [x for x in items if x["dryer_id"] == dryer_id]
    if lot_id is not None:
        items = [x for x in items if x["lot_id"] == lot_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return response.paginate(items, batch_out)


def _get_batch_or_404(rid):
    rec = db.store.batches.get(rid)
    if rec is None:
        raise ApiError(ERR_DRYING_BATCH_NOT_FOUND, 404, "Drying batch not found: %s" % rid)
    return rec


@bp.route("/drying-batches/<rid>", methods=["GET"])
def get_batch(rid):
    auth = authenticate()
    require_roles(auth, RUN_ROLES)
    return response.ok(batch_out(_get_batch_or_404(rid)))


@bp.route("/drying-batches/<rid>/start", methods=["POST"])
def start_batch(rid):
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    batch = _get_batch_or_404(rid)
    check_state(batch, ("SCHEDULED",), BATCH_TERMINAL, "DryingBatch")
    if db.store.clock < batch["_start_dt"]:
        raise ApiError(ERR_SCHEDULE_WINDOW_NOT_OPEN, 422,
                       "The logical clock has not reached start_at")
    batch["status"] = "DRYING"
    db.touch(batch)
    return response.ok(batch_out(batch))


@bp.route("/drying-batches/<rid>/complete", methods=["POST"])
def complete_batch(rid):
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    batch = _get_batch_or_404(rid)
    b = body()
    # shape (5) before state (6)
    final_moisture = check_range(req_number(b, "final_moisture_pct"),
                                 "final_moisture_pct", gt=0, lt=100)
    check_state(batch, ("DRYING",), BATCH_TERMINAL, "DryingBatch")
    if db.store.clock < batch["_end_dt"]:
        raise ApiError(ERR_SCHEDULE_WINDOW_NOT_OPEN, 422,
                       "The logical clock has not reached end_at")
    batch["status"] = "COMPLETED"
    batch["final_moisture_pct"] = final_moisture
    db.touch(batch)
    lot = db.store.lots.get(batch["lot_id"])
    if lot is not None:
        lot["post_dry_moisture_pct"] = final_moisture
        db.touch(lot)
    return response.ok(batch_out(batch))


@bp.route("/drying-batches/<rid>/cancel", methods=["POST"])
def cancel_batch(rid):
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    batch = _get_batch_or_404(rid)
    check_state(batch, ("SCHEDULED",), BATCH_TERMINAL, "DryingBatch")
    batch["status"] = "CANCELLED"
    db.touch(batch)
    return response.ok(batch_out(batch))


# --------------------------------------------------------- processing runs

@bp.route("/processing-runs", methods=["POST"])
def create_run():
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    b = body()
    # existence (3)
    lot_id = b.get("lot_id")
    if lot_id is not None and lot_id not in db.store.lots:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found: %s" % lot_id)
    lot_id = req_string(b, "lot_id")
    lot = db.store.lots[lot_id]
    # OCC (4) before remaining shape (5)
    expected = b.get("expected_lot_version")
    if is_int(expected) and expected != lot["version"]:
        raise ApiError(ERR_STALE_LOT_VERSION, 412,
                       "expected_lot_version does not match the lot's current version")
    # shape (5)
    if "expected_lot_version" not in b or b["expected_lot_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: expected_lot_version")
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_lot_version must be an integer")
    # state (6)
    check_state(lot, ("ROUTED_IN_SHELL", "ROUTED_KERNEL", "PROCESSING"),
                LOT_TERMINAL, "FieldLot")
    # input snapshot: gross minus other non-CANCELLED runs' inputs
    used = sum(calc.D(r["input_weight_lbs"]) for r in db.store.runs.values()
               if r["lot_id"] == lot["id"] and r["status"] != "CANCELLED")
    input_weight = calc.round2(calc.D(lot["gross_weight_lbs"]) - used)
    rec = db.stamp({
        "id": db.new_id(),
        "lot_id": lot_id,
        "input_weight_lbs": input_weight,
        "kernel_out_lbs": None,
        "shell_out_lbs": None,
        "hull_out_lbs": None,
        "status": "QUEUED",
    })
    db.store.runs[rec["id"]] = rec
    # first non-cancelled run moves a routed lot into PROCESSING; every
    # creation increments the lot's version (PRD §2.7)
    if lot["status"] in ("ROUTED_IN_SHELL", "ROUTED_KERNEL"):
        lot["status"] = "PROCESSING"
    db.touch(lot)
    return response.ok(run_out(rec), 201)


@bp.route("/processing-runs", methods=["GET"])
def list_runs():
    auth = authenticate()
    require_roles(auth, RUN_ROLES)
    lot_id = request.args.get("lot_id")
    status = opt_enum_filter(request.args, "status", RUN_STATUSES)
    items = list(db.store.runs.values())
    if lot_id is not None:
        items = [r for r in items if r["lot_id"] == lot_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return response.paginate(items, run_out)


def _get_run_or_404(rid):
    rec = db.store.runs.get(rid)
    if rec is None:
        raise ApiError(ERR_PROCESSING_RUN_NOT_FOUND, 404, "Processing run not found: %s" % rid)
    return rec


@bp.route("/processing-runs/<rid>", methods=["GET"])
def get_run(rid):
    auth = authenticate()
    require_roles(auth, RUN_ROLES)
    return response.ok(run_out(_get_run_or_404(rid)))


@bp.route("/processing-runs/<rid>/start", methods=["POST"])
def start_run(rid):
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    run = _get_run_or_404(rid)
    check_state(run, ("QUEUED",), RUN_TERMINAL, "ProcessingRun")
    lot = db.store.lots[run["lot_id"]]
    if lot["status"] not in ("ROUTED_IN_SHELL", "ROUTED_KERNEL", "PROCESSING"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Run's lot is in state %s" % lot["status"])
    run["status"] = "RUNNING"
    db.touch(run)
    return response.ok(run_out(run))


@bp.route("/processing-runs/<rid>/complete", methods=["POST"])
def complete_run(rid):
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    run = _get_run_or_404(rid)
    b = body()
    # shape (5) before state (6)
    kernel = check_range(req_number(b, "kernel_out_lbs"), "kernel_out_lbs", ge=0)
    shell = check_range(req_number(b, "shell_out_lbs"), "shell_out_lbs", ge=0)
    hull = check_range(req_number(b, "hull_out_lbs"), "hull_out_lbs", ge=0)
    check_state(run, ("RUNNING",), RUN_TERMINAL, "ProcessingRun")
    # physical (9): non-negative shrink
    total_out = calc.D(kernel) + calc.D(shell) + calc.D(hull)
    if total_out > calc.D(run["input_weight_lbs"]):
        raise ApiError(ERR_SHRINK_NEGATIVE, 422,
                       "Run outputs exceed input weight (negative shrink)")
    run["kernel_out_lbs"] = calc.round2(kernel)
    run["shell_out_lbs"] = calc.round2(shell)
    run["hull_out_lbs"] = calc.round2(hull)
    run["status"] = "COMPLETED"
    db.touch(run)
    lot = db.store.lots[run["lot_id"]]
    if lot["status"] == "PROCESSING":
        lot["status"] = "PROCESSED"
    calc.recompute_graded_kernel_weight(lot)
    db.touch(lot)
    return response.ok(run_out(run))


@bp.route("/processing-runs/<rid>/cancel", methods=["POST"])
def cancel_run(rid):
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    run = _get_run_or_404(rid)
    check_state(run, ("QUEUED",), RUN_TERMINAL, "ProcessingRun")
    run["status"] = "CANCELLED"
    db.touch(run)
    return response.ok(run_out(run))
