"""Transfer recommendations: freight economics and lifecycle (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import derive as dv
import envelope as env
import guards as gd
import store as db
import validation as va
from auth import require, scope_check
from errors import ApiError

bp = Blueprint("transfers", __name__)

TRANSFER_STATES = (
    "PROPOSED",
    "APPROVED",
    "REJECTED",
    "DISPATCHED",
    "RECEIVED",
    "CANCELLED",
    "EXPIRED",
)
TRANSFER_TTL_DAYS = 7


def donor_position_or_reject(store_id, item_id):
    """PRD 2.10: a donor-store-and-item pair with no position is a 404."""
    position = dv.position_for(store_id, item_id)
    if position is None:
        raise ApiError("ERR_POSITION_NOT_FOUND")
    return position


def build_transfer(
    program,
    from_store,
    to_store,
    item,
    units,
    source_reason,
    proposed_by_user_id,
    donor,
    receiver,
    assortment_action_id=None,
):
    """Freeze the four economics figures and open the recommendation.

    Shared by operator creation (REBALANCE) and assortment-action execution
    (CONSOLIDATION); none of the figures is ever recomputed afterwards.
    """
    size_split = calc.transfer_size_split(item, donor, receiver, units, source_reason)
    if not size_split:
        raise ApiError("ERR_TRANSFER_SIZE_INFEASIBLE")
    freight, handling, landed = calc.transfer_landed_cost(from_store, units)
    benefit = calc.transfer_benefit(item, to_store, size_split)
    ratio_bp = calc.benefit_ratio_bp(benefit, landed)
    superseded_id = None
    for peer in dv.by_created(list(db.transfers.values())):
        if (
            peer["status"] == "PROPOSED"
            and peer["from_store_id"] == from_store["id"]
            and peer["to_store_id"] == to_store["id"]
            and peer["item_id"] == item["id"]
        ):
            peer["status"] = "CANCELLED"
            peer["reject_reason"] = "superseded"
            db.touch(peer)
            superseded_id = peer["id"]
    record = db.base_record()
    record.update(
        {
            "program_id": program["id"],
            "from_store_id": from_store["id"],
            "to_store_id": to_store["id"],
            "item_id": item["id"],
            "units": units,
            "source_reason": source_reason,
            "size_split": size_split,
            "freight_cost_usd": freight,
            "handling_fee_usd": handling,
            "landed_cost_usd": landed,
            "benefit_usd": benefit,
            "benefit_ratio_bp": ratio_bp,
            "status": "PROPOSED",
            "expires_at": db.now() + timedelta(days=TRANSFER_TTL_DAYS),
            "proposed_by_user_id": proposed_by_user_id,
            "approved_by_user_id": None,
            "reject_reason": None,
            "supersedes_recommendation_id": superseded_id,
            "assortment_action_id": assortment_action_id,
        }
    )
    db.transfers[record["id"]] = record
    return record


@bp.post("/allocation/transfer-recommendations")
@require("Allocator")
def create_transfer():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    from_store_id = va.get_str(data, "from_store_id")
    to_store_id = va.get_str(data, "to_store_id")
    item_id = va.get_str(data, "item_id")
    units = va.get_int(data, "units", minimum=1)
    expected = va.get_int(data, "expected_from_position_version", minimum=0)
    program = gd.get_program(program_id)
    from_store = gd.get_store(from_store_id)
    to_store = gd.get_store(to_store_id)
    item = gd.get_item(item_id)
    if (
        from_store["program_id"] != program["id"]
        or to_store["program_id"] != program["id"]
        or item["program_id"] != program["id"]
    ):
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE")
    gd.decision_gate(program)
    donor = donor_position_or_reject(from_store["id"], item["id"])
    receiver = donor_position_or_reject(to_store["id"], item["id"])
    if donor["version"] != expected:
        raise ApiError("ERR_STALE_POSITION_VERSION")
    if from_store["id"] == to_store["id"]:
        raise ApiError("ERR_SAME_STORE_TRANSFER")
    if to_store["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_NOT_ELIGIBLE")
    size_split = calc.transfer_size_split(item, donor, receiver, units, "REBALANCE")
    if not size_split:
        raise ApiError("ERR_TRANSFER_SIZE_INFEASIBLE")
    if dv.available_units(donor) < units:
        raise ApiError("ERR_INSUFFICIENT_DONOR_UNITS")
    record = build_transfer(
        program,
        from_store,
        to_store,
        item,
        units,
        "REBALANCE",
        g.user_id,
        donor,
        receiver,
    )
    db.touch(donor)
    return env.created(dv.transfer_out(record))


@bp.get("/allocation/transfer-recommendations/<recommendation_id>")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def read_transfer(recommendation_id):
    return env.ok(dv.transfer_out(gd.get_transfer(recommendation_id)))


@bp.get("/allocation/transfer-recommendations")
@require("PlanningAdmin", "Allocator", "AllocationManager")
def list_transfers():
    filters = {
        "program_id": va.q_str("program_id"),
        "from_store_id": va.q_str("from_store_id"),
        "to_store_id": va.q_str("to_store_id"),
        "item_id": va.q_str("item_id"),
        "supersedes_recommendation_id": va.q_str("supersedes_recommendation_id"),
        "assortment_action_id": va.q_str("assortment_action_id"),
        "status": va.q_enum("status", TRANSFER_STATES),
    }
    records = dv.by_created(list(db.transfers.values()))
    for field, value in filters.items():
        if value:
            records = [r for r in records if r.get(field) == value]
    chunk, meta = va.page(records)
    return env.ok_array([dv.transfer_out(r) for r in chunk], meta)


@bp.post("/allocation/transfer-recommendations/<recommendation_id>/approve")
@require("AllocationManager")
def approve_transfer(recommendation_id):
    transfer = gd.get_transfer(recommendation_id)
    if transfer["status"] != "PROPOSED":
        gd.bad_state()
    program = gd.get_program(transfer["program_id"])
    gd.decision_gate(program)
    if db.now() >= transfer["expires_at"]:
        raise ApiError("ERR_TRANSFER_EXPIRED")
    if g.user_id == transfer["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    item = db.items[transfer["item_id"]]
    donor = donor_position_or_reject(transfer["from_store_id"], item["id"])
    receiver = donor_position_or_reject(transfer["to_store_id"], item["id"])
    plan = gd.plan_in_effect_or_reject(transfer["to_store_id"], item["item_class"])
    if transfer["source_reason"] == "REBALANCE" and (
        transfer["benefit_ratio_bp"] < program["transfer_min_ratio_bp"]
    ):
        raise ApiError("ERR_BENEFIT_RATIO_BELOW_THRESHOLD")
    if dv.available_units(donor) < transfer["units"]:
        raise ApiError("ERR_INSUFFICIENT_DONOR_UNITS")
    if dv.headroom(receiver, plan) < transfer["units"]:
        raise ApiError("ERR_FIXTURE_CAPACITY_EXCEEDED")
    transfer["status"] = "APPROVED"
    transfer["approved_by_user_id"] = g.user_id
    db.touch(transfer)
    dv.propagate_position(donor)
    return env.ok(dv.transfer_out(transfer))


@bp.post("/allocation/transfer-recommendations/<recommendation_id>/reject")
@require("AllocationManager")
def reject_transfer(recommendation_id):
    data = va.body()
    reason = va.get_str(data, "reason")
    transfer = gd.get_transfer(recommendation_id)
    if transfer["status"] != "PROPOSED":
        gd.bad_state()
    transfer["status"] = "REJECTED"
    transfer["reject_reason"] = reason
    db.touch(transfer)
    return env.ok(dv.transfer_out(transfer))


@bp.post("/allocation/transfer-recommendations/<recommendation_id>/dispatch")
@require("AllocationManager")
def dispatch_transfer(recommendation_id):
    transfer = gd.get_transfer(recommendation_id)
    if transfer["status"] != "APPROVED":
        gd.bad_state()
    program = gd.get_program(transfer["program_id"])
    gd.decision_gate(program)
    to_store = gd.get_store(transfer["to_store_id"])
    if to_store["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_NOT_ELIGIBLE")
    item = db.items[transfer["item_id"]]
    donor = donor_position_or_reject(transfer["from_store_id"], item["id"])
    receiver = dv.position_for(transfer["to_store_id"], item["id"])
    transfer["status"] = "DISPATCHED"
    db.touch(transfer)
    donor["on_hand_units"] = max(0, donor["on_hand_units"] - transfer["units"])
    gd.subtract_sizes(donor["size_on_hand"], transfer["size_split"])
    db.touch(donor)
    dv.propagate_position(donor)
    if receiver is not None:
        dv.propagate_position(receiver)
    dv.rederive_item_lifecycle(item)
    return env.ok(dv.transfer_out(transfer))


@bp.post("/allocation/transfer-recommendations/<recommendation_id>/receive")
@require("StoreOperator")
def receive_transfer(recommendation_id):
    transfer = db.transfers.get(recommendation_id)
    if transfer is not None:
        scope_check(transfer["to_store_id"])
    transfer = gd.get_transfer(recommendation_id)
    if transfer["status"] != "DISPATCHED":
        gd.bad_state()
    item = db.items[transfer["item_id"]]
    donor = dv.position_for(transfer["from_store_id"], item["id"])
    receiver = dv.position_for(transfer["to_store_id"], item["id"])
    transfer["status"] = "RECEIVED"
    db.touch(transfer)
    if receiver is not None:
        receiver["on_hand_units"] += transfer["units"]
        gd.merge_sizes(receiver["size_on_hand"], transfer["size_split"])
        if receiver["on_hand_units"] > 0:
            receiver["consolidated_out"] = False
        db.touch(receiver)
    if donor is not None:
        if donor["on_hand_units"] == 0 and transfer["source_reason"] == "CONSOLIDATION":
            donor["consolidated_out"] = True
            db.touch(donor)
        dv.propagate_position(donor)
    if receiver is not None:
        dv.propagate_position(receiver)
    dv.rederive_item_lifecycle(item)
    return env.ok(dv.transfer_out(transfer))


@bp.post("/allocation/transfer-recommendations/<recommendation_id>/cancel")
@require("AllocationManager")
def cancel_transfer(recommendation_id):
    data = va.body()
    reason = va.get_str(data, "reason")
    transfer = gd.get_transfer(recommendation_id)
    if transfer["status"] != "APPROVED":
        gd.bad_state()
    item = db.items.get(transfer["item_id"])
    donor = dv.position_for(transfer["from_store_id"], transfer["item_id"])
    transfer["status"] = "CANCELLED"
    transfer["reject_reason"] = reason
    db.touch(transfer)
    if donor is not None:
        dv.propagate_position(donor)
    if item is not None:
        dv.rederive_item_lifecycle(item)
    return env.ok(dv.transfer_out(transfer))


@bp.post("/allocation/_run-transfer-expiry")
@require("AllocationManager")
def run_transfer_expiry():
    data = va.body()
    program_id = va.get_str(data, "program_id")
    program = gd.get_program(program_id)
    clock = db.now()
    expired = []
    for transfer in dv.by_created(list(db.transfers.values())):
        if transfer["program_id"] != program["id"]:
            continue
        if transfer["status"] != "PROPOSED":
            continue
        if transfer["expires_at"] <= clock:
            transfer["status"] = "EXPIRED"
            db.touch(transfer)
            expired.append(transfer)
    return env.ok_array([dv.transfer_out(t) for t in expired])
