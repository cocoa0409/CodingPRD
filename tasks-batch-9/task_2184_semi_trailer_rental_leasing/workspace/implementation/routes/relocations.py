"""Repositioning orders."""

from flask import Blueprint

import calc
import envelope
import serializers
import services
import store
import validate
from auth import authenticate, require_owner
from errors import fail

bp = Blueprint("relocations", __name__)

RELOCATION_ROLES = ["FleetAdmin", "BranchManager"]
RELOCATION_STATUSES = ("REQUESTED", "APPROVED", "REJECTED", "IN_TRANSIT", "COMPLETED", "CANCELLED")


@bp.post("/fleet/relocation-orders")
def create_relocation():
    authenticate(RELOCATION_ROLES)
    payload = validate.body()
    trailer = None
    if validate.present(payload, "trailer_id") and isinstance(payload["trailer_id"], str):
        trailer = services.get_trailer(payload["trailer_id"])
    if validate.present(payload, "destination_branch_id") and isinstance(payload["destination_branch_id"], str):
        services.get_branch(payload["destination_branch_id"])

    trailer_id = validate.req_string(payload, "trailer_id")
    destination_branch_id = validate.req_string(payload, "destination_branch_id")
    depart = validate.req_date(payload, "planned_depart_date")
    arrive = validate.req_date(payload, "planned_arrive_date")
    planned_miles = validate.req_int(payload, "planned_miles", minimum=0)

    if arrive < depart:
        fail("ERR_INVALID_DATE_RANGE", "planned_arrive_date must be on or after planned_depart_date")

    if calc.trailer_service_status(trailer) != "SERVICEABLE":
        fail("ERR_TRAILER_OUT_OF_SERVICE", "Trailer is not serviceable")
    if trailer["current_branch_id"] == destination_branch_id:
        fail("ERR_TRAILER_BRANCH_MISMATCH", "The trailer already stands at the destination yard")

    rec = store.new_record()
    rec.update({
        "trailer_id": trailer_id,
        "origin_branch_id": trailer["current_branch_id"],
        "destination_branch_id": destination_branch_id,
        "status": "REQUESTED",
        "planned_depart_date": depart.isoformat(),
        "planned_arrive_date": arrive.isoformat(),
        "planned_miles": planned_miles,
        "actual_miles": None,
        "deadhead_miles": None,
        "actual_arrive_date": None,
        "estimated_cost_cents": calc.relocation_cost_cents(planned_miles, 0),
        "actual_cost_cents": None,
        "reject_reason": None,
        "cancel_reason": None,
    })
    store.relocation_orders[rec["id"]] = rec
    return envelope.created(serializers.relocation_order(rec))


@bp.get("/fleet/relocation-orders/<relocation_order_id>")
def read_relocation(relocation_order_id):
    authenticate(RELOCATION_ROLES)
    return envelope.ok(serializers.relocation_order(services.get_relocation(relocation_order_id)))


@bp.get("/fleet/relocation-orders")
def list_relocations():
    authenticate(RELOCATION_ROLES)
    limit, offset = validate.pagination()
    trailer_id = validate.query("trailer_id")
    origin = validate.query("origin_branch_id")
    destination = validate.query("destination_branch_id")
    status = validate.query_enum("status", RELOCATION_STATUSES)
    rows = []
    for o in store.relocation_orders.values():
        if trailer_id is not None and o["trailer_id"] != trailer_id:
            continue
        if origin is not None and o["origin_branch_id"] != origin:
            continue
        if destination is not None and o["destination_branch_id"] != destination:
            continue
        if status is not None and o["status"] != status:
            continue
        rows.append(o)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.relocation_order(r) for r in page], limit, offset, len(rows))


@bp.post("/fleet/relocation-orders/<relocation_order_id>/approve")
def approve_relocation(relocation_order_id):
    caller = authenticate(RELOCATION_ROLES)
    order = services.get_relocation(relocation_order_id)
    validate.body()
    if caller.is_branch_manager:
        require_owner(caller, order["destination_branch_id"])

    if order["status"] != "REQUESTED":
        fail("ERR_RELOCATION_NOT_REQUESTED", "Relocation order is not REQUESTED")

    destination = store.branches.get(order["destination_branch_id"])
    win_start, win_end = calc.inbound_window(order)
    committed = 0
    for other in store.relocation_orders.values():
        if other["id"] == order["id"]:
            continue
        if other["destination_branch_id"] != order["destination_branch_id"]:
            continue
        if other["status"] not in ("APPROVED", "IN_TRANSIT"):
            continue
        other_start, other_end = calc.inbound_window(other)
        if other_start is None or win_start is None:
            continue
        if calc.closed_overlap(other_start, other_end, win_start, win_end):
            committed += 1

    on_hand = calc.branch_on_hand_count(destination["id"])
    if on_hand + committed + 1 > destination["yard_capacity"]:
        fail("ERR_BRANCH_YARD_CAPACITY_EXCEEDED", "The destination yard has no inbound room")

    order["status"] = "APPROVED"
    store.touch(order)
    return envelope.ok(serializers.relocation_order(order))


@bp.post("/fleet/relocation-orders/<relocation_order_id>/reject")
def reject_relocation(relocation_order_id):
    authenticate(RELOCATION_ROLES)
    order = services.get_relocation(relocation_order_id)
    payload = validate.body()
    reason = validate.req_string(payload, "reason")

    if order["status"] != "REQUESTED":
        fail("ERR_RELOCATION_NOT_REQUESTED", "Relocation order is not REQUESTED")

    order["status"] = "REJECTED"
    order["reject_reason"] = reason
    store.touch(order)
    return envelope.ok(serializers.relocation_order(order))


@bp.post("/fleet/relocation-orders/<relocation_order_id>/dispatch")
def dispatch_relocation(relocation_order_id):
    authenticate(RELOCATION_ROLES)
    order = services.get_relocation(relocation_order_id)
    validate.body()

    if order["status"] != "APPROVED":
        fail("ERR_RELOCATION_NOT_APPROVED", "Relocation order is not APPROVED")

    trailer = store.trailers.get(order["trailer_id"])
    if trailer is None or calc.trailer_service_status(trailer) != "SERVICEABLE":
        fail("ERR_TRAILER_OUT_OF_SERVICE", "Trailer is not serviceable")
    if trailer["availability_status"] != "AVAILABLE":
        fail("ERR_TRAILER_NOT_AVAILABLE", "Trailer is not idle")

    trailer["availability_status"] = "IN_TRANSIT"
    store.touch(trailer)
    order["status"] = "IN_TRANSIT"
    store.touch(order)
    return envelope.ok(serializers.relocation_order(order))


@bp.post("/fleet/relocation-orders/<relocation_order_id>/complete")
def complete_relocation(relocation_order_id):
    authenticate(RELOCATION_ROLES)
    order = services.get_relocation(relocation_order_id)
    payload = validate.body()
    actual_miles = validate.req_int(payload, "actual_miles", minimum=0)
    deadhead_miles = validate.req_int(payload, "deadhead_miles", minimum=0)
    actual_arrive = validate.req_date(payload, "actual_arrive_date")

    depart = store.parse_date(order["planned_depart_date"])
    if actual_arrive < depart:
        fail("ERR_INVALID_DATE_RANGE", "actual_arrive_date must be on or after planned_depart_date")

    if order["status"] != "IN_TRANSIT":
        fail("ERR_RELOCATION_NOT_IN_TRANSIT", "Relocation order is not IN_TRANSIT")

    order["actual_miles"] = actual_miles
    order["deadhead_miles"] = deadhead_miles
    order["actual_arrive_date"] = actual_arrive.isoformat()
    order["actual_cost_cents"] = calc.relocation_cost_cents(actual_miles, deadhead_miles)
    order["status"] = "COMPLETED"
    store.touch(order)

    trailer = store.trailers.get(order["trailer_id"])
    if trailer is not None:
        trailer["current_branch_id"] = order["destination_branch_id"]
        trailer["availability_status"] = "AVAILABLE"
        store.touch(trailer)
    return envelope.ok(serializers.relocation_order(order))


@bp.post("/fleet/relocation-orders/<relocation_order_id>/abort")
def abort_relocation(relocation_order_id):
    authenticate(RELOCATION_ROLES)
    order = services.get_relocation(relocation_order_id)
    payload = validate.body()
    reason = validate.req_string(payload, "reason")

    if order["status"] != "IN_TRANSIT":
        fail("ERR_RELOCATION_NOT_IN_TRANSIT", "Relocation order is not IN_TRANSIT")

    order["status"] = "CANCELLED"
    order["cancel_reason"] = reason
    store.touch(order)

    trailer = store.trailers.get(order["trailer_id"])
    if trailer is not None:
        trailer["availability_status"] = "AVAILABLE"
        trailer["current_branch_id"] = order["origin_branch_id"]
        store.touch(trailer)
    return envelope.ok(serializers.relocation_order(order))
