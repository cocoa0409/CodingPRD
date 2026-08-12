"""Batch lifecycle and IPC check endpoints."""
from flask import Blueprint, g, request

from core import (body, check_enum, err, get_required, list_page, new_entity,
                  require_roles, success, touch)
from services import (D, MAX_IPC_FAILURES, RAW_KINDS,
                      SCALE_UP_APPROVAL_THRESHOLD, consume_batch_allocations,
                      ipc_band, must_get, serialize_batch, serialize_ipc,
                      serialize_run)
from store import db, iso_now, new_id

bp = Blueprint("batches", __name__)

BATCH_READ_ROLES = ("ProductionPlanner", "QAManager", "PlantDirector")


@bp.get("/cosmfg/batches/<bid>")
@require_roles(*BATCH_READ_ROLES)
def get_batch(bid):
    return success(serialize_batch(must_get(db.batches, bid, "Batch")))


@bp.get("/cosmfg/batches/<bid>/filling-runs")
@require_roles(*BATCH_READ_ROLES)
def list_batch_runs(bid):
    batch = must_get(db.batches, bid, "Batch")
    items = [r for r in db.runs.values() if r["batch_id"] == batch["id"]]
    return list_page(items, serialize_run)


@bp.post("/cosmfg/batches/<bid>/approve-scale-up")
@require_roles("PlantDirector")
def approve_scale_up(bid):
    batch = must_get(db.batches, bid, "Batch")
    if batch["status"] != "PLANNED":
        err("ERR_INVALID_STATE", 409,
            "Scale-up approval applies to a PLANNED batch before mixing")
    batch["scale_up_approved"] = True
    touch(batch)
    return success(serialize_batch(batch))


@bp.post("/cosmfg/batches/<bid>/start-mixing")
@require_roles("ProductionPlanner")
def start_mixing(bid):
    batch = must_get(db.batches, bid, "Batch")
    if batch["status"] != "PLANNED":
        err("ERR_INVALID_STATE", 409, "Only a PLANNED batch may start mixing")
    order = db.orders.get(batch["production_order_id"])
    if order is None or order["status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        err("ERR_INVALID_STATE", 409,
            "The parent order must stand CONFIRMED or IN_PRODUCTION")
    if (D(batch["scale_up_factor"]) > SCALE_UP_APPROVAL_THRESHOLD
            and not batch["scale_up_approved"]):
        err("ERR_SCALE_UP_APPROVAL_REQUIRED", 422,
            "Batch scale_up_factor > 10 requires scale_up_approved before mixing")
    reserved_raw = D(0)
    for a in db.allocations.values():
        if a.get("batch_id") != batch["id"] or a["status"] != "RESERVED":
            continue
        lot = db.lots.get(a["lot_id"])
        comp = db.components.get(lot["component_id"]) if lot else None
        if comp is not None and comp["kind"] in RAW_KINDS:
            reserved_raw += D(a["quantity"])
    if reserved_raw < D(batch["batch_size_kg"]):
        err("ERR_BATCH_UNDER_ALLOCATED", 422,
            "Reserved raw-material mass for the batch is below batch_size_kg")
    batch["status"] = "MIXING"
    touch(batch)
    # First MIXING batch moves the order CONFIRMED -> IN_PRODUCTION
    if order["status"] == "CONFIRMED":
        order["status"] = "IN_PRODUCTION"
        touch(order)
    return success(serialize_batch(batch))


@bp.post("/cosmfg/batches/<bid>/ipc-checks")
@require_roles("QAManager")
def record_ipc_check(bid):
    batch = must_get(db.batches, bid, "Batch")
    if batch["status"] != "MIXING":
        err("ERR_INVALID_STATE", 409,
            "IPC checks may only be recorded on a MIXING batch")
    b = body()
    check_type = check_enum(get_required(b, "check_type"), {"VISCOSITY", "PH"},
                            "check_type")
    measured = get_required(b, "measured_value")
    if isinstance(measured, bool) or not isinstance(measured, (int, float)):
        err("ERR_VALIDATION", 400, "measured_value must be a number")
    order = db.orders.get(batch["production_order_id"])
    formula = db.formulas.get(order["formula_id"]) if order else None
    failures = batch["failed_check_count"]
    band = ipc_band(formula, check_type, failures)
    if check_type == "VISCOSITY":
        deviation = abs(D(measured) - D(formula["viscosity_target_cps"]))
    else:
        deviation = abs(D(measured) - D(formula["ph_target"]))
    result = "PASS" if deviation <= band else "FAIL"  # band edge passes
    ts = iso_now()
    check = {
        "id": new_id(),
        "batch_id": batch["id"],
        "check_type": check_type,
        "measured_value": measured,
        "round_index": 1 + failures,
        "effective_tolerance": float(band),
        "result": result,
        "recorded_by_user_id": g.user_id,
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    db.ipc_checks[check["id"]] = check
    batch["last_ipc_recorded_by_user_id"] = g.user_id
    if result == "FAIL":
        if check_type == "VISCOSITY":
            batch["round_viscosity_result"] = "FAIL"
        else:
            batch["round_ph_result"] = "FAIL"
        batch["failed_check_count"] = failures + 1
        batch["status"] = "IPC_FAILED"
    else:
        if check_type == "VISCOSITY":
            batch["round_viscosity_result"] = "PASS"
        else:
            batch["round_ph_result"] = "PASS"
        if (batch["round_viscosity_result"] == "PASS"
                and batch["round_ph_result"] == "PASS"):
            batch["status"] = "IPC_PASSED"
    touch(batch)
    return success(serialize_ipc(check), status=201)


@bp.get("/cosmfg/batches/<bid>/ipc-checks")
@require_roles("QAManager", "ProductionPlanner", "PlantDirector")
def list_ipc_checks(bid):
    batch = must_get(db.batches, bid, "Batch")
    items = [c for c in db.ipc_checks.values() if c["batch_id"] == batch["id"]]
    check_type = request.args.get("check_type")
    if check_type is not None:
        items = [c for c in items if c["check_type"] == check_type]
    return list_page(items, serialize_ipc)


@bp.post("/cosmfg/batches/<bid>/adjust")
@require_roles("QAManager")
def adjust_batch(bid):
    batch = must_get(db.batches, bid, "Batch")
    if batch["status"] != "IPC_FAILED":
        err("ERR_INVALID_STATE", 409, "Only an IPC_FAILED batch may be adjusted")
    if batch["failed_check_count"] >= MAX_IPC_FAILURES:
        err("ERR_IPC_ATTEMPTS_EXHAUSTED", 422,
            "Adjust rejected once failed_check_count has reached 3")
    batch["status"] = "MIXING"
    batch["round_viscosity_result"] = "NONE"
    batch["round_ph_result"] = "NONE"
    touch(batch)
    return success(serialize_batch(batch))


@bp.post("/cosmfg/batches/<bid>/release")
@require_roles("QAManager")
def release_batch(bid):
    batch = must_get(db.batches, bid, "Batch")
    # Segregation of duties (validation priority 3) is evaluated before the
    # state legality check.
    if (batch["last_ipc_recorded_by_user_id"] is not None
            and batch["last_ipc_recorded_by_user_id"] == g.user_id):
        err("ERR_SEGREGATION_OF_DUTIES", 403,
            "Batch release actor must differ from the user who recorded the "
            "batch's most recent IPC check")
    if batch["status"] != "IPC_PASSED":
        err("ERR_INVALID_STATE", 409, "Only an IPC_PASSED batch may be released")
    order = db.orders.get(batch["production_order_id"])
    formula_id = order["formula_id"] if order else None
    for s in db.studies.values():
        if s["formula_id"] == formula_id and s["status"] == "COMPLETED_FAIL":
            err("ERR_STUDY_FAILED_BLOCKS_RELEASE", 409,
                "A COMPLETED_FAIL stability study exists for the order's formula")
    batch["status"] = "RELEASED_TO_FILLING"
    touch(batch)
    return success(serialize_batch(batch))


@bp.post("/cosmfg/batches/<bid>/reject")
@require_roles("QAManager")
def reject_batch(bid):
    batch = must_get(db.batches, bid, "Batch")
    if batch["status"] not in ("MIXING", "IPC_FAILED"):
        err("ERR_INVALID_STATE", 409,
            "Only a MIXING or IPC_FAILED batch may be rejected")
    batch["status"] = "REJECTED"
    consume_batch_allocations(batch)
    touch(batch)
    return success(serialize_batch(batch))
