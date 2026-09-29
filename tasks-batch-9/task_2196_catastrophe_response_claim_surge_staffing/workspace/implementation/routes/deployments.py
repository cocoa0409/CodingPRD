"""Deployment endpoints: the 5-link demobilize chain and the cancel compensation."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import derive
import ops
import store
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing, require_open_posture
from store import clock_now, touch

bp = Blueprint("deployments", __name__)

ROLE_TYPES = ("FIELD", "DESK", "AERIAL")


@bp.post("/deployments")
def create_deployment():
    begin()
    soft = validate.soft_body()
    # Existence in ladder order: event (4), adjuster (6), housing block (7).
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None
    raw_adjuster = validate.raw_ref(soft, "adjuster_id")
    adjuster = validate.adjuster(raw_adjuster) if raw_adjuster is not None else None
    raw_block = validate.raw_ref(soft, "housing_block_id")
    block = validate.housing_block(raw_block) if raw_block is not None else None

    payload = validate.body()
    if event is None:
        validate.req_string(payload, "event_id")
    role_type = validate.req_enum(payload, "role_type", ROLE_TYPES)
    start = validate.req_datetime(payload, "window_start_utc")
    end = validate.req_datetime(payload, "window_end_utc")
    default_rooms = 0 if role_type == "DESK" else 1
    rooms = validate.opt_int(payload, "rooms_reserved", minimum=0, maximum=4,
                             default=default_rooms)
    if role_type == "DESK" and rooms != 0:
        fail("ERR_VALIDATION", "rooms_reserved must be 0 for a DESK deployment.")
    # Position 16.
    validate.interval(start, end,
                      "window_end_utc must be strictly later than window_start_utc.")
    # Position 20.
    require_open_posture(event)
    # Position 30 - cross-aggregate scope.
    if block is not None and block["event_id"] != event["id"]:
        fail("ERR_EVENT_SCOPE_MISMATCH")

    if adjuster is None:
        # Position 35 - the selector pool must not be empty.
        adjuster = ops.select_adjuster(event, role_type, start, end)
        selection_reason = "SELECTOR_RANKED"
    else:
        selection_reason = "EXPLICIT_ADJUSTER"

    rec = store.base_record()
    rec.update({
        "event_id": event["id"],
        "adjuster_id": adjuster["id"],
        "housing_block_id": None if block is None else block["id"],
        "role_type": role_type,
        "window_start_utc": start,
        "window_end_utc": end,
        "rooms_reserved": rooms,
        "status": "REQUESTED",
        "selection_reason": selection_reason,
        "provisional_cost": Decimal("0.00"),
        "final_settled_cost": Decimal("0.00"),
        "surge_premium_tier": "TIER_NONE",
        "demobilized_at_utc": None,
    })
    store.deployments[rec["id"]] = rec
    return created(derive.deployment_out(rec))


@bp.get("/deployments")
def list_deployments():
    begin()
    rows = list(store.deployments.values())
    for param, field in (("event_id", "event_id"), ("adjuster_id", "adjuster_id"),
                         ("housing_block_id", "housing_block_id"),
                         ("status", "status"), ("role_type", "role_type")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.deployment_out)


@bp.get("/deployments/<deployment_id>")
def read_deployment(deployment_id):
    begin()
    return ok(derive.deployment_out(validate.deployment(deployment_id)))


@bp.post("/deployments/<deployment_id>/confirm")
def confirm_deployment(deployment_id):
    begin()
    rec = validate.deployment(deployment_id)
    event = store.events.get(rec["event_id"])
    adjuster = store.adjusters.get(rec["adjuster_id"])
    block = store.housing_blocks.get(rec.get("housing_block_id"))

    # Position 19 - state.
    if rec["status"] != "REQUESTED":
        fail("ERR_DEPLOYMENT_NOT_REQUESTED")
    if adjuster is None or adjuster["deployment_status"] != "AVAILABLE":
        fail("ERR_ADJUSTER_NOT_AVAILABLE")
    if adjuster["credential_status"] not in ("VALID", "EXPIRING", "WAIVED"):
        fail("ERR_ADJUSTER_CREDENTIAL_INVALID")
    # Position 20.
    require_open_posture(event)
    # Position 23 - BUFFERED HALF-OPEN, exact adjacency rejected.  Pair B: this
    # outranks the housing capacity check at position 38.
    if ops.rest_conflict(rec["adjuster_id"], rec["window_start_utc"],
                         rec["window_end_utc"], ignore_deployment_id=rec["id"]):
        fail("ERR_DEPLOYMENT_WINDOW_CONFLICT")
    # Position 24 - AGGREGATE NIGHTLY housing capacity.
    if rec["role_type"] != "DESK" and block is not None:
        if ops.nightly_capacity_exceeded(block, rec):
            fail("ERR_HOUSING_CAPACITY_EXCEEDED")
    # Position 27 - licensing, waived credentials excepted.
    if adjuster["credential_status"] != "WAIVED" \
            and event["jurisdiction_state"] not in adjuster["licensed_states"]:
        fail("ERR_ADJUSTER_NOT_LICENSED_IN_STATE")
    # Position 38 - rooms_available >= rooms_reserved at confirm time.
    if rec["role_type"] != "DESK":
        if block is None or block["status"] != "ACTIVE":
            fail("ERR_HOUSING_CAPACITY_EXCEEDED")
        available = int(block["rooms_total"]) - derive.block_rooms_occupied(block["id"])
        if available < int(rec["rooms_reserved"]):
            fail("ERR_HOUSING_CAPACITY_EXCEEDED")

    rec["status"] = "CONFIRMED"
    cost, tier = calc.deployment_cost(rec, adjuster, block, "PROVISIONAL")
    rec["provisional_cost"] = cost
    rec["surge_premium_tier"] = tier
    touch(rec)
    adjuster["deployment_status"] = "DEPLOYED"
    touch(adjuster)
    ops.sync_block_occupancy(block)
    touch(event)
    return ok(derive.deployment_out(rec))


@bp.post("/deployments/<deployment_id>/check-in")
def check_in_deployment(deployment_id):
    begin()
    rec = validate.deployment(deployment_id)
    if rec["status"] != "CONFIRMED":
        fail("ERR_DEPLOYMENT_NOT_CONFIRMED")
    if clock_now() < rec["window_start_utc"]:
        fail("ERR_DEPLOYMENT_WINDOW_NOT_STARTED")
    rec["status"] = "ON_SITE"
    touch(rec)
    return ok(derive.deployment_out(rec))


@bp.post("/deployments/<deployment_id>/demobilize")
def demobilize_deployment(deployment_id):
    begin()
    rec = validate.deployment(deployment_id)
    if rec["status"] not in ("CONFIRMED", "ON_SITE"):
        fail("ERR_DEPLOYMENT_NOT_DEMOBILIZABLE")
    event = store.events.get(rec["event_id"])
    adjuster = store.adjusters.get(rec["adjuster_id"])
    block = store.housing_blocks.get(rec.get("housing_block_id"))

    # Link 1: settle.
    rec["status"] = "DEMOBILIZED"
    rec["demobilized_at_utc"] = clock_now()
    cost, tier = calc.deployment_cost(rec, adjuster, block, "FINAL_SETTLED")
    rec["final_settled_cost"] = cost
    rec["surge_premium_tier"] = tier
    touch(rec)
    # Rooms are released by the status change; refresh the block's own axis.
    ops.sync_block_occupancy(block)
    # Link 2: the adjuster rests.
    ops.rest_adjuster(adjuster)
    # Links 3 and 4: live inspection work is cancelled, claims regress.
    ops.cancel_adjuster_live_assignments(rec["adjuster_id"])
    # Link 5: the event's posture is derived on read, nothing to stamp.
    touch(event)
    return ok(derive.deployment_out(rec))


@bp.post("/deployments/<deployment_id>/cancel")
def cancel_deployment(deployment_id):
    begin()
    rec = validate.deployment(deployment_id)
    if rec["status"] not in ("REQUESTED", "CONFIRMED"):
        fail("ERR_DEPLOYMENT_NOT_CANCELLABLE")
    if rec["status"] == "CONFIRMED":
        in_flight = [a for a in store.assignments.values()
                     if a.get("deployment_id") == rec["id"]
                     and a["status"] in ("IN_PROGRESS", "COMPLETED")]
        if in_flight:
            fail("ERR_ASSIGNMENTS_IN_FLIGHT")

    was_confirmed = rec["status"] == "CONFIRMED"
    event = store.events.get(rec["event_id"])
    adjuster = store.adjusters.get(rec["adjuster_id"])
    block = store.housing_blocks.get(rec.get("housing_block_id"))

    rec["status"] = "CANCELLED"
    rec["final_settled_cost"] = Decimal("0.00")
    touch(rec)
    if was_confirmed:
        # Links 2 and 3: rooms return exactly, EXHAUSTED -> ACTIVE when freed.
        ops.sync_block_occupancy(block)
        ops.rest_adjuster(adjuster)
    touch(event)
    return ok(derive.deployment_out(rec))
