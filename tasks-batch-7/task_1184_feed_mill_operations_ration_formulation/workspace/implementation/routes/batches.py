"""Batches: scheduling, start/mix/release/rework/reject/cancel, and nested
weighment recording (PRD 3.6)."""
from flask import Blueprint, request

from db import STORE, make_record, bump, clock_now
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import (ser_batch, ser_weighment, sorted_items, line_window_conflict,
                      line_contamination, order_blocked, check_mix_tolerance,
                      bin_on_hand, bin_status, contract_pool, effective_spot_price,
                      contract_after_consumption, rhu, CENT)
from validation import get_body, req_str, req_tons, req_dt, bad, paginate

bp = Blueprint("batches", __name__)

READ_ROLES = {"MillManager", "Nutritionist", "Operator", "QualityTech"}


def _get_batch(bid):
    b = STORE["batches"].get(bid)
    if b is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Batch {bid} not found")
    return b


@bp.post("/api/batches")
def create_batch():
    uid, role = authenticate()
    data = get_body()
    order_id = req_str(data, "order_id")
    line_id = req_str(data, "line_id")
    target_tons = req_tons(data, "target_tons")
    start = req_dt(data, "planned_start_at")
    end = req_dt(data, "planned_end_at")
    if end <= start:
        bad("planned_end_at must be strictly after planned_start_at")
    authorize(role, uid, {"MillManager"})
    order = STORE["orders"].get(order_id)
    if order is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Order {order_id} not found")
    if line_id not in STORE["lines"]:
        raise ApiError("ERR_NOT_FOUND", 404, f"ProductionLine {line_id} not found")
    if line_window_conflict(line_id, start, end):
        raise ApiError("ERR_LINE_WINDOW_CONFLICT", 409,
                       "Window collides with another batch on the line (45-min buffer)")
    rec = make_record()
    rec.update(order_id=order_id, line_id=line_id, target_tons=target_tons,
               planned_start_at=start, planned_end_at=end,
               is_medicated=order["is_medicated"], mixed_at=None, status="PLANNED")
    STORE["batches"][rec["id"]] = rec
    return success(ser_batch(rec), 201)


@bp.get("/api/batches")
def list_batches():
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    order_id = request.args.get("order_id")
    line_id = request.args.get("line_id")
    status = request.args.get("status")
    items = sorted_items(STORE["batches"])
    if order_id is not None:
        items = [b for b in items if b["order_id"] == order_id]
    if line_id is not None:
        items = [b for b in items if b["line_id"] == line_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(items)
    return success([ser_batch(b) for b in page], 200, meta)


@bp.get("/api/batches/<bid>")
def get_batch(bid):
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    return success(ser_batch(_get_batch(bid)), 200)


@bp.post("/api/batches/<bid>/start")
def start_batch(bid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Operator"})
    b = _get_batch(bid)
    if b["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PLANNED batch can start")
    line = STORE["lines"][b["line_id"]]
    if line["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Production line is not ACTIVE")
    order = STORE["orders"][b["order_id"]]
    if order["status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order must be CONFIRMED or IN_PRODUCTION to start a batch")
    if order_blocked(order["id"]):
        raise ApiError("ERR_ORDER_BLOCKED", 409, "Order has a batch in HOLD")
    # Sequencing gate: a non-medicated batch may not follow medicated work on a
    # contaminated line until a VERIFIED flush postdates the last medicated mix.
    if not b["is_medicated"] and line_contamination(b["line_id"]) == "MEDICATED":
        raise ApiError("ERR_FLUSH_REQUIRED", 409,
                       "Line is MEDICATED-contaminated; a verified flush is required")
    if order["status"] == "CONFIRMED":
        order["status"] = "IN_PRODUCTION"
        bump(order)
    b["status"] = "BATCHING"
    bump(b)
    return success(ser_batch(b), 200)


@bp.post("/api/batches/<bid>/weighments")
def record_weighment(bid):
    uid, role = authenticate()
    data = get_body()
    ingredient_id = req_str(data, "ingredient_id")
    bin_id = req_str(data, "bin_id")
    actual_tons = req_tons(data, "actual_tons")
    authorize(role, uid, {"Operator"})
    b = _get_batch(bid)
    if ingredient_id not in STORE["ingredients"]:
        raise ApiError("ERR_NOT_FOUND", 404, f"Ingredient {ingredient_id} not found")
    bin_rec = STORE["bins"].get(bin_id)
    if bin_rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bin {bin_id} not found")
    # Layer 6 (state)
    if b["status"] != "BATCHING":
        raise ApiError("ERR_INVALID_STATE", 409, "Weighments record only while BATCHING")
    if bin_rec["blocked"]:
        raise ApiError("ERR_BIN_BLOCKED", 409, "Bin is BLOCKED")
    # Layer 9 (constraint), in the PRD's listed order
    if bin_rec["ingredient_id"] != ingredient_id:
        raise ApiError("ERR_BIN_INGREDIENT_MISMATCH", 422,
                       "Bin is assigned to a different ingredient")
    if bin_on_hand(bin_rec) < actual_tons:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 422,
                       "Bin stock does not cover the draw")
    order = STORE["orders"][b["order_id"]]
    if not any(l["ingredient_id"] == ingredient_id for l in order["pinned_lines"]):
        raise ApiError("ERR_INGREDIENT_NOT_IN_FORMULA", 422,
                       "Weighed ingredient is not in the order's pinned lines")
    T = clock_now()
    spot = effective_spot_price(ingredient_id, T)
    if spot is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Ingredient has no effective spot price at the current clock")
    # Contract selector: all-or-nothing per weighment (scaffold weighment_pricing).
    pool = contract_pool(ingredient_id, T, min_cover=actual_tons)
    if pool:
        contract = pool[0]
        source, contract_id, unit_price = "CONTRACT", contract["id"], contract["fixed_price_cents_per_ton"]
    else:
        contract = None
        source, contract_id, unit_price = "SPOT", None, spot
    rec = make_record()
    rec.update(batch_id=bid, ingredient_id=ingredient_id, bin_id=bin_id,
               actual_tons=actual_tons, source=source, contract_id=contract_id,
               unit_price_cents=unit_price,
               line_cost_cents=int(rhu(actual_tons * unit_price, CENT)),
               status="RECORDED")
    before = bin_status(bin_rec)
    STORE["weighments"][rec["id"]] = rec
    if bin_status(bin_rec) != before:  # READY -> EMPTY on an exact drawdown
        bump(bin_rec)
    if contract is not None:
        contract_after_consumption(contract)
    return success(ser_weighment(rec), 201)


@bp.post("/api/batches/<bid>/mix")
def mix_batch(bid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Operator"})
    b = _get_batch(bid)
    if b["status"] != "BATCHING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a BATCHING batch can be mixed")
    order = STORE["orders"][b["order_id"]]
    check_mix_tolerance(b, order)
    b["mixed_at"] = clock_now()
    b["status"] = "MIXED"
    bump(b)
    return success(ser_batch(b), 200)


@bp.post("/api/batches/<bid>/release")
def release_batch(bid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"QualityTech"})
    b = _get_batch(bid)
    if b["status"] != "MIXED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a MIXED batch can be released")
    if not any(s["batch_id"] == bid and s["result"] == "PASS"
               for s in STORE["samples"].values()):
        raise ApiError("ERR_QUALITY_NOT_PASSED", 409,
                       "No PASS quality sample exists for this batch")
    b["status"] = "RELEASED"
    bump(b)
    return success(ser_batch(b), 200)


@bp.post("/api/batches/<bid>/rework")
def rework_batch(bid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Operator"})
    b = _get_batch(bid)
    if b["status"] != "HOLD":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a HOLD batch can be reworked")
    b["status"] = "BATCHING"
    bump(b)
    return success(ser_batch(b), 200)


@bp.post("/api/batches/<bid>/reject")
def reject_batch(bid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"QualityTech"})
    b = _get_batch(bid)
    if b["status"] != "HOLD":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a HOLD batch can be rejected")
    b["status"] = "REJECTED"
    bump(b)
    return success(ser_batch(b), 200)


@bp.post("/api/batches/<bid>/cancel")
def cancel_batch(bid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    b = _get_batch(bid)
    if b["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PLANNED batch can be cancelled")
    b["status"] = "CANCELLED"
    bump(b)
    return success(ser_batch(b), 200)
