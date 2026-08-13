"""Batch endpoints: planning, blending, QA verdicts, adjustments, condemn, release."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from domain import (MIN_BATCH_LITERS, REBLEND_LIMIT, TANK_GAP_HOURS,
                    TANK_OCCUPYING_BATCH_STATES, ser_batch, ser_process_run, ser_run)
from errors import err
from routes_formulas import get_formula_or_404
from routes_tanks import get_tank_or_404
from services import condemn_cascade
from store import db, iso_ms, stamp, touch, trunc_minute
from util import body, ok, paginate, req_field, require_any, require_roles

bp = Blueprint("batches", __name__)


def get_batch_or_404(batch_id):
    batch = db.batches.get(batch_id)
    if batch is None:
        raise err("ERR_BATCH_NOT_FOUND", f"Batch {batch_id} not found")
    return batch


def _dec(value):
    return Decimal(str(value))


def _tenth(value):
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_loss(batch):
    """Book process loss: 2% of quantity, 0.1 L half-up; processed remainder."""
    quantity = _dec(batch["quantity_liters"])
    loss = (quantity * Decimal("0.02")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    batch["loss_liters"] = float(loss)
    batch["processed_liters"] = float(quantity - loss)


@bp.post("/v1/batches")
def create_batch():
    require_roles("BlendOperator")
    data = body()
    formula_id = req_field(data, "formula_id", "str")
    tank_id = req_field(data, "tank_id", "str")
    planned_start = req_field(data, "planned_start_at", "datetime")
    planned_end = req_field(data, "planned_end_at", "datetime")
    quantity = req_field(data, "quantity_liters", "num")
    formula = get_formula_or_404(formula_id)
    tank = get_tank_or_404(tank_id)
    # category 5: tank posture
    if tank["posture"] != "AVAILABLE":
        raise err("ERR_TANK_STATE_INVALID", "Tank must stand AVAILABLE to take a batch")
    # category 8: structural constraints
    if planned_end <= planned_start:
        raise err("ERR_INVALID_WINDOW", "planned_end_at must be strictly after planned_start_at")
    quantity = _tenth(_dec(quantity))
    if quantity > tank["capacity_liters"]:
        raise err("ERR_TANK_CAPACITY_EXCEEDED", "quantity_liters exceeds tank capacity")
    if quantity < MIN_BATCH_LITERS:
        raise err("ERR_BATCH_TOO_SMALL", "quantity_liters must be at least 500 liters")
    gap = timedelta(hours=TANK_GAP_HOURS)
    new_start = trunc_minute(planned_start)
    new_end = trunc_minute(planned_end)
    for other in db.batches.values():
        if other["tank_id"] != tank_id or other["status"] not in TANK_OCCUPYING_BATCH_STATES:
            continue
        old_start = trunc_minute(other["_planned_start_dt"])
        old_end = trunc_minute(other["_planned_end_dt"])
        if new_end + gap <= old_start or old_end + gap <= new_start:
            continue
        raise err("ERR_TANK_WINDOW_CONFLICT",
                  "Tank window conflicts with an existing booking (3h gap required)")
    batch = {
        "formula_id": formula_id,
        "tank_id": tank_id,
        "planned_start_at": iso_ms(planned_start),
        "planned_end_at": iso_ms(planned_end),
        "_planned_start_dt": planned_start,
        "_planned_end_dt": planned_end,
        "quantity_liters": quantity,
        "initial_quantity_liters": quantity,
        "measured_brix": None,
        "added_water_liters": 0.0,
        "added_concentrate_liters": 0.0,
        "adjustment_count": 0,
        "blended_by_user_id": None,
        "linked_run_id": None,
        "loss_liters": None,
        "processed_liters": None,
        "status": "PLANNED",
    }
    stamp(batch)
    db.batches[batch["id"]] = batch
    tank["posture"] = "OCCUPIED"
    tank["occupying_batch_id"] = batch["id"]
    tank["allergen_group"] = formula["allergen_group"]
    touch(tank)
    return ok(ser_batch(batch), 201)


@bp.get("/v1/batches")
def list_batches():
    require_any()
    formula_id = request.args.get("formula_id")
    tank_id = request.args.get("tank_id")
    status = request.args.get("status")
    items = list(db.batches.values())
    if formula_id is not None:
        items = [b for b in items if b["formula_id"] == formula_id]
    if tank_id is not None:
        items = [b for b in items if b["tank_id"] == tank_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate(items, ser_batch)


@bp.get("/v1/batches/<batch_id>")
def get_batch(batch_id):
    require_any()
    return ok(ser_batch(get_batch_or_404(batch_id)))


@bp.post("/v1/batches/<batch_id>/start-blend")
def start_blend(batch_id):
    require_roles("BlendOperator")
    batch = get_batch_or_404(batch_id)
    if batch["status"] != "PLANNED":
        raise err("ERR_BATCH_STATE_INVALID", "start-blend requires status PLANNED")
    tank = get_tank_or_404(batch["tank_id"])
    if tank["posture"] != "OCCUPIED" or tank.get("occupying_batch_id") != batch_id:
        raise err("ERR_TANK_STATE_INVALID", "Tank must be OCCUPIED by this batch")
    batch["status"] = "BLENDING"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/v1/batches/<batch_id>/record-blend")
def record_blend(batch_id):
    user_id, _ = require_roles("BlendOperator")
    batch = get_batch_or_404(batch_id)
    data = body()
    measured = req_field(data, "measured_brix", "num")
    if batch["status"] != "BLENDING":
        raise err("ERR_BATCH_STATE_INVALID", "record-blend requires status BLENDING")
    batch["measured_brix"] = measured
    batch["blended_by_user_id"] = user_id
    batch["status"] = "AWAITING_QA"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/v1/batches/<batch_id>/qa-verdict")
def qa_verdict(batch_id):
    user_id, _ = require_roles("QAInspector")
    batch = get_batch_or_404(batch_id)
    data = body()
    verdict = req_field(data, "verdict", "str")
    if verdict not in ("PASS", "FAIL"):
        raise err("ERR_INVALID_REQUEST", "verdict must be PASS or FAIL")
    if batch["status"] != "AWAITING_QA":
        raise err("ERR_BATCH_STATE_INVALID", "qa-verdict requires status AWAITING_QA")
    if user_id == batch["blended_by_user_id"]:
        raise err("ERR_SOD_QA_SELF_APPROVAL",
                  "QA actor must differ from the blending operator")
    if verdict == "PASS":
        formula = get_formula_or_404(batch["formula_id"])
        diff = abs(_dec(batch["measured_brix"]) - _dec(formula["target_brix"]))
        if diff > _dec(formula["brix_tolerance"]):
            raise err("ERR_BRIX_OUT_OF_TOLERANCE",
                      "Measured brix is outside the inclusive tolerance band")
        batch["status"] = "QA_PASSED"
    else:
        batch["status"] = "QA_FAILED"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/v1/batches/<batch_id>/apply-adjustment")
def apply_adjustment(batch_id):
    require_roles("BlendOperator")
    batch = get_batch_or_404(batch_id)
    if batch["status"] != "QA_FAILED":
        raise err("ERR_BATCH_STATE_INVALID", "apply-adjustment requires status QA_FAILED")
    if batch["adjustment_count"] >= REBLEND_LIMIT:
        raise err("ERR_REBLEND_LIMIT_EXCEEDED", "At most two adjustments are permitted")
    formula = get_formula_or_404(batch["formula_id"])
    measured = _dec(batch["measured_brix"])
    target = _dec(formula["target_brix"])
    tolerance = _dec(formula["brix_tolerance"])
    diff = measured - target
    if abs(diff) <= tolerance:
        raise err("ERR_NOTHING_TO_ADJUST", "Measured brix sits inside the tolerance band")
    quantity = _dec(batch["quantity_liters"])
    if diff > 0:
        addition = quantity * diff / target
        to_water = True
    else:
        addition = quantity * (target - measured) / (_dec(formula["concentrate_brix"]) - target)
        to_water = False
    addition = addition.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    tank = get_tank_or_404(batch["tank_id"])
    if quantity + addition > _dec(tank["capacity_liters"]):
        raise err("ERR_ADJUSTMENT_EXCEEDS_TANK_CAPACITY",
                  "Computed addition would overflow the tank")
    if to_water:
        batch["added_water_liters"] = float(_dec(batch["added_water_liters"]) + addition)
    else:
        batch["added_concentrate_liters"] = float(_dec(batch["added_concentrate_liters"]) + addition)
    batch["quantity_liters"] = float(quantity + addition)
    batch["adjustment_count"] += 1
    batch["status"] = "BLENDING"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/v1/batches/<batch_id>/condemn")
def condemn_batch(batch_id):
    user_id, _ = require_roles("QAInspector")
    batch = get_batch_or_404(batch_id)
    if batch["status"] not in ("QA_FAILED", "PROCESSED", "RELEASED"):
        raise err("ERR_BATCH_STATE_INVALID",
                  "condemn requires status QA_FAILED, PROCESSED or RELEASED")
    if user_id == batch["blended_by_user_id"]:
        raise err("ERR_SOD_QA_SELF_APPROVAL",
                  "QA actor must differ from the blending operator")
    condemn_cascade(batch)
    batch["status"] = "CONDEMNED"
    touch(batch)
    return ok(ser_batch(batch))


@bp.post("/v1/batches/<batch_id>/release")
def release_batch(batch_id):
    user_id, _ = require_roles("QAInspector")
    batch = get_batch_or_404(batch_id)
    if batch["status"] not in ("PROCESSED", "PROCESSING"):
        raise err("ERR_BATCH_STATE_INVALID",
                  "release requires status PROCESSED or PROCESSING")
    if user_id == batch["blended_by_user_id"]:
        raise err("ERR_SOD_QA_SELF_APPROVAL",
                  "QA actor must differ from the blending operator")
    if batch["status"] == "PROCESSING":
        governing = None
        candidates = [p for p in db.process_runs.values()
                      if p["batch_id"] == batch_id and p["status"] != "ABORTED"]
        if candidates:
            governing = max(candidates, key=lambda p: p["_seq"])
        if governing is None or governing["status"] not in ("VALIDATED", "DISPOSITION_RELEASED"):
            raise err("ERR_PROCESS_NOT_VALIDATED",
                      "Governing process run must be VALIDATED or DISPOSITION_RELEASED")
        if batch["loss_liters"] is None:
            compute_loss(batch)
    batch["status"] = "RELEASED"
    touch(batch)
    return ok(ser_batch(batch))


@bp.get("/v1/batches/<batch_id>/process-runs")
def batch_process_runs(batch_id):
    require_any()
    get_batch_or_404(batch_id)
    items = [p for p in db.process_runs.values() if p["batch_id"] == batch_id]
    return paginate(items, ser_process_run)


@bp.get("/v1/batches/<batch_id>/production-runs")
def batch_production_runs(batch_id):
    require_any()
    get_batch_or_404(batch_id)
    items = [r for r in db.runs.values() if r.get("batch_id") == batch_id]
    return paginate(items, ser_run)
