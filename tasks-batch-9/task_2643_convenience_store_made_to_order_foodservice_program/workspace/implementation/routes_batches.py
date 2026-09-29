"""Par-baked production: slot planning, baking, holding, top-off and write-offs."""

from flask import Blueprint

from apihttp import authenticate, created, get_body, ok, paginate, query_str
from calc import (
    append_waste_log,
    find_holding_unit,
    find_menu_item,
    find_production_batch,
    find_store,
    occupancy_end_for,
    slot_conflict_exists,
)
from core import base_record, db, plus_minutes, sort_created, touch
from errors import ApiError
from serialize import production_batch_out, waste_log_out

bp = Blueprint("batches", __name__)

DISCARD_REASONS = ("HOLD_EXPIRED", "QUALITY_REJECT", "UNIT_IMPAIRED", "DAYPART_TRANSITION")
OPERATOR_DISCARD_REASONS = ("HOLD_EXPIRED", "QUALITY_REJECT")


@bp.post("/production-batches")
def plan_production_batch():
    authenticate(("StoreManager", "KitchenAssociate"))
    body = get_body()
    store_id = body.string("store_id")
    menu_item_id = body.string("menu_item_id")
    holding_unit_id = body.string("holding_unit_id")
    slot_index = body.integer("slot_index", minimum=1)
    planned_qty = body.integer("planned_qty", minimum=1)
    bake_start_at = body.datetime("bake_start_at")
    store = find_store(store_id)
    item = find_menu_item(menu_item_id)
    unit = find_holding_unit(holding_unit_id)
    if unit["status"] != "OPERATIONAL":
        raise ApiError("ERR_HOLDING_UNIT_NOT_OPERATIONAL")
    if item["fulfillment_mode"] != "PAR_BAKED_CASE":
        raise ApiError("ERR_ITEM_NOT_PAR_BAKED")
    if slot_index > unit["slot_count"]:
        raise ApiError("ERR_SLOT_INDEX_OUT_OF_RANGE")
    occupancy_end_at = occupancy_end_for(bake_start_at, item)
    if slot_conflict_exists(unit["id"], slot_index, bake_start_at, occupancy_end_at):
        raise ApiError("ERR_UNIT_SLOT_CONFLICT")
    rec = base_record()
    rec.update({
        "store_id": store["id"],
        "menu_item_id": item["id"],
        "holding_unit_id": unit["id"],
        "slot_index": slot_index,
        "planned_qty": planned_qty,
        "bake_start_at": bake_start_at,
        "occupancy_end_at": occupancy_end_at,
        "baked_qty": 0,
        "remaining_qty": 0,
        "reserved_qty": 0,
        "sold_qty": 0,
        "discarded_qty": 0,
        "hold_started_at": None,
        "hold_expires_at": None,
        "status": "PLANNED",
    })
    db.production_batches[rec["id"]] = rec
    return created(production_batch_out(rec))


@bp.get("/production-batches/<batch_id>")
def read_production_batch(batch_id):
    authenticate(("ChainAdmin", "StoreManager", "KitchenAssociate", "ShiftLead", "FoodSafetyLead"))
    return ok(production_batch_out(find_production_batch(batch_id)))


@bp.get("/production-batches")
def list_production_batches():
    authenticate(("ChainAdmin", "StoreManager", "KitchenAssociate", "ShiftLead"))
    batches = list(db.production_batches.values())
    for field in ("store_id", "menu_item_id", "holding_unit_id", "status"):
        value = query_str(field)
        if value is not None:
            batches = [b for b in batches if b[field] == value]
    return paginate(sort_created(batches), production_batch_out)


@bp.post("/production-batches/<batch_id>/bake")
def bake_production_batch(batch_id):
    authenticate(("KitchenAssociate",))
    body = get_body()
    batch = find_production_batch(batch_id)
    if batch["status"] not in ("PLANNED", "HOLDING"):
        raise ApiError("ERR_BATCH_STATE_INVALID")
    unit = db.holding_units[batch["holding_unit_id"]]
    store = db.stores[batch["store_id"]]
    if batch["status"] == "HOLDING":
        additional_qty = body.integer("additional_qty", minimum=1)
        if unit["status"] != "OPERATIONAL":
            raise ApiError("ERR_HOLDING_UNIT_NOT_OPERATIONAL")
        batch["baked_qty"] += additional_qty
        batch["remaining_qty"] += additional_qty
        batch["hold_started_at"] = None
        batch["hold_expires_at"] = None
        batch["status"] = "BAKING"
        touch(batch)
        return ok(production_batch_out(batch))
    if unit["status"] != "OPERATIONAL":
        raise ApiError("ERR_HOLDING_UNIT_NOT_OPERATIONAL")
    if store["hot_case_slots_used"] >= store["hot_case_slot_capacity"]:
        raise ApiError("ERR_HOT_CASE_CAPACITY_EXCEEDED")
    batch["baked_qty"] = batch["planned_qty"]
    batch["remaining_qty"] = batch["planned_qty"]
    batch["status"] = "BAKING"
    touch(batch)
    store["hot_case_slots_used"] += 1
    touch(store)
    return ok(production_batch_out(batch))


@bp.post("/production-batches/<batch_id>/pull")
def pull_production_batch(batch_id):
    authenticate(("KitchenAssociate",))
    batch = find_production_batch(batch_id)
    if batch["status"] != "BAKING":
        raise ApiError("ERR_BATCH_STATE_INVALID")
    unit = db.holding_units[batch["holding_unit_id"]]
    if unit["status"] != "OPERATIONAL":
        raise ApiError("ERR_HOLDING_UNIT_NOT_OPERATIONAL")
    item = db.menu_items[batch["menu_item_id"]]
    batch["status"] = "HOLDING"
    batch["hold_started_at"] = db.clock
    batch["hold_expires_at"] = plus_minutes(db.clock, item["hold_minutes"])
    touch(batch)
    return ok(production_batch_out(batch))


@bp.post("/production-batches/<batch_id>/discard")
def discard_production_batch(batch_id):
    user_id, _role = authenticate(("KitchenAssociate", "ShiftLead"))
    body = get_body()
    qty = body.integer("qty", minimum=1)
    reason = body.enum("reason", DISCARD_REASONS)
    expected_batch_version = body.integer("expected_batch_version")
    batch = find_production_batch(batch_id)
    if expected_batch_version != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION")
    if batch["status"] != "HOLDING":
        raise ApiError("ERR_BATCH_STATE_INVALID")
    hold_expired = (
        batch["hold_expires_at"] is not None and batch["hold_expires_at"] <= db.clock
    )
    if hold_expired and reason != "HOLD_EXPIRED":
        raise ApiError("ERR_BATCH_HOLD_EXPIRED")
    if reason not in OPERATOR_DISCARD_REASONS:
        raise ApiError("ERR_RESERVED_DISCARD_REASON")
    if qty > batch["remaining_qty"]:
        raise ApiError("ERR_DISCARD_QTY_EXCEEDS_REMAINING")
    store = db.stores[batch["store_id"]]
    item = db.menu_items[batch["menu_item_id"]]
    batch["remaining_qty"] -= qty
    batch["discarded_qty"] += qty
    log = append_waste_log(batch, item, qty, reason, user_id, store)
    store["waste_cost_cents_mtd"] += log["food_cost_cents"]
    if batch["remaining_qty"] == 0 and batch["reserved_qty"] == 0:
        batch["status"] = "DISCARDED"
        store["hot_case_slots_used"] -= 1
    touch(batch)
    touch(store)
    return ok(production_batch_out(batch))


@bp.get("/production-batches/<batch_id>/waste-logs")
def list_batch_waste_logs(batch_id):
    authenticate(("ChainAdmin", "StoreManager", "ShiftLead", "FoodSafetyLead"))
    batch = find_production_batch(batch_id)
    logs = [w for w in db.waste_logs.values() if w["production_batch_id"] == batch["id"]]
    reason = query_str("reason")
    if reason is not None:
        logs = [w for w in logs if w["reason"] == reason]
    return paginate(sort_created(logs), waste_log_out)
