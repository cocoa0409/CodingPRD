"""Partial swaps inside a cycle (PRD 3.4)."""

from flask import Blueprint

import auth
import boxops
import constants as K
import derive
import envelope
import ledger
import listing
import lookup
import selector
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("swaps", __name__)


@bp.post("/kidswear/cycles/<cycle_id>/swap-requests")
def create_swap_request(cycle_id):
    caller = auth.gate("Member")
    body = shape.body_json()
    return_ids = shape.str_list(body, "return_box_item_ids")
    style_ids = shape.str_list(body, "requested_style_ids")
    expected_cycle_version = shape.integer(body, "expected_cycle_version")

    cycle = lookup.cycle(cycle_id)
    auth.own(caller, cycle["member_id"])
    member = lookup.member(cycle["member_id"])
    # rung 13
    for item_id in return_ids:
        item = store.get("box_items", item_id)
        if item is None:
            raise ApiError("ERR_REFERENCE_NOT_OWNED")
        box = boxops.box_of_item(item)
        if box is None or box["member_id"] != member["id"]:
            raise ApiError("ERR_REFERENCE_NOT_OWNED")
    for style_id in style_ids:
        if store.get("styles", style_id) is None:
            raise ApiError("ERR_REFERENCE_NOT_OWNED")

    lookup.standing(member, block_pending=True, block_delinquent=True)
    lookup.pause_gate_r(member)
    # rung 19
    if expected_cycle_version != cycle["version"]:
        raise ApiError("ERR_STALE_CYCLE_VERSION")
    # rung 23
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    clock = timeutil.now()
    # rung 33
    if clock > cycle["swap_by_at"]:
        raise ApiError("ERR_SWAP_WINDOW_CLOSED")
    # rung 38
    for item_id in return_ids:
        item = store.get("box_items", item_id)
        if item["embargo_until"] is not None and clock < item["embargo_until"]:
            raise ApiError("ERR_CAPSULE_EMBARGOED")
    # rung 46
    plan = lookup.plan(member["plan_id"])
    if (len(return_ids) != len(style_ids)
            or len(return_ids) < 1
            or len(return_ids) > plan["slots_per_box"]
            or len(style_ids) > plan["slots_per_box"]):
        raise ApiError("ERR_SWAP_SHAPE_INVALID")

    row = store.insert("swap_requests", {
        "cycle_id": cycle_id,
        "member_id": member["id"],
        "status": "DRAFT",
        "return_box_item_ids": list(return_ids),
        "requested_style_ids": list(style_ids),
        "allocated_unit_ids": [],
        "slot_delta": 0,
        "rejection_reason": None,
    })
    store.touch(cycle)
    return envelope.created(serialize.swap_request(row))


@bp.get("/kidswear/swap-requests")
def list_swap_requests():
    caller = auth.gate("WarehouseOperator", "PlatformAdmin", "Member", "BillingAgent")
    rows = store.all_rows("swap_requests")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "cycle_id", shape.query_str("cycle_id"))
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.SWAP_STATUSES))
    return envelope.listing(rows, serialize.swap_request)


@bp.get("/kidswear/swap-requests/<swap_request_id>")
def read_swap_request(swap_request_id):
    caller = auth.gate("WarehouseOperator", "PlatformAdmin", "Member", "BillingAgent")
    row = lookup.swap_request(swap_request_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.swap_request(row))


@bp.post("/kidswear/swap-requests/<swap_request_id>/submit")
def submit_swap(swap_request_id):
    caller = auth.gate("Member")
    request = lookup.swap_request(swap_request_id)
    auth.own(caller, request["member_id"])
    member = lookup.member(request["member_id"])
    cycle = lookup.cycle(request["cycle_id"])
    lookup.standing(member, block_pending=True)
    lookup.pause_gate_r(member)
    # rung 23 is a numbered G7 rung naming this endpoint, so it is evaluated
    # ahead of the swap request's own (un-numbered) from-state check.
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    if request["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if timeutil.now() > cycle["swap_by_at"]:
        raise ApiError("ERR_SWAP_WINDOW_CLOSED")
    plan = lookup.plan(member["plan_id"])
    if derive.swap_entitlement_remaining(cycle, plan) < 1:
        raise ApiError("ERR_SWAP_ENTITLEMENT_EXHAUSTED")
    request["status"] = "SUBMITTED"
    store.touch(request)
    return envelope.ok(serialize.swap_request(request))


@bp.post("/kidswear/swap-requests/<swap_request_id>/approve")
def approve_swap(swap_request_id):
    auth.gate("WarehouseOperator")
    request = lookup.swap_request(swap_request_id)
    member = lookup.member(request["member_id"])
    lookup.standing(member, block_pending=True)
    if request["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    picked = []
    for style_id in request["requested_style_ids"]:
        style = lookup.style(style_id)
        unit = selector.swap_replacement(style, member, exclude_ids=set(picked))
        picked.append(unit["id"])
    for unit_id in picked:
        unit = store.get("units", unit_id)
        unit["state"] = "RESERVED"
        store.touch(unit)
    request["allocated_unit_ids"] = picked
    request["slot_delta"] = len(picked) - len(request["return_box_item_ids"])
    request["status"] = "APPROVED"
    store.touch(request)
    return envelope.ok(serialize.swap_request(request))


@bp.post("/kidswear/swap-requests/<swap_request_id>/reject")
def reject_swap(swap_request_id):
    auth.gate("WarehouseOperator")
    body = shape.body_json()
    reason = shape.enum_in(body, "rejection_reason", K.SWAP_REJECTION_REASONS)
    request = lookup.swap_request(swap_request_id)
    member = lookup.member(request["member_id"])
    lookup.standing(member, block_pending=True)
    if request["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    request["status"] = "REJECTED"
    request["rejection_reason"] = reason
    store.touch(request)
    for item_id in request["return_box_item_ids"]:
        item = store.get("box_items", item_id)
        if item is not None and item["fulfillment_status"] == "ALLOCATED":
            ledger.cancel_box_item(item)
            box = boxops.box_of_item(item)
            if box is not None:
                boxops.maybe_close_box(box)
    return envelope.ok(serialize.swap_request(request))


@bp.post("/kidswear/swap-requests/<swap_request_id>/fulfill")
def fulfill_swap(swap_request_id):
    auth.gate("WarehouseOperator")
    request = lookup.swap_request(swap_request_id)
    member = lookup.member(request["member_id"])
    lookup.standing(member, block_pending=True)
    if request["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    target_box = None
    for item_id in request["return_box_item_ids"]:
        item = store.get("box_items", item_id)
        if item is None or item["fulfillment_status"] != "RECEIVED":
            raise ApiError("ERR_RETURN_ITEM_NOT_RECEIVED")
        if target_box is None:
            target_box = boxops.box_of_item(item)
    slot_delta = len(request["allocated_unit_ids"]) - len(request["return_box_item_ids"])
    if slot_delta != 0:
        raise ApiError("ERR_SWAP_CONSERVATION_VIOLATION")
    request["slot_delta"] = slot_delta
    for unit_id in request["allocated_unit_ids"]:
        unit = store.get("units", unit_id)
        embargo_until = None
        if unit is not None and unit["capsule_id"] is not None:
            capsule = store.get("capsules", unit["capsule_id"])
            if capsule is not None:
                embargo_until = capsule["embargo_until"]
        store.insert("box_items", {
            "box_id": target_box["id"],
            "unit_id": unit_id,
            "return_shipment_id": None,
            "fulfillment_status": "ALLOCATED",
            "settlement_status": "OPEN",
            "slot_index": boxops.next_slot_index(target_box["id"]),
            "is_capsule_item": unit is not None and unit["capsule_id"] is not None,
            "embargo_until": embargo_until,
            "days_late": 0,
            "late_fee_cents": 0,
            "damage_fee_cents": 0,
            "assessed_grade": None,
        })
    request["status"] = "FULFILLED"
    store.touch(request)
    return envelope.ok(serialize.swap_request(request))
