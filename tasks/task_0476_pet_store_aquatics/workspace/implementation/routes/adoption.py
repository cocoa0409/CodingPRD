"""AdoptionEvent + AdoptionPlacement endpoints (PRD §3.4, §3.6)."""
from flask import Blueprint, request

import db
from db import stamp_create, touch
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_int, as_datetime,
)
from services.serialize import event_out, placement_out

bp = Blueprint("adoption", __name__)

EVENT_READ_ROLES = ["InventoryManager", "LivestockKeeper", "StoreClerk", "Customer"]
PLACEMENT_READ_ROLES = ["InventoryManager", "LivestockKeeper", "StoreClerk", "Customer"]


# ---------------------------------------------------------------------------
# AdoptionEvent
# ---------------------------------------------------------------------------
@bp.route("/adoption-events", methods=["POST"])
def schedule_event():
    _, role = require_auth()
    require_role(role, ["StoreClerk"])
    body = get_body()
    store_id = as_str(require_present(body, "store_id"), "store_id")
    lookup("stores", store_id)
    partner_name = as_str(require_present(body, "partner_name"), "partner_name")
    event_date = require_present(body, "event_date")
    as_datetime(event_date, "event_date")
    capacity = as_int(require_present(body, "capacity"), "capacity")
    if capacity <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "capacity must be > 0.")

    record = {
        "store_id": store_id,
        "partner_name": partner_name,
        "event_date": event_date,
        "capacity": capacity,
        "placed_head": 0,
        "status": "SCHEDULED",
    }
    stamp_create(record)
    db.adoption_events[record["id"]] = record
    return object_response(event_out(record), 201)


@bp.route("/adoption-events", methods=["GET"])
def list_events():
    _, role = require_auth()
    require_role(role, EVENT_READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.adoption_events.values())
    store_id = request.args.get("store_id")
    if store_id is not None:
        records = [r for r in records if r["store_id"] == store_id]
    page, total = paginate(records, limit, offset)
    return array_response([event_out(r) for r in page], limit, offset, total)


@bp.route("/adoption-events/<event_id>", methods=["GET"])
def get_event(event_id):
    _, role = require_auth()
    require_role(role, EVENT_READ_ROLES)
    record = lookup("adoption_events", event_id)
    return object_response(event_out(record))


@bp.route("/adoption-events/<event_id>/open", methods=["POST"])
def open_event(event_id):
    _, role = require_auth()
    require_role(role, ["StoreClerk"])
    event = lookup("adoption_events", event_id)
    if event["status"] != "SCHEDULED":
        raise err("ERR_EVENT_STATE_INVALID")
    event["status"] = "OPEN"
    touch(event)
    return object_response(event_out(event))


@bp.route("/adoption-events/<event_id>/close", methods=["POST"])
def close_event(event_id):
    _, role = require_auth()
    require_role(role, ["StoreClerk"])
    event = lookup("adoption_events", event_id)
    if event["status"] != "OPEN":
        raise err("ERR_EVENT_STATE_INVALID")

    # Cascade: return every still-PLACED placement under this event.
    for placement in db.adoption_placements.values():
        if placement["event_id"] != event_id or placement["status"] != "PLACED":
            continue
        placement["status"] = "RETURNED"
        touch(placement)
        event["placed_head"] -= placement["head"]
        batch = db.livestock_batches.get(placement["batch_id"])
        if batch is not None and batch["sale_state"] == "RESERVED":
            batch["sale_state"] = "ON_FLOOR"
            touch(batch)

    event["status"] = "CLOSED"
    touch(event)
    return object_response(event_out(event))


# ---------------------------------------------------------------------------
# AdoptionPlacement
# ---------------------------------------------------------------------------
@bp.route("/adoption-placements", methods=["POST"])
def create_placement():
    _, role = require_auth()
    require_role(role, ["LivestockKeeper"])
    body = get_body()
    event_id = as_str(require_present(body, "event_id"), "event_id")
    batch_id = as_str(require_present(body, "batch_id"), "batch_id")
    event = lookup("adoption_events", event_id)
    batch = lookup("livestock_batches", batch_id)
    head = as_int(require_present(body, "head"), "head")
    if head <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "head must be > 0.")

    # State + safety gates (PRD §3.4).
    if batch["sale_state"] != "ON_FLOOR":
        raise err("ERR_BATCH_SALE_STATE_INVALID")
    if batch["health_state"] != "HEALTHY":
        raise err("ERR_BATCH_NOT_HEALTHY")

    live_head = batch["head_count"] - batch["mortality_count"]
    # Live-head check before capacity check.
    if head > live_head:
        raise err("ERR_INSUFFICIENT_HEAD")
    if event["placed_head"] + head > event["capacity"]:
        raise err("ERR_EVENT_CAPACITY_EXCEEDED")

    record = {
        "event_id": event_id,
        "batch_id": batch_id,
        "head": head,
        "status": "PLACED",
    }
    stamp_create(record)
    db.adoption_placements[record["id"]] = record

    event["placed_head"] += head
    touch(event)

    # Reserve the batch only when the full live head is placed.
    if head == live_head:
        batch["sale_state"] = "RESERVED"
    touch(batch)

    return object_response(placement_out(record), 201)


@bp.route("/adoption-placements", methods=["GET"])
def list_placements():
    _, role = require_auth()
    require_role(role, PLACEMENT_READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.adoption_placements.values())
    for field in ("event_id", "batch_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, total = paginate(records, limit, offset)
    return array_response([placement_out(r) for r in page], limit, offset, total)


@bp.route("/adoption-placements/<placement_id>", methods=["GET"])
def get_placement(placement_id):
    _, role = require_auth()
    require_role(role, PLACEMENT_READ_ROLES)
    record = lookup("adoption_placements", placement_id)
    return object_response(placement_out(record))


@bp.route("/adoption-placements/<placement_id>/return", methods=["POST"])
def return_placement(placement_id):
    _, role = require_auth()
    require_role(role, ["LivestockKeeper"])
    placement = lookup("adoption_placements", placement_id)
    if placement["status"] != "PLACED":
        raise err("ERR_PLACEMENT_NOT_RETURNABLE")

    placement["status"] = "RETURNED"
    event = db.adoption_events.get(placement["event_id"])
    if event is not None:
        event["placed_head"] -= placement["head"]
        touch(event)
    batch = db.livestock_batches.get(placement["batch_id"])
    if batch is not None and batch["sale_state"] == "RESERVED":
        batch["sale_state"] = "ON_FLOOR"
        touch(batch)
    touch(placement)
    return object_response(placement_out(placement))
