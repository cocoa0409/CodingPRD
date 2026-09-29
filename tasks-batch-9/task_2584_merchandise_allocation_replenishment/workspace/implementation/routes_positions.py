"""Store positions and DC receipts (PRD 3.3-3.4)."""
from flask import Blueprint, g

import derive as dv
import envelope as env
import guards as gd
import store as db
import validation as va
from auth import require, scope_check
from errors import ApiError

bp = Blueprint("positions", __name__)

STOCK_STATES = ("STOCKOUT", "LOW", "IN_STOCK", "OVERSTOCK")
ASSORTMENT_STATES = ("COMPLETE", "SIZE_OUT_RISK", "BROKEN", "EXITED")
RECEIPT_STATES = ("STAGED", "ALLOCATING", "ALLOCATED", "CLOSED")


def check_size_array(item, size_array, total, total_field):
    """Rungs 17 and 18, in that order."""
    if sum(entry["units"] for entry in size_array) != total:
        raise ApiError("ERR_SIZE_UNITS_MISMATCH")
    profile = dv.profile_of_item(item)
    known = {entry["size_code"] for entry in (profile["size_curve"] if profile else [])}
    for entry in size_array:
        if entry["size_code"] not in known:
            raise ApiError("ERR_SIZE_CODE_UNKNOWN")


# ================================ StorePosition ==============================
@bp.post("/allocation/store-positions")
@require("PlanningAdmin", "Allocator")
def create_position():
    data = va.body()
    store_id = va.get_str(data, "store_id")
    item_id = va.get_str(data, "item_id")
    on_hand = va.get_int(data, "on_hand_units", minimum=0)
    size_on_hand = va.get_size_array(data, "size_on_hand")
    on_order = va.get_int(data, "on_order_units", required=False, default=0, minimum=0)
    min_units = va.get_int(data, "min_units", minimum=0)
    max_units = va.get_int(data, "max_units", minimum=0)
    weekly = va.get_int(data, "weekly_forecast_units", minimum=0)
    trailing = va.get_int(data, "trailing_4wk_sales_units", minimum=0)
    if max_units < min_units:
        va.bad("max_units must be >= min_units.")
    store = gd.get_store(store_id)
    item = gd.get_item(item_id)
    if store["program_id"] != item["program_id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE")
    if dv.position_for(store["id"], item["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_POSITION")
    check_size_array(item, size_on_hand, on_hand, "on_hand_units")
    record = db.base_record()
    record.update(
        {
            "store_id": store["id"],
            "item_id": item["id"],
            "on_hand_units": on_hand,
            "size_on_hand": size_on_hand,
            "on_order_units": on_order,
            "min_units": min_units,
            "max_units": max_units,
            "weekly_forecast_units": weekly,
            "trailing_4wk_sales_units": trailing,
            "consolidated_out": False,
        }
    )
    db.positions[record["id"]] = record
    dv.propagate_position(record)
    return env.created(dv.position_out(record))


@bp.get("/allocation/store-positions/<position_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager", "StoreOperator")
def read_position(position_id):
    position = db.positions.get(position_id)
    if position is not None:
        scope_check(position["store_id"])
    return env.ok(dv.position_out(gd.get_position(position_id)))


@bp.get("/allocation/store-positions")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_positions():
    store_id = va.q_str("store_id")
    item_id = va.q_str("item_id")
    stock = va.q_enum("stock_status", STOCK_STATES)
    assortment = va.q_enum("assortment_status", ASSORTMENT_STATES)
    records = dv.by_created(list(db.positions.values()))
    if store_id:
        records = [r for r in records if r["store_id"] == store_id]
    if item_id:
        records = [r for r in records if r["item_id"] == item_id]
    if stock:
        records = [r for r in records if dv.stock_status(r) == stock]
    if assortment:
        records = [r for r in records if dv.assortment_status(r) == assortment]
    chunk, meta = va.page(records)
    return env.ok_array([dv.position_out(r) for r in chunk], meta)


@bp.patch("/allocation/store-positions/<position_id>")
@require("PlanningAdmin", "Allocator")
def patch_position(position_id):
    data = va.body()
    min_units = va.get_int(data, "min_units", required=False, minimum=0)
    max_units = va.get_int(data, "max_units", required=False, minimum=0)
    weekly = va.get_int(data, "weekly_forecast_units", required=False, minimum=0)
    trailing = va.get_int(data, "trailing_4wk_sales_units", required=False, minimum=0)
    on_order = va.get_int(data, "on_order_units", required=False, minimum=0)
    position = gd.get_position(position_id)
    new_min = position["min_units"] if min_units is None else min_units
    new_max = position["max_units"] if max_units is None else max_units
    if new_max < new_min:
        va.bad("max_units must be >= min_units.")
    position["min_units"] = new_min
    position["max_units"] = new_max
    if weekly is not None:
        position["weekly_forecast_units"] = weekly
    if trailing is not None:
        position["trailing_4wk_sales_units"] = trailing
    if on_order is not None:
        position["on_order_units"] = on_order
    db.touch(position)
    return env.ok(dv.position_out(position))


# =================================== Receipt =================================
@bp.post("/allocation/receipts")
@require("PlanningAdmin", "Allocator")
def create_receipt():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    item_id = va.get_str(data, "item_id")
    reference = va.get_str(data, "reference")
    units_received = va.get_int(data, "units_received", minimum=1)
    size_received = va.get_size_array(data, "size_received")
    receipt_date = va.get_dt(data, "receipt_date")
    program = gd.get_program(program_id)
    item = gd.get_item(item_id)
    if item["program_id"] != program["id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE")
    gd.decision_gate(program)
    check_size_array(item, size_received, units_received, "units_received")
    record = db.base_record()
    record.update(
        {
            "program_id": program["id"],
            "item_id": item["id"],
            "reference": reference,
            "units_received": units_received,
            "size_received": size_received,
            "receipt_date": receipt_date,
            "status": "STAGED",
        }
    )
    db.receipts[record["id"]] = record
    return env.created(dv.receipt_out(record))


@bp.get("/allocation/receipts/<receipt_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_receipt(receipt_id):
    return env.ok(dv.receipt_out(gd.get_receipt(receipt_id)))


@bp.get("/allocation/receipts")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_receipts():
    program_id = va.q_str("program_id")
    item_id = va.q_str("item_id")
    status = va.q_enum("status", RECEIPT_STATES)
    records = dv.by_created(list(db.receipts.values()))
    if program_id:
        records = [r for r in records if r["program_id"] == program_id]
    if item_id:
        records = [r for r in records if r["item_id"] == item_id]
    if status:
        records = [r for r in records if r["status"] == status]
    chunk, meta = va.page(records)
    return env.ok_array([dv.receipt_out(r) for r in chunk], meta)


@bp.post("/allocation/receipts/<receipt_id>/close")
@require("AllocationManager")
def close_receipt(receipt_id):
    receipt = gd.get_receipt(receipt_id)
    if receipt["status"] not in ("ALLOCATING", "ALLOCATED"):
        gd.bad_state()
    receipt["status"] = "CLOSED"
    db.touch(receipt)
    for run in dv.runs_of_receipt(receipt["id"]):
        if run["status"] in ("DRAFT", "PROPOSED"):
            run["status"] = "CANCELLED"
            db.touch(run)
            for line in dv.lines_of_run(run["id"]):
                line["fulfillment_status"] = "RECALLED"
                line["units_allocated"] = 0
                db.touch(line)
    return env.ok(dv.receipt_out(receipt))


@bp.post("/allocation/receipts/<receipt_id>/adjust")
@require("PlanningAdmin", "Allocator")
def adjust_receipt(receipt_id):
    data = va.body()
    units_received = va.get_int(data, "units_received", minimum=1)
    size_received = va.get_size_array(data, "size_received")
    reason = va.get_str(data, "adjustment_reason")
    receipt = gd.get_receipt(receipt_id)
    if receipt["status"] not in ("STAGED", "ALLOCATING"):
        gd.bad_state()
    program = gd.program_of_receipt(receipt)
    gd.decision_gate(program)
    item = db.items[receipt["item_id"]]
    check_size_array(item, size_received, units_received, "units_received")
    if units_received < dv.receipt_units_committed(receipt):
        raise ApiError("ERR_RECEIPT_UNITS_EXCEEDED")
    receipt["units_received"] = units_received
    receipt["size_received"] = size_received
    receipt["adjustment_reason"] = reason
    db.touch(receipt)
    return env.ok(dv.receipt_out(receipt))
