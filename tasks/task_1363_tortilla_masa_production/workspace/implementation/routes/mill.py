"""IngredientLot + NixtamalBatch endpoints."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import domain as D
from db import store, mint, touch, now, fmt_dt
from errors import err
from middleware import authorize, ROLES
from response import ok, ok_list
from validate import (body, need_str, need_num, need_int, need_enum, opt_enum,
                      paginate)

bp = Blueprint("mill", __name__)


# ---- IngredientLot ----

@bp.post("/plant/ingredient-lots")
def create_lot():
    authorize(["PlantManager"])
    b = body()
    lot_code = need_str(b, "lot_code")
    corn_variety = need_enum(b, "corn_variety", D.CORN_VARIETIES)
    received_kg = need_num(b, "received_kg")
    moisture_pct = need_num(b, "moisture_pct")
    if received_kg <= 0:
        err("ERR_INVALID_REQUEST", 400, "received_kg must be greater than zero")
    if not (Decimal("0") < moisture_pct < Decimal("30")):
        err("ERR_INVALID_REQUEST", 400, "moisture_pct must lie strictly between 0 and 30")
    for l in store.ingredient_lots.values():
        if l["lot_code"] == lot_code:
            err("ERR_DUPLICATE_CODE", 409, "lot_code already exists")
    lot = mint()
    lot.update({"lot_code": lot_code, "corn_variety": corn_variety,
                "received_kg": received_kg, "moisture_pct": moisture_pct,
                "lot_status": "RECEIVED"})
    store.ingredient_lots[lot["id"]] = lot
    return ok(D.lot_json(lot), 201)


@bp.get("/plant/ingredient-lots")
def list_lots():
    authorize(ROLES)
    from flask import request
    status = request.args.get("lot_status")
    items = [l for l in store.ingredient_lots.values()
             if status is None or l["lot_status"] == status]
    page, limit, offset, total = paginate(items, D.lot_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/ingredient-lots/<lid>")
def get_lot(lid):
    authorize(ROLES)
    return ok(D.lot_json(D.get_lot(lid)))


@bp.post("/plant/ingredient-lots/<lid>/condition")
def condition_lot(lid):
    authorize(["MillerOperator"])
    b = body()
    decision = opt_enum(b, "decision", {"REJECT"})
    lot = D.get_lot(lid)
    if lot["lot_status"] != "RECEIVED":
        err("ERR_LOT_INVALID_STATE", 409, "Lot must be RECEIVED to condition")
    lot["lot_status"] = "REJECTED" if decision == "REJECT" else "CONDITIONED"
    touch(lot)
    return ok(D.lot_json(lot))


@bp.get("/plant/ingredient-lots/<lid>/batches")
def lot_batches(lid):
    authorize(ROLES)
    D.get_lot(lid)
    items = [b for b in store.nixtamal_batches.values() if b["ingredient_lot_id"] == lid]
    page, limit, offset, total = paginate(items, D.batch_json)
    return ok_list(page, limit, offset, total)


# ---- NixtamalBatch ----

@bp.post("/plant/nixtamal-batches")
def create_batch():
    authorize(["MillerOperator"])
    b = body()
    ingredient_lot_id = need_str(b, "ingredient_lot_id")
    corn_kg = need_num(b, "corn_kg")
    lime_pct = need_num(b, "lime_pct")
    cook_minutes = need_int(b, "cook_minutes")
    steep_target_hours = need_int(b, "steep_target_hours")
    if corn_kg <= 0:
        err("ERR_INVALID_REQUEST", 400, "corn_kg must be greater than zero")
    if not (Decimal("0.1") <= lime_pct <= Decimal("2.0")):
        err("ERR_VALIDATION", 422, "lime_pct must lie between 0.1 and 2.0 inclusive")
    if cook_minutes < 30:
        err("ERR_VALIDATION", 422, "cook_minutes must be at least 30")
    if steep_target_hours < 8:
        err("ERR_VALIDATION", 422, "steep_target_hours must be at least 8")
    lot = D.get_lot(ingredient_lot_id)
    if corn_kg > D.lot_available_kg(lot):
        err("ERR_VALIDATION", 422, "corn_kg exceeds the lot's available_kg")
    batch = mint()
    theoretical = D.r2(corn_kg * D.VARIETY_YIELD_FACTOR[lot["corn_variety"]])
    batch.update({
        "ingredient_lot_id": lot["id"], "corn_kg": corn_kg, "lime_pct": lime_pct,
        "cook_minutes": cook_minutes, "steep_target_hours": steep_target_hours,
        "cook_started_at": None, "steep_started_at": None, "recook_count": 0,
        "theoretical_masa_kg": theoretical, "actual_masa_kg": None,
        "masa_wasted_kg": None, "yield_variance_pct": None,
        "batch_status": "PLANNED",
    })
    store.nixtamal_batches[batch["id"]] = batch
    if lot["lot_status"] == "CONDITIONED" and D.lot_available_kg(lot) == 0:
        lot["lot_status"] = "DEPLETED"
        touch(lot)
    return ok(D.batch_json(batch), 201)


@bp.get("/plant/nixtamal-batches/<bid>")
def get_batch(bid):
    authorize(ROLES)
    return ok(D.batch_json(D.get_batch(bid)))


@bp.post("/plant/nixtamal-batches/<bid>/start-cook")
def start_cook(bid):
    authorize(["MillerOperator"])
    batch = D.get_batch(bid)
    if batch["batch_status"] != "PLANNED":
        err("ERR_BATCH_INVALID_STATE", 409, "Batch must be PLANNED to start cooking")
    lot = D.get_lot(batch["ingredient_lot_id"])
    if lot["lot_status"] != "CONDITIONED":
        err("ERR_LOT_INVALID_STATE", 409, "Ingredient lot must be CONDITIONED to start cooking")
    batch["cook_started_at"] = fmt_dt(now())
    batch["batch_status"] = "COOKING"
    touch(batch)
    return ok(D.batch_json(batch))


@bp.post("/plant/nixtamal-batches/<bid>/start-steep")
def start_steep(bid):
    authorize(["MillerOperator"])
    batch = D.get_batch(bid)
    if batch["batch_status"] != "COOKING":
        err("ERR_BATCH_INVALID_STATE", 409, "Batch must be COOKING to start steeping")
    from validate import parse_dt_value
    started = parse_dt_value(batch["cook_started_at"])
    if now() < started + timedelta(minutes=batch["cook_minutes"]):
        err("ERR_COOK_INCOMPLETE", 409, "cook_minutes have not elapsed since cook_started_at")
    batch["steep_started_at"] = fmt_dt(now())
    batch["batch_status"] = "STEEPING"
    touch(batch)
    return ok(D.batch_json(batch))


@bp.post("/plant/nixtamal-batches/<bid>/evaluate")
def evaluate_batch(bid):
    authorize(["QualityInspector"])
    b = body()
    decision = need_enum(b, "decision", D.EVALUATE_DECISIONS)
    batch = D.get_batch(bid)
    status = batch["batch_status"]
    if status == "STEEPING":
        from validate import parse_dt_value
        started = parse_dt_value(batch["steep_started_at"])
        if now() < started + timedelta(hours=batch["steep_target_hours"]):
            err("ERR_STEEP_INCOMPLETE", 409,
                "steep_target_hours have not elapsed since steep_started_at")
        if decision == "PASS":
            batch["batch_status"] = "MILLING"
        elif decision == "RECOOK":
            batch["batch_status"] = "COOKING"
            batch["recook_count"] += 1
            batch["cook_started_at"] = fmt_dt(now())
        else:  # REJECT
            batch["batch_status"] = "REJECTED"
        touch(batch)
        return ok(D.batch_json(batch))
    if status == "QUARANTINED":
        if decision != "REJECT":
            err("ERR_BATCH_INVALID_STATE", 409,
                "Only REJECT may be evaluated from QUARANTINED")
        batch["batch_status"] = "REJECTED"
        touch(batch)
        D.batch_quarantine_cascade(batch)  # idempotent re-fire
        return ok(D.batch_json(batch))
    err("ERR_BATCH_INVALID_STATE", 409, "Batch must be STEEPING or QUARANTINED to evaluate")


@bp.post("/plant/nixtamal-batches/<bid>/mill")
def mill_batch(bid):
    authorize(["MillerOperator"])
    b = body()
    milled_masa_kg = need_num(b, "milled_masa_kg")
    measured_moisture_pct = need_num(b, "measured_moisture_pct")
    masa_wasted_kg = need_num(b, "masa_wasted_kg")
    if milled_masa_kg <= 0:
        err("ERR_INVALID_REQUEST", 400, "milled_masa_kg must be greater than zero")
    if masa_wasted_kg < 0:
        err("ERR_VALIDATION", 422, "masa_wasted_kg may not be negative")
    if not (Decimal("0") <= measured_moisture_pct <= Decimal("100")):
        err("ERR_INVALID_REQUEST", 400, "measured_moisture_pct must lie between 0 and 100")
    batch = D.get_batch(bid)
    if batch["batch_status"] != "MILLING":
        err("ERR_BATCH_INVALID_STATE", 409, "Batch must be MILLING to mill")
    net = milled_masa_kg - masa_wasted_kg
    excess = measured_moisture_pct - D.TARGET_MASA_MOISTURE_PCT
    penalty = (excess if excess > 0 else Decimal("0")) / Decimal("100")
    actual = D.r2(net * (Decimal("1") - penalty))
    batch["actual_masa_kg"] = actual
    batch["masa_wasted_kg"] = D.r2(masa_wasted_kg)
    batch["yield_variance_pct"] = D.r2(
        (actual - batch["theoretical_masa_kg"]) / batch["theoretical_masa_kg"] * Decimal("100"))
    batch["batch_status"] = "MASA_AVAILABLE"
    touch(batch)
    return ok(D.batch_json(batch))


@bp.post("/plant/nixtamal-batches/<bid>/quarantine")
def quarantine_batch(bid):
    authorize(["QualityInspector"])
    batch = D.get_batch(bid)
    if batch["batch_status"] != "MASA_AVAILABLE":
        err("ERR_BATCH_INVALID_STATE", 409, "Batch must be MASA_AVAILABLE to quarantine")
    batch["batch_status"] = "QUARANTINED"
    touch(batch)
    D.batch_quarantine_cascade(batch)
    return ok(D.batch_json(batch))


@bp.post("/plant/nixtamal-batches/<bid>/release-quarantine")
def release_quarantine(bid):
    authorize(["QualityInspector"])
    batch = D.get_batch(bid)
    if batch["batch_status"] != "QUARANTINED":
        err("ERR_BATCH_INVALID_STATE", 409, "Batch must be QUARANTINED to release quarantine")
    batch["batch_status"] = "MASA_AVAILABLE"
    touch(batch)
    return ok(D.batch_json(batch))


@bp.get("/plant/nixtamal-batches/<bid>/allocations")
def batch_allocations(bid):
    authorize(ROLES)
    D.get_batch(bid)
    items = [a for a in store.allocations.values() if a["nixtamal_batch_id"] == bid]
    page, limit, offset, total = paginate(items, D.alloc_json)
    return ok_list(page, limit, offset, total)
