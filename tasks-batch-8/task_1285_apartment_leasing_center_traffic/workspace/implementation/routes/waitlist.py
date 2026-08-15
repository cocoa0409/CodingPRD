"""WaitlistEntry endpoints (queue for sold-out floorplans with timed offers)."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import AGENT, PM, auth
from response import ok, ok_list
from services import (
    available_units,
    effective_available_units,
    get_floorplan,
    get_waitlist_entry,
    next_position,
    promote_entry,
    queue_head,
    requeue_entry,
    ser_waitlist_entry,
    sorted_created,
    stamp,
    touch,
)
from util import apply_filters, as_str, body, pagination, required

bp = Blueprint("waitlist", __name__)

STAFF = [PM, AGENT]


@bp.post("/leasing/waitlist-entries")
def create_entry():
    auth(STAFF)
    data = body()
    floorplan_id = as_str(required(data, "floorplan_id"), "floorplan_id")
    contact_name = as_str(required(data, "contact_name"), "contact_name")
    contact_email = as_str(required(data, "contact_email"), "contact_email")
    fp = get_floorplan(floorplan_id)
    if available_units(fp) >= 1:
        raise ApiError(
            "ERR_FLOORPLAN_AVAILABLE",
            409,
            "Waitlist join is only permitted while the floorplan has no available units",
        )
    rec = {
        "id": new_id(),
        "floorplan_id": floorplan_id,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "position": next_position(floorplan_id),
        "offer_expires_at": None,
        "linked_application_id": None,
        "status": "WAITING",
    }
    stamp(rec)
    DB["waitlist_entries"][rec["id"]] = rec
    return ok(ser_waitlist_entry(rec), status=201)


@bp.get("/leasing/waitlist-entries")
def list_entries():
    auth(STAFF)
    limit, offset = pagination()
    items = apply_filters(
        DB["waitlist_entries"].values(),
        [
            ("floorplan_id", "floorplan_id"),
            ("status", "status"),
            ("linked_application_id", "linked_application_id"),
        ],
    )
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_waitlist_entry(e) for e in items[offset : offset + limit]],
        total,
        limit,
        offset,
    )


@bp.get("/leasing/waitlist-entries/<eid>")
def get_one_entry(eid):
    auth(STAFF)
    return ok(ser_waitlist_entry(get_waitlist_entry(eid)))


@bp.post("/leasing/waitlist-entries/<eid>/promote")
def promote(eid):
    auth(STAFF)
    entry = get_waitlist_entry(eid)
    if entry["status"] != "WAITING":
        raise ApiError(
            "ERR_WAITLIST_INVALID_STATE", 409, "Only a WAITING entry can be promoted"
        )
    head = queue_head(entry["floorplan_id"])
    if head is None or head["id"] != entry["id"]:
        raise ApiError(
            "ERR_NOT_QUEUE_HEAD",
            409,
            "Only the WAITING queue head (position ASC, created_at ASC) can be promoted",
        )
    fp = DB["floorplans"][entry["floorplan_id"]]
    if effective_available_units(fp) < 1:
        raise ApiError(
            "ERR_NO_UNITS_TO_OFFER",
            409,
            "No effective availability to offer (available minus OFFERED is zero)",
        )
    promote_entry(entry)
    return ok(ser_waitlist_entry(entry))


@bp.post("/leasing/waitlist-entries/<eid>/decline")
def decline(eid):
    auth(STAFF)
    entry = get_waitlist_entry(eid)
    if entry["status"] != "OFFERED":
        raise ApiError(
            "ERR_WAITLIST_INVALID_STATE", 409, "Only an OFFERED entry can be declined"
        )
    requeue_entry(entry)
    return ok(ser_waitlist_entry(entry))


@bp.post("/leasing/waitlist-entries/<eid>/cancel")
def cancel_entry(eid):
    auth(STAFF)
    entry = get_waitlist_entry(eid)
    if entry["status"] not in ("WAITING", "OFFERED"):
        raise ApiError(
            "ERR_WAITLIST_INVALID_STATE",
            409,
            "Only a WAITING or OFFERED entry can be cancelled",
        )
    if entry["status"] == "OFFERED":
        entry["offer_expires_at"] = None
    entry["status"] = "CANCELLED"
    touch(entry)
    return ok(ser_waitlist_entry(entry))
