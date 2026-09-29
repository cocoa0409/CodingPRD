"""Wafer start plans and lots."""
from flask import Blueprint

import calc
import clock
from auth import require
from db import db, need, new_row, ordered, touch
from errors import fail
from response import ok, ok_raw
from routes.common import matches, paged
from util import r2, r3
from validate import (PRIORITY_CLASSES, PRODUCT_FAMILIES, body, q_enum, q_str,
                      v_datetime, v_enum, v_int, v_num, v_str)

bp = Blueprint("planning", __name__)

PLAN_STATUSES = ("DRAFT", "COMMITTED", "CLOSED")
FLOW_STATES = ("PLANNED", "RELEASED", "IN_PROCESS", "AT_SORT", "COMPLETED", "SCRAPPED")
HOLD_STATES = ("NONE", "SPC_HOLD", "QUAL_HOLD", "ENGINEERING_HOLD")

PLAN_READERS = ("FabPlanner", "ProcessEngineer", "QualityManager", "YieldEngineer",
                "EquipmentEngineer")
LOT_READERS = ("FabPlanner", "ProcessEngineer", "QualityManager", "YieldEngineer",
               "EquipmentEngineer", "Operator")


# ------------------------------------------------------------ wafer start plans

@bp.post("/fab/wafer-start-plans")
@require("FabPlanner")
def create_plan():
    data = body()
    flow_id = v_str(data, "flow_id")
    product_family = v_enum(data, "product_family", PRODUCT_FAMILIES)
    week_start_date = v_datetime(data, "week_start_date")
    planned_wafer_starts = v_int(data, "planned_wafer_starts", minimum=1)
    capacity_budget_hours = v_num(data, "capacity_budget_hours", gt=0)
    cycle_time_target_days = v_num(data, "cycle_time_target_days", gt=0)

    flow = need(db.process_flows, flow_id, "ERR_PROCESS_FLOW_NOT_FOUND")
    if flow["status"] != "RELEASED":
        fail("ERR_FLOW_NOT_RELEASED", "Flow is %s, not RELEASED" % flow["status"])
    if flow["product_family"] != product_family:
        fail("ERR_PRODUCT_FAMILY_MISMATCH",
             "Flow product family is %s" % flow["product_family"])

    row = new_row({
        "flow_id": flow_id,
        "product_family": product_family,
        "week_start_date": week_start_date,
        "planned_wafer_starts": planned_wafer_starts,
        "capacity_budget_hours": r2(capacity_budget_hours),
        "cycle_time_target_days": r3(cycle_time_target_days),
        "released_wafer_starts": 0,
        "committed_hours": 0.0,
        "surcharge_hours": 0.0,
        "commitment_tier": "TIER_0",
        "status": "DRAFT",
    })
    db.plans[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/wafer-start-plans")
@require(*PLAN_READERS)
def list_plans():
    filters = {
        "flow_id": q_str("flow_id"),
        "status": q_enum("status", PLAN_STATUSES),
    }
    return paged([p for p in db.plans.values() if matches(p, filters)])


@bp.get("/fab/wafer-start-plans/<plan_id>")
@require(*PLAN_READERS)
def read_plan(plan_id):
    return ok(need(db.plans, plan_id, "ERR_PLAN_NOT_FOUND"))


@bp.post("/fab/wafer-start-plans/<plan_id>/commit")
@require("FabPlanner")
def commit_plan(plan_id):
    body()
    plan = need(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    flow = db.process_flows[plan["flow_id"]]

    if flow["status"] != "RELEASED":
        fail("ERR_FLOW_NOT_RELEASED", "Flow is %s, not RELEASED" % flow["status"])
    if plan["status"] != "DRAFT":
        fail("ERR_PLAN_ALREADY_COMMITTED", "Plan is %s, not DRAFT" % plan["status"])
    if plan["product_family"] != flow["product_family"]:
        fail("ERR_PRODUCT_FAMILY_MISMATCH",
             "Flow product family is %s" % flow["product_family"])

    base, utilization, tier, surcharge, committed = calc.capacity_commitment(
        plan["planned_wafer_starts"], flow["total_standard_hours"],
        plan["capacity_budget_hours"])
    if committed > plan["capacity_budget_hours"]:
        fail("ERR_CAPACITY_BUDGET_EXCEEDED",
             "committed_hours %.2f exceeds capacity_budget_hours %.2f"
             % (committed, plan["capacity_budget_hours"]))

    plan["commitment_tier"] = tier
    plan["surcharge_hours"] = surcharge
    plan["committed_hours"] = committed
    plan["status"] = "COMMITTED"
    touch(plan)
    return ok(plan)


# ---------------------------------------------------------------------- lots

@bp.post("/fab/lots")
@require("FabPlanner")
def create_lot():
    data = body()
    plan_id = v_str(data, "plan_id")
    flow_id = v_str(data, "flow_id")
    lot_number = v_str(data, "lot_number", min_len=1, max_len=32)
    wafer_count = v_int(data, "wafer_count", minimum=1)
    priority_class = v_enum(data, "priority_class", PRIORITY_CLASSES, required=False,
                            default="STANDARD")

    need(db.process_flows, flow_id, "ERR_PROCESS_FLOW_NOT_FOUND")
    plan = need(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["flow_id"] != flow_id:
        fail("ERR_PRODUCT_FAMILY_MISMATCH", "Lot flow_id does not match the plan's flow_id")
    if any(l["lot_number"] == lot_number for l in db.lots.values()):
        fail("ERR_DUPLICATE_CODE", "lot_number '%s' already exists" % lot_number)

    row = new_row({
        "plan_id": plan_id,
        "flow_id": flow_id,
        "parent_lot_id": None,
        "hold_excursion_id": None,
        "lot_number": lot_number,
        "wafer_count": wafer_count,
        "origin_wafer_count": wafer_count,
        "priority_class": priority_class,
        "lot_type": "PRODUCTION",
        "flow_state": "PLANNED",
        "hold_state": "NONE",
        "current_step_seq": 0,
        "rework_count": 0,
        "released_at": None,
        "completed_at": None,
        "actual_cycle_time_days": None,
    })
    db.lots[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/lots")
@require(*LOT_READERS)
def list_lots():
    filters = {
        "plan_id": q_str("plan_id"),
        "flow_id": q_str("flow_id"),
        "parent_lot_id": q_str("parent_lot_id"),
        "hold_excursion_id": q_str("hold_excursion_id"),
        "hold_state": q_enum("hold_state", HOLD_STATES),
        "flow_state": q_enum("flow_state", FLOW_STATES),
        "priority_class": q_enum("priority_class", PRIORITY_CLASSES),
    }
    return paged([l for l in db.lots.values() if matches(l, filters)])


@bp.get("/fab/lots/<lot_id>")
@require(*LOT_READERS)
def read_lot(lot_id):
    return ok(need(db.lots, lot_id, "ERR_LOT_NOT_FOUND"))


@bp.post("/fab/lots/<lot_id>/release")
@require("FabPlanner")
def release_lot(lot_id):
    data = body()
    expected_plan_version = v_int(data, "expected_plan_version", minimum=0)
    lot = need(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    plan = db.plans[lot["plan_id"]]

    if expected_plan_version != plan["version"]:
        fail("ERR_STALE_PLAN_VERSION",
             "expected_plan_version %d does not match plan version %d"
             % (expected_plan_version, plan["version"]))
    if plan["status"] != "COMMITTED":
        fail("ERR_PLAN_NOT_COMMITTED", "Plan is %s, not COMMITTED" % plan["status"])
    if lot["flow_state"] != "PLANNED":
        fail("ERR_LOT_INVALID_STATE", "Lot is %s, not PLANNED" % lot["flow_state"])
    if plan["released_wafer_starts"] + lot["wafer_count"] > plan["planned_wafer_starts"]:
        fail("ERR_PLAN_STARTS_EXCEEDED",
             "Releasing %d wafers would exceed the plan's %d authorised starts"
             % (lot["wafer_count"], plan["planned_wafer_starts"]))

    lot["flow_state"] = "RELEASED"
    lot["released_at"] = clock.now()
    touch(lot)

    plan["released_wafer_starts"] = plan["released_wafer_starts"] + lot["wafer_count"]
    touch(plan)
    if plan["released_wafer_starts"] == plan["planned_wafer_starts"]:
        plan["status"] = "CLOSED"
        touch(plan)
    return ok(lot)


@bp.post("/fab/lots/<lot_id>/splits")
@require("ProcessEngineer")
def split_lot(lot_id):
    data = body()
    split_wafer_count = v_int(data, "split_wafer_count", minimum=1)
    lot_number = v_str(data, "lot_number", min_len=1, max_len=32)
    expected_lot_version = v_int(data, "expected_lot_version", minimum=0)
    priority_class = v_enum(data, "priority_class", PRIORITY_CLASSES, required=False,
                            default="STANDARD")
    parent = need(db.lots, lot_id, "ERR_LOT_NOT_FOUND")

    if expected_lot_version != parent["version"]:
        fail("ERR_STALE_LOT_VERSION",
             "expected_lot_version %d does not match lot version %d"
             % (expected_lot_version, parent["version"]))
    if parent["flow_state"] not in ("RELEASED", "IN_PROCESS"):
        fail("ERR_LOT_INVALID_STATE",
             "Lot is %s; splits require RELEASED or IN_PROCESS" % parent["flow_state"])
    if any(l["lot_number"] == lot_number for l in db.lots.values()):
        fail("ERR_DUPLICATE_CODE", "lot_number '%s' already exists" % lot_number)
    if not 1 <= split_wafer_count < parent["wafer_count"]:
        fail("ERR_INVALID_SPLIT_QUANTITY",
             "split_wafer_count must be >= 1 and < the parent's wafer_count %d"
             % parent["wafer_count"])

    child = new_row({
        "plan_id": parent["plan_id"],
        "flow_id": parent["flow_id"],
        "parent_lot_id": parent["id"],
        "hold_excursion_id": None,
        "lot_number": lot_number,
        "wafer_count": split_wafer_count,
        "origin_wafer_count": split_wafer_count,
        "priority_class": priority_class,
        "lot_type": "ENGINEERING_SPLIT",
        "flow_state": "RELEASED",
        "hold_state": "ENGINEERING_HOLD",
        "current_step_seq": parent["current_step_seq"],
        "rework_count": 0,
        "released_at": None,
        "completed_at": None,
        "actual_cycle_time_days": None,
    })
    db.lots[child["id"]] = child

    parent["wafer_count"] = parent["wafer_count"] - split_wafer_count
    touch(parent)
    return ok(child, 201)


@bp.post("/fab/lots/<lot_id>/rejoin")
@require("ProcessEngineer")
def rejoin_lot(lot_id):
    body()
    lot = need(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if (lot["lot_type"] != "ENGINEERING_SPLIT" or not lot["parent_lot_id"]
            or lot["hold_state"] != "ENGINEERING_HOLD"):
        fail("ERR_NOT_A_SPLIT_LOT", "Lot is not an engineering split lot on ENGINEERING_HOLD")
    parent = db.lots.get(lot["parent_lot_id"])
    if parent is None:
        fail("ERR_NOT_A_SPLIT_LOT", "Parent lot no longer exists")

    parent["wafer_count"] = parent["wafer_count"] + lot["wafer_count"]
    touch(parent)

    lot["wafer_count"] = 0
    lot["hold_state"] = "NONE"
    lot["hold_excursion_id"] = None
    lot["flow_state"] = "COMPLETED"
    touch(lot)
    return ok(lot)


@bp.post("/fab/lots/<lot_id>/rework")
@require("ProcessEngineer")
def rework_lot(lot_id):
    body()
    lot = need(db.lots, lot_id, "ERR_LOT_NOT_FOUND")

    if lot["flow_state"] not in ("RELEASED", "IN_PROCESS"):
        fail("ERR_LOT_INVALID_STATE",
             "Lot is %s; rework requires RELEASED or IN_PROCESS" % lot["flow_state"])
    if lot["hold_state"] != "SPC_HOLD":
        fail("ERR_LOT_INVALID_STATE", "Lot hold_state is %s, not SPC_HOLD" % lot["hold_state"])
    excursion = db.excursions.get(lot["hold_excursion_id"]) if lot["hold_excursion_id"] else None
    if excursion is None or excursion["disposition"] != "REWORK":
        fail("ERR_LOT_INVALID_STATE",
             "The excursion holding this lot has not been dispositioned REWORK")

    current = None
    for step in ordered(db.process_steps.values()):
        if step["flow_id"] == lot["flow_id"] and step["step_seq"] == lot["current_step_seq"]:
            current = step
            break
    target = None
    if current is not None and current["rework_target_step_id"]:
        target = db.process_steps.get(current["rework_target_step_id"])
    if target is None:
        fail("ERR_REWORK_TARGET_NOT_SET",
             "The step at the lot's current sequence declares no rework target")
    if lot["rework_count"] >= calc.MAX_REWORK_COUNT:
        fail("ERR_REWORK_LIMIT_EXCEEDED",
             "Lot has already been reworked %d time(s)" % lot["rework_count"])

    lot["current_step_seq"] = target["step_seq"] - 1
    lot["rework_count"] = lot["rework_count"] + 1
    lot["hold_state"] = "NONE"
    lot["hold_excursion_id"] = None
    touch(lot)
    return ok(lot)


@bp.get("/fab/lots/<lot_id>/cycle-time-projection")
@require("FabPlanner", "ProcessEngineer", "QualityManager", "YieldEngineer")
def cycle_time_projection(lot_id):
    lot = need(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["released_at"] is None:
        fail("ERR_LOT_INVALID_STATE", "Lot has not been released into the fab")
    plan = db.plans[lot["plan_id"]]
    return ok_raw(calc.cycle_time_projection(lot, clock.now(), plan["cycle_time_target_days"]))
