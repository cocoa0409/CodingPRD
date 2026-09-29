"""Allocation runs and allocation lines (PRD 3.6-3.7)."""
from flask import Blueprint, g

import calc
import derive as dv
import envelope as env
import guards as gd
import store as db
import validation as va
from auth import require, scope_check
from errors import ApiError

bp = Blueprint("runs", __name__)

METHODS = ("MIN_MAX_TOPUP", "DEMAND_DRIVEN", "PUSH_SIZE_PROFILE")
BASES = ("FORWARD_LOOKING", "HISTORICAL_SELL_THROUGH")
RUN_STATES = ("DRAFT", "PROPOSED", "COMMITTED", "RECALLED", "CANCELLED")
LINE_STATES = ("PENDING", "SHIPPED", "RECEIVED", "RECALLED")


def _new_run_record(receipt, method, need_basis, user_id):
    record = db.base_record()
    record.update(
        {
            "receipt_id": receipt["id"],
            "method": method,
            "need_basis": need_basis,
            "status": "DRAFT",
            "supersedes_run_id": None,
            "proposed_by_user_id": user_id,
            "committed_by_user_id": None,
            "unallocated_remainder_units": 0,
            "eligible_store_count": 0,
        }
    )
    return record


@bp.post("/allocation/receipts/<receipt_id>/allocation-runs")
@require("Allocator")
def create_run(receipt_id):
    data = va.body()
    method = va.get_enum(data, "method", METHODS)
    need_basis = va.get_enum(data, "need_basis", BASES)
    expected = va.get_int(data, "expected_receipt_version", minimum=0)
    receipt = gd.get_receipt(receipt_id)
    if receipt["status"] == "CLOSED":
        gd.bad_state()
    program = gd.program_of_receipt(receipt)
    gd.decision_gate(program)
    if expected != receipt["version"]:
        raise ApiError("ERR_STALE_RECEIPT_VERSION")
    item = db.items[receipt["item_id"]]
    item["replenishment_model"] = calc.replenishment_model(item)
    if calc.METHOD_FOR_MODEL[item["replenishment_model"]] != method:
        raise ApiError("ERR_METHOD_MODEL_MISMATCH")
    record = _new_run_record(receipt, method, need_basis, g.user_id)
    for sibling in dv.by_created(dv.runs_of_receipt(receipt["id"])):
        if sibling["status"] in ("DRAFT", "PROPOSED"):
            sibling["status"] = "CANCELLED"
            db.touch(sibling)
            record["supersedes_run_id"] = sibling["id"]
            for line in dv.lines_of_run(sibling["id"]):
                line["fulfillment_status"] = "RECALLED"
                line["units_allocated"] = 0
                db.touch(line)
    db.runs[record["id"]] = record
    if receipt["status"] == "STAGED":
        receipt["status"] = "ALLOCATING"
    db.touch(receipt)
    return env.created(dv.run_out(record))


@bp.get("/allocation/allocation-runs/<run_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_run(run_id):
    return env.ok(dv.run_out(gd.get_run(run_id)))


@bp.get("/allocation/allocation-runs")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_runs():
    receipt_id = va.q_str("receipt_id")
    supersedes = va.q_str("supersedes_run_id")
    status = va.q_enum("status", RUN_STATES)
    records = dv.by_created(list(db.runs.values()))
    if receipt_id:
        records = [r for r in records if r["receipt_id"] == receipt_id]
    if supersedes:
        records = [r for r in records if r["supersedes_run_id"] == supersedes]
    if status:
        records = [r for r in records if r["status"] == status]
    chunk, meta = va.page(records)
    return env.ok_array([dv.run_out(r) for r in chunk], meta)


@bp.post("/allocation/allocation-runs/<run_id>/propose")
@require("Allocator")
def propose_run(run_id):
    run = gd.get_run(run_id)
    if run["status"] != "DRAFT":
        gd.bad_state()
    receipt = db.receipts[run["receipt_id"]]
    program = gd.program_of_receipt(receipt)
    gd.decision_gate(program)
    item = db.items[receipt["item_id"]]

    # candidate filter (PRD 3.6): ACTIVE store, existing position, item not MARKDOWN
    base = []
    for store in dv.by_created(dv.stores_of_program(program["id"])):
        if store["status"] != "ACTIVE":
            continue
        position = dv.position_for(store["id"], item["id"])
        if position is None:
            continue
        if item["lifecycle_state"] == "MARKDOWN":
            continue
        base.append((store, position))
    # rung 25 before rungs 30/31
    plans = {}
    for store, position in base:
        plans[store["id"]] = gd.plan_in_effect_or_reject(store["id"], item["item_class"])
    if not base:
        raise ApiError("ERR_NO_ELIGIBLE_STORES")

    candidates = []
    for store, position in base:
        plan = plans[store["id"]]
        need = calc.store_need_units(run, store, item, position, plan)
        if need <= 0:
            continue
        candidates.append(
            {
                "store": store,
                "position": position,
                "plan": plan,
                "need": need,
                "headroom": dv.headroom(position, plan),
            }
        )
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_STORES")
    pool = dv.receipt_units_unallocated(receipt)
    if pool <= 0 or sum(c["need"] for c in candidates) == 0:
        raise ApiError("ERR_ZERO_NETWORK_NEED")

    alloc, capacity_capped, remaining = calc.receipt_proration(pool, candidates)
    profile = dv.profile_of_item(item)
    curve = profile["size_curve"] if profile else []
    for index, candidate in enumerate(candidates):
        units = alloc[index]
        if units <= 0:
            continue
        position = candidate["position"]
        available = dv.available_units(position)
        in_transit = dv.in_transit_units(position)
        line = db.base_record()
        line.update(
            {
                "run_id": run["id"],
                "store_id": candidate["store"]["id"],
                "need_units": candidate["need"],
                "units_proposed": units,
                "units_allocated": 0,
                "size_breakdown": calc.size_breakdown_split(curve, units),
                "capacity_capped_units": capacity_capped[index],
                "presentation_gap_units": max(
                    0,
                    candidate["plan"]["presentation_min_units"]
                    - (available + in_transit + units),
                ),
                "fulfillment_status": "PENDING",
            }
        )
        db.lines[line["id"]] = line
    run["status"] = "PROPOSED"
    run["unallocated_remainder_units"] = remaining
    run["eligible_store_count"] = len(candidates)
    db.touch(run)
    return env.ok(dv.run_out(run))


@bp.post("/allocation/allocation-runs/<run_id>/revise")
@require("Allocator")
def revise_run(run_id):
    run = gd.get_run(run_id)
    if run["status"] != "PROPOSED":
        gd.bad_state()
    gd.decision_gate(gd.program_of_run(run))
    for line in dv.lines_of_run(run["id"]):
        del db.lines[line["id"]]
    run["status"] = "DRAFT"
    run["unallocated_remainder_units"] = 0
    run["eligible_store_count"] = 0
    db.touch(run)
    return env.ok(dv.run_out(run))


@bp.post("/allocation/allocation-runs/<run_id>/commit")
@require("AllocationManager")
def commit_run(run_id):
    run = gd.get_run(run_id)
    if run["status"] != "PROPOSED":
        gd.bad_state()
    receipt = db.receipts[run["receipt_id"]]
    program = gd.program_of_receipt(receipt)
    gd.decision_gate(program)
    if g.user_id == run["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    item = db.items[receipt["item_id"]]
    lines = dv.by_created(dv.lines_of_run(run["id"]))
    context = []
    missing_plan = False
    for line in lines:
        position = dv.position_for(line["store_id"], item["id"])
        plan = dv.in_effect_plan(line["store_id"], item["item_class"])
        if plan is None:
            missing_plan = True
        context.append((line, position, plan))
    # rung 13, then rung 14, then rung 25 (a missing plan cannot violate 13 or 14)
    for line, position, plan in context:
        if plan is None or position is None:
            continue
        supply = (
            dv.available_units(position)
            + dv.in_transit_units(position)
            + line["units_proposed"]
        )
        if supply < plan["presentation_min_units"]:
            raise ApiError("ERR_PRESENTATION_MIN_NOT_MET")
    for line, position, plan in context:
        if plan is None or position is None:
            continue
        supply = (
            dv.available_units(position)
            + dv.in_transit_units(position)
            + line["units_proposed"]
        )
        if supply > plan["capacity_units"]:
            raise ApiError("ERR_FIXTURE_CAPACITY_EXCEEDED")
    if missing_plan:
        raise ApiError("ERR_NO_FIXTURE_PLAN_IN_EFFECT")
    proposed_total = sum(line["units_proposed"] for line in lines)
    if proposed_total > dv.receipt_units_unallocated(receipt):
        raise ApiError("ERR_RECEIPT_UNITS_EXCEEDED")

    for line in lines:
        line["units_allocated"] = line["units_proposed"]
        line["fulfillment_status"] = "PENDING"
        db.touch(line)
    run["status"] = "COMMITTED"
    run["committed_by_user_id"] = g.user_id
    db.touch(run)
    if receipt["status"] == "ALLOCATING" and dv.receipt_units_unallocated(receipt) == 0:
        receipt["status"] = "ALLOCATED"
        db.touch(receipt)
    return env.ok(dv.run_out(run))


@bp.post("/allocation/allocation-runs/<run_id>/recall")
@require("AllocationManager")
def recall_run(run_id):
    run = gd.get_run(run_id)
    if run["status"] != "COMMITTED":
        gd.bad_state()
    lines = dv.by_created(dv.lines_of_run(run["id"]))
    if any(line["fulfillment_status"] != "PENDING" for line in lines):
        raise ApiError("ERR_LINE_ALREADY_SHIPPED")
    for line in lines:
        line["units_allocated"] = 0
        line["fulfillment_status"] = "RECALLED"
        db.touch(line)
    run["status"] = "RECALLED"
    db.touch(run)
    receipt = db.receipts[run["receipt_id"]]
    if receipt["status"] == "ALLOCATED":
        receipt["status"] = "ALLOCATING"
        db.touch(receipt)
    return env.ok(dv.run_out(run))


@bp.post("/allocation/allocation-runs/<run_id>/cancel")
@require("Allocator", "AllocationManager")
def cancel_run(run_id):
    run = gd.get_run(run_id)
    if run["status"] not in ("DRAFT", "PROPOSED"):
        gd.bad_state()
    was_proposed = run["status"] == "PROPOSED"
    run["status"] = "CANCELLED"
    db.touch(run)
    if was_proposed:
        for line in dv.lines_of_run(run["id"]):
            line["fulfillment_status"] = "RECALLED"
            db.touch(line)
    return env.ok(dv.run_out(run))


# ================================ AllocationLine =============================
@bp.get("/allocation/allocation-lines/<line_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_line(line_id):
    return env.ok(dv.line_out(gd.get_line(line_id)))


@bp.get("/allocation/allocation-lines")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_lines():
    run_id = va.q_str("run_id")
    store_id = va.q_str("store_id")
    status = va.q_enum("fulfillment_status", LINE_STATES)
    records = dv.by_created(list(db.lines.values()))
    if run_id:
        records = [r for r in records if r["run_id"] == run_id]
    if store_id:
        records = [r for r in records if r["store_id"] == store_id]
    if status:
        records = [r for r in records if r["fulfillment_status"] == status]
    chunk, meta = va.page(records)
    return env.ok_array([dv.line_out(r) for r in chunk], meta)


@bp.post("/allocation/allocation-lines/<line_id>/ship")
@require("AllocationManager")
def ship_line(line_id):
    line = gd.get_line(line_id)
    run = db.runs[line["run_id"]]
    if line["fulfillment_status"] != "PENDING" or run["status"] != "COMMITTED":
        gd.bad_state()
    if line["units_allocated"] <= 0:
        gd.bad_state()
    line["fulfillment_status"] = "SHIPPED"
    db.touch(line)
    return env.ok(dv.line_out(line))


@bp.post("/allocation/allocation-lines/<line_id>/confirm-receipt")
@require("StoreOperator")
def confirm_line(line_id):
    line = db.lines.get(line_id)
    if line is not None:
        scope_check(line["store_id"])
    line = gd.get_line(line_id)
    if line["fulfillment_status"] != "SHIPPED":
        gd.bad_state()
    item = dv.line_item_id(line)
    position = dv.position_for(line["store_id"], item)
    line["fulfillment_status"] = "RECEIVED"
    db.touch(line)
    if position is not None:
        position["on_hand_units"] += line["units_allocated"]
        gd.merge_sizes(position["size_on_hand"], line["size_breakdown"])
        if position["on_hand_units"] > 0:
            position["consolidated_out"] = False
        db.touch(position)
        dv.propagate_position(position)
    return env.ok(dv.line_out(line))
