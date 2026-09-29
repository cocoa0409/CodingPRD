"""Programs, stores, shelf plans, size curves and SKUs (PRD 3.1-3.2)."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import derive as dv
import envelope as env
import guards as gd
import store as db
import validation as va
from auth import require, scope_check
from errors import ApiError

bp = Blueprint("catalog", __name__)

GRADES = ("A", "B", "C", "D")
STORE_STATES = ("ACTIVE", "REMODEL", "CLOSING", "CLOSED")
ITEM_TYPES = ("BASIC", "SEASONAL", "FASHION")
MODELS = ("MIN_MAX", "DEMAND_DRIVEN", "PUSH")
LIFECYCLES = ("ACTIVE", "SIZE_OUT_WATCH", "BROKEN", "CONSOLIDATION_PENDING", "MARKDOWN")


# =============================== AllocationProgram ===========================
@bp.post("/allocation/programs")
@require("PlanningAdmin")
def create_program():
    data = va.body()
    name = va.get_str(data, "name")
    season_code = va.get_str(data, "season_code")
    banner_code = va.get_str(data, "banner_code")
    ratio_bp = va.get_int(data, "transfer_min_ratio_bp", required=False, default=15000, minimum=0)
    basis = va.get_enum(
        data, "scorecard_basis", ("SIMPLE_AVERAGE", "UNIT_WEIGHTED"), required=False,
        default="UNIT_WEIGHTED",
    )
    record = db.base_record()
    record.update(
        {
            "name": name,
            "season_code": season_code,
            "banner_code": banner_code,
            "status": "PLANNING",
            "transfer_min_ratio_bp": ratio_bp,
            "scorecard_basis": basis,
            "locked_at": None,
            "lock_reason": None,
        }
    )
    db.programs[record["id"]] = record
    return env.created(dv.program_out(record))


@bp.get("/allocation/programs/<program_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_program(program_id):
    return env.ok(dv.program_out(gd.get_program(program_id)))


@bp.post("/allocation/programs/<program_id>/activate")
@require("PlanningAdmin")
def activate_program(program_id):
    program = gd.get_program(program_id)
    if program["status"] != "PLANNING":
        gd.bad_state()
    active_store = any(
        s["status"] == "ACTIVE" for s in dv.stores_of_program(program_id)
    )
    has_item = bool(dv.items_of_program(program_id))
    if not active_store or not has_item:
        gd.bad_state()
    program["status"] = "ACTIVE"
    db.touch(program)
    return env.ok(dv.program_out(program))


@bp.post("/allocation/programs/<program_id>/lock")
@require("AllocationManager")
def lock_program(program_id):
    data = va.body()
    reason = va.get_str(data, "reason")
    program = gd.get_program(program_id)
    if program["status"] != "ACTIVE":
        gd.bad_state()
    program["status"] = "LOCKED"
    program["locked_at"] = db.now()
    program["lock_reason"] = reason
    db.touch(program)
    return env.ok(dv.program_out(program))


@bp.post("/allocation/programs/<program_id>/unlock")
@require("AllocationManager")
def unlock_program(program_id):
    program = gd.get_program(program_id)
    if program["status"] != "LOCKED":
        gd.bad_state()
    program["status"] = "ACTIVE"
    program["locked_at"] = None
    program["lock_reason"] = None
    db.touch(program)
    return env.ok(dv.program_out(program))


@bp.post("/allocation/programs/<program_id>/close")
@require("PlanningAdmin")
def close_program(program_id):
    program = gd.get_program(program_id)
    if program["status"] not in ("ACTIVE", "LOCKED"):
        gd.bad_state()
    receipts = dv.receipts_of_program(program_id)
    receipt_ids = {r["id"] for r in receipts}
    for run in db.runs.values():
        if run["receipt_id"] in receipt_ids and run["status"] in ("DRAFT", "PROPOSED"):
            gd.bad_state()
    for transfer in db.transfers.values():
        if transfer["program_id"] == program_id and transfer["status"] in (
            "PROPOSED",
            "APPROVED",
            "DISPATCHED",
        ):
            gd.bad_state()
    program["status"] = "CLOSED"
    db.touch(program)
    for receipt in receipts:
        if receipt["status"] in ("STAGED", "ALLOCATING", "ALLOCATED"):
            receipt["status"] = "CLOSED"
            db.touch(receipt)
    for action in db.actions.values():
        if action["status"] != "PENDING":
            continue
        item = db.items.get(action["item_id"])
        if item and item["program_id"] == program_id:
            action["status"] = "CANCELLED"
            db.touch(action)
    return env.ok(dv.program_out(program))


# ==================================== Store ==================================
@bp.post("/allocation/stores")
@require("PlanningAdmin")
def create_store():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    store_code = va.get_str(data, "store_code")
    grade = va.get_enum(data, "grade", GRADES)
    grade_index_bp = va.get_int(data, "grade_index_bp", minimum=1)
    cluster_code = va.get_str(data, "cluster_code")
    freight = va.get_money(data, "freight_flat_usd", minimum=0)
    sell_through = va.get_int(data, "historical_sell_through_bp", minimum=0, maximum=10000)
    program = gd.get_program(program_id)
    for existing in dv.stores_of_program(program["id"]):
        if existing["store_code"] == store_code:
            raise ApiError("ERR_DUPLICATE_STORE_CODE")
    record = db.base_record()
    record.update(
        {
            "program_id": program["id"],
            "store_code": store_code,
            "grade": grade,
            "grade_index_bp": grade_index_bp,
            "cluster_code": cluster_code,
            "status": "ACTIVE",
            "freight_flat_usd": freight,
            "historical_sell_through_bp": sell_through,
        }
    )
    db.stores[record["id"]] = record
    return env.created(dv.store_out(record))


@bp.get("/allocation/stores/<store_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager", "StoreOperator")
def read_store(store_id):
    scope_check(store_id)
    return env.ok(dv.store_out(gd.get_store(store_id)))


@bp.get("/allocation/stores")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_stores():
    program_id = va.q_str("program_id")
    cluster_code = va.q_str("cluster_code")
    status = va.q_enum("status", STORE_STATES)
    grade = va.q_enum("grade", GRADES)
    records = dv.by_created(list(db.stores.values()))
    if program_id:
        records = [r for r in records if r["program_id"] == program_id]
    if cluster_code:
        records = [r for r in records if r["cluster_code"] == cluster_code]
    if status:
        records = [r for r in records if r["status"] == status]
    if grade:
        records = [r for r in records if r["grade"] == grade]
    chunk, meta = va.page(records)
    return env.ok_array([dv.store_out(r) for r in chunk], meta)


@bp.post("/allocation/stores/<store_id>/status")
@require("PlanningAdmin")
def set_store_status(store_id):
    data = va.body()
    target = va.get_enum(data, "target_status", STORE_STATES)
    store = gd.get_store(store_id)
    current = store["status"]
    declared = {
        ("ACTIVE", "REMODEL"),
        ("REMODEL", "ACTIVE"),
        ("ACTIVE", "CLOSING"),
        ("CLOSING", "CLOSED"),
    }
    if (current, target) not in declared:
        gd.bad_state()
    positions = dv.positions_of_store(store_id)
    if target == "CLOSED":
        if any(p["on_hand_units"] != 0 for p in positions):
            raise ApiError("ERR_STORE_HAS_INVENTORY")
    store["status"] = target
    db.touch(store)
    if target == "CLOSED":
        # assortment_status is derived; a CLOSED store makes every position EXITED
        for position in positions:
            dv.propagate_position(position)
    return env.ok(dv.store_out(store))


# ================================= FixturePlan ===============================
@bp.post("/allocation/fixture-plans")
@require("PlanningAdmin")
def create_fixture_plan():
    data = va.body()
    store_id = va.get_str(data, "store_id")
    item_class = va.get_enum(data, "item_class", gd.ITEM_CLASSES)
    effective_from = va.get_dt(data, "effective_from")
    effective_to = va.get_dt(data, "effective_to", required=False)
    fixture_count = va.get_int(data, "fixture_count", minimum=1)
    facings = va.get_int(data, "facings_per_fixture", minimum=1)
    per_facing = va.get_int(data, "units_per_facing", minimum=1)
    presentation_min = va.get_int(data, "presentation_min_units", minimum=0)
    capacity = fixture_count * facings * per_facing
    if presentation_min > capacity:
        va.bad("presentation_min_units may not exceed capacity_units.")
    store = gd.get_store(store_id)
    for plan in db.fixture_plans.values():
        if plan["store_id"] != store["id"] or plan["item_class"] != item_class:
            continue
        a_start, a_end = effective_from, effective_to
        b_start, b_end = plan["effective_from"], plan["effective_to"]
        starts_before_end = a_end is None or b_start < a_end
        ends_after_start = b_end is None or a_start < b_end
        if starts_before_end and ends_after_start:
            raise ApiError("ERR_FIXTURE_PLAN_OVERLAP")
    record = db.base_record()
    record.update(
        {
            "store_id": store["id"],
            "item_class": item_class,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "fixture_count": fixture_count,
            "facings_per_fixture": facings,
            "units_per_facing": per_facing,
            "capacity_units": capacity,
            "presentation_min_units": presentation_min,
        }
    )
    db.fixture_plans[record["id"]] = record
    return env.created(dv.plan_out(record))


@bp.get("/allocation/fixture-plans/<plan_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_fixture_plan(plan_id):
    return env.ok(dv.plan_out(gd.get_plan(plan_id)))


@bp.get("/allocation/fixture-plans")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_fixture_plans():
    store_id = va.q_str("store_id")
    item_class = va.q_enum("item_class", gd.ITEM_CLASSES)
    records = dv.by_created(list(db.fixture_plans.values()))
    if store_id:
        records = [r for r in records if r["store_id"] == store_id]
    if item_class:
        records = [r for r in records if r["item_class"] == item_class]
    chunk, meta = va.page(records)
    return env.ok_array([dv.plan_out(r) for r in chunk], meta)


# ================================= SizeProfile ===============================
@bp.post("/allocation/size-profiles")
@require("PlanningAdmin")
def create_size_profile():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    profile_code = va.get_str(data, "profile_code")
    item_class = va.get_enum(data, "item_class", gd.ITEM_CLASSES)
    curve = va.get_size_curve(data, "size_curve")
    core_min = va.get_int(data, "core_size_min_share_bp", required=False, default=1500, minimum=0)
    program = gd.get_program(program_id)
    for existing in db.size_profiles.values():
        if existing["program_id"] == program["id"] and existing["profile_code"] == profile_code:
            raise ApiError("ERR_DUPLICATE_PROFILE_CODE")
    codes = [entry["size_code"] for entry in curve]
    if len(set(codes)) != len(codes) or sum(e["share_bp"] for e in curve) != 10000:
        raise ApiError("ERR_SIZE_CURVE_INVALID")
    record = db.base_record(versioned=False)
    record.update(
        {
            "program_id": program["id"],
            "profile_code": profile_code,
            "item_class": item_class,
            "size_curve": curve,
            "core_size_min_share_bp": core_min,
        }
    )
    db.size_profiles[record["id"]] = record
    return env.created(dv.profile_out(record))


@bp.get("/allocation/size-profiles/<profile_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_size_profile(profile_id):
    return env.ok(dv.profile_out(gd.get_profile(profile_id)))


@bp.get("/allocation/size-profiles")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_size_profiles():
    program_id = va.q_str("program_id")
    item_class = va.q_enum("item_class", gd.ITEM_CLASSES)
    records = dv.by_created(list(db.size_profiles.values()))
    if program_id:
        records = [r for r in records if r["program_id"] == program_id]
    if item_class:
        records = [r for r in records if r["item_class"] == item_class]
    chunk, meta = va.page(records)
    return env.ok_array([dv.profile_out(r) for r in chunk], meta)


# ==================================== Item ===================================
@bp.post("/allocation/items")
@require("PlanningAdmin")
def create_item():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    sku_code = va.get_str(data, "sku_code")
    style_code = va.get_str(data, "style_code")
    item_class = va.get_enum(data, "item_class", gd.ITEM_CLASSES)
    item_type = va.get_enum(data, "item_type", ITEM_TYPES)
    profile_id = va.get_str(data, "size_profile_id")
    unit_cost = va.get_money(data, "unit_cost_usd", minimum=0)
    retail = va.get_money(data, "retail_price_usd", minimum=0)
    override = va.get_enum(data, "replenishment_model_override", MODELS, required=False)
    program = gd.get_program(program_id)
    profile = gd.get_profile(profile_id)
    if profile["program_id"] != program["id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE")
    for existing in dv.items_of_program(program["id"]):
        if existing["sku_code"] == sku_code:
            raise ApiError("ERR_DUPLICATE_SKU_CODE")
    if item_class != profile["item_class"]:
        raise ApiError("ERR_ITEM_CLASS_MISMATCH")
    record = db.base_record()
    record.update(
        {
            "program_id": program["id"],
            "sku_code": sku_code,
            "style_code": style_code,
            "item_class": item_class,
            "item_type": item_type,
            "size_profile_id": profile["id"],
            "unit_cost_usd": unit_cost,
            "retail_price_usd": retail,
            "replenishment_model_override": override,
            "lifecycle_state": "ACTIVE",
        }
    )
    record["replenishment_model"] = calc.replenishment_model(record)
    db.items[record["id"]] = record
    return env.created(dv.item_out(record))


@bp.get("/allocation/items/<item_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_item(item_id):
    return env.ok(dv.item_out(gd.get_item(item_id)))


@bp.get("/allocation/items")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_items():
    program_id = va.q_str("program_id")
    profile_id = va.q_str("size_profile_id")
    item_type = va.q_enum("item_type", ITEM_TYPES)
    lifecycle = va.q_enum("lifecycle_state", LIFECYCLES)
    records = dv.by_created(list(db.items.values()))
    if program_id:
        records = [r for r in records if r["program_id"] == program_id]
    if profile_id:
        records = [r for r in records if r["size_profile_id"] == profile_id]
    if item_type:
        records = [r for r in records if r["item_type"] == item_type]
    if lifecycle:
        records = [r for r in records if r["lifecycle_state"] == lifecycle]
    chunk, meta = va.page(records)
    return env.ok_array([dv.item_out(r) for r in chunk], meta)


@bp.patch("/allocation/items/<item_id>")
@require("PlanningAdmin")
def patch_item(item_id):
    data = va.body()
    has_override = "replenishment_model_override" in data
    override = None
    if has_override and data["replenishment_model_override"] is not None:
        override = va.get_enum(data, "replenishment_model_override", MODELS)
    retail = va.get_money(data, "retail_price_usd", required=False, minimum=0)
    item = gd.get_item(item_id)
    if has_override:
        item["replenishment_model_override"] = override
    if retail is not None:
        item["retail_price_usd"] = retail
    item["replenishment_model"] = calc.replenishment_model(item)
    db.touch(item)
    return env.ok(dv.item_out(item))
