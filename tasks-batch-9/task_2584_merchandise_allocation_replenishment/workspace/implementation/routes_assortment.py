"""Assortment detection, remedies, cluster snapshots and the logical clock."""
from flask import Blueprint, g

import calc
import derive as dv
import envelope as env
import guards as gd
import routes_transfers as tr
import store as db
import validation as va
from auth import require, require_lenient
from errors import ApiError

bp = Blueprint("assortment", __name__)

ACTION_TYPES = ("CONSOLIDATION", "MARKDOWN")
ACTION_STATES = ("PENDING", "EXECUTED", "CANCELLED", "SUPERSEDED")
BASES = ("SIMPLE_AVERAGE", "UNIT_WEIGHTED")
DEGRADED = ("SIZE_OUT_RISK", "BROKEN")
TRIGGER_FOR_STATUS = {"SIZE_OUT_RISK": "SIZE_OUT", "BROKEN": "BROKEN_ASSORTMENT"}


def _has_pending_action(item_id, store_id):
    return any(
        a["status"] == "PENDING" and a["item_id"] == item_id and a["store_id"] == store_id
        for a in db.actions.values()
    )


def _sweep_key(pair):
    store, item = pair[1], pair[2]
    return (store["store_code"], item["sku_code"])


# ============================ detection sweep ================================
@bp.post("/allocation/_run-assortment-detection")
@require("Allocator", "AllocationManager")
def run_assortment_detection():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    program = gd.get_program(program_id)
    gd.decision_gate(program)
    candidates = []
    for position in db.positions.values():
        item = db.items.get(position["item_id"])
        store = db.stores.get(position["store_id"])
        if item is None or store is None:
            continue
        if item["program_id"] != program["id"]:
            continue
        status = dv.assortment_status(position)
        if status not in DEGRADED:
            continue
        if store["status"] not in ("ACTIVE", "REMODEL"):
            continue
        if item["lifecycle_state"] == "MARKDOWN":
            continue
        if _has_pending_action(item["id"], store["id"]):
            continue
        candidates.append((position, store, item, status))
    candidates.sort(key=_sweep_key)
    for position, store, item, status in candidates:
        gd.plan_in_effect_or_reject(store["id"], item["item_class"])
    raised = []
    for position, store, item, status in candidates:
        target = calc.remedy_selection(position)
        broken_count = dv.broken_size_count(position)
        record = db.base_record()
        record.update(
            {
                "item_id": item["id"],
                "store_id": store["id"],
                "trigger_reason": TRIGGER_FOR_STATUS[status],
                "action_type": "CONSOLIDATION" if target else "MARKDOWN",
                "consolidation_target_store_id": target["store_id"] if target else None,
                "broken_size_count": broken_count,
                "markdown_pct_bp": None
                if target
                else calc.markdown_depth_bp(broken_count, len(dv.core_sizes(item))),
                "units_at_detection": dv.available_units(position),
                "status": "PENDING",
                "detected_at": db.now(),
            }
        )
        db.actions[record["id"]] = record
        raised.append(record)
    return env.ok_array([dv.action_out(a) for a in raised])


# ============================= AssortmentAction ==============================
@bp.get("/allocation/assortment-actions/<action_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_action(action_id):
    return env.ok(dv.action_out(gd.get_action(action_id)))


@bp.get("/allocation/assortment-actions")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_actions():
    filters = {
        "item_id": va.q_str("item_id"),
        "store_id": va.q_str("store_id"),
        "consolidation_target_store_id": va.q_str("consolidation_target_store_id"),
        "action_type": va.q_enum("action_type", ACTION_TYPES),
        "status": va.q_enum("status", ACTION_STATES),
    }
    records = dv.by_created(list(db.actions.values()))
    for field, value in filters.items():
        if value:
            records = [r for r in records if r.get(field) == value]
    chunk, meta = va.page(records)
    return env.ok_array([dv.action_out(r) for r in chunk], meta)


@bp.post("/allocation/assortment-actions/<action_id>/execute")
@require("AllocationManager")
def execute_action(action_id):
    action = gd.get_action(action_id)
    if action["status"] != "PENDING":
        gd.bad_state()
    item = gd.get_item(action["item_id"])
    program = gd.get_program(item["program_id"])
    gd.decision_gate(program)
    if item["lifecycle_state"] not in ("SIZE_OUT_WATCH", "BROKEN"):
        raise ApiError("ERR_ITEM_LIFECYCLE_BLOCKED")
    if action["action_type"] == "CONSOLIDATION":
        target_store = gd.get_store(action["consolidation_target_store_id"])
        donor = tr.donor_position_or_reject(action["store_id"], item["id"])
        receiver = tr.donor_position_or_reject(target_store["id"], item["id"])
        units = action["units_at_detection"]
        plan = dv.in_effect_plan(target_store["id"], item["item_class"])
        if units < 1 or dv.headroom(receiver, plan) < units:
            raise ApiError("ERR_FIXTURE_CAPACITY_EXCEEDED")
        from_store = gd.get_store(action["store_id"])
        tr.build_transfer(
            program,
            from_store,
            target_store,
            item,
            units,
            "CONSOLIDATION",
            "system",
            donor,
            receiver,
            assortment_action_id=action["id"],
        )
        item["lifecycle_state"] = "CONSOLIDATION_PENDING"
    else:
        item["lifecycle_state"] = "MARKDOWN"
    db.touch(item)
    action["status"] = "EXECUTED"
    db.touch(action)
    return env.ok(dv.action_out(action))


@bp.post("/allocation/assortment-actions/<action_id>/cancel")
@require("AllocationManager")
def cancel_action(action_id):
    action = gd.get_action(action_id)
    if action["status"] != "PENDING":
        gd.bad_state()
    action["status"] = "CANCELLED"
    db.touch(action)
    return env.ok(dv.action_out(action))


# ============================ PerformanceSnapshot =============================
@bp.post("/allocation/performance-snapshots")
@require("Allocator", "AllocationManager")
def create_snapshot():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    cluster_code = va.get_str(data, "cluster_code")
    basis = va.get_enum(data, "basis", BASES, required=False)
    program = gd.get_program(program_id)
    gd.decision_gate(program)
    if basis is None:
        basis = program["scorecard_basis"]
    included = []
    for position in dv.by_created(list(db.positions.values())):
        store = db.stores.get(position["store_id"])
        item = db.items.get(position["item_id"])
        if store is None or item is None:
            continue
        if store["program_id"] != program["id"]:
            continue
        if store["cluster_code"] != cluster_code:
            continue
        if store["status"] not in ("ACTIVE", "REMODEL"):
            continue
        if item["lifecycle_state"] == "MARKDOWN":
            continue
        included.append(position)
    if not included:
        raise ApiError("ERR_NO_CLUSTER_POSITIONS")
    in_stock_bp, sell_bp, accuracy_bp = calc.cluster_scorecard(included, basis)
    record = db.base_record(versioned=False)
    record.update(
        {
            "program_id": program["id"],
            "cluster_code": cluster_code,
            "basis": basis,
            "as_of_date": db.now(),
            "store_count": len({p["store_id"] for p in included}),
            "included_position_count": len(included),
            "in_stock_pct_bp": in_stock_bp,
            "sell_through_pct_bp": sell_bp,
            "allocation_accuracy_bp": accuracy_bp,
        }
    )
    db.snapshots[record["id"]] = record
    return env.created(dv.snapshot_out(record))


@bp.get("/allocation/performance-snapshots/<snapshot_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_snapshot(snapshot_id):
    return env.ok(dv.snapshot_out(gd.get_snapshot(snapshot_id)))


@bp.get("/allocation/performance-snapshots")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_snapshots():
    program_id = va.q_str("program_id")
    cluster_code = va.q_str("cluster_code")
    records = dv.by_created(list(db.snapshots.values()))
    if program_id:
        records = [r for r in records if r["program_id"] == program_id]
    if cluster_code:
        records = [r for r in records if r["cluster_code"] == cluster_code]
    chunk, meta = va.page(records)
    return env.ok_array([dv.snapshot_out(r) for r in chunk], meta)


# ================================ logical clock ==============================
@bp.post("/_clock/set_current_utc")
@require_lenient("PlanningAdmin")
def set_current_utc():
    data = va.body()
    current = va.get_dt(data, "current_utc")
    db.set_clock(current)
    return env.ok(None)
