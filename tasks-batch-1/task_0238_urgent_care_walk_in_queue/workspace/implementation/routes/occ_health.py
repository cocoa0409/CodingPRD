"""Occupational-health order endpoints (PRD §3.8)."""
from flask import Blueprint, request

import clock
import serialize
from db import db, stamp_create, touch
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from util import parse_iso, add_minutes
from validation import get_json_body, parse_pagination, paginate, require_str

from routes.lookup import get_path, get_fk

bp = Blueprint("occ_health", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "Provider"]
ORDER_TYPES = {"DRUG_SCREEN", "PHYSICAL", "RESPIRATOR_FIT"}
ROOM_REQUIRED_TYPES = {"PHYSICAL", "RESPIRATOR_FIT"}
RESULT_VALUES = {"NEGATIVE", "POSITIVE", "PASS", "FAIL"}
CLEAN_BUFFER_MINUTES = 15
ACTIVE_OCC_STATES = {"SCHEDULED", "IN_PROGRESS"}


@bp.route("/occ-health-orders", methods=["POST"])
def create_occ_order():
    authorize(["FrontDeskClerk", "ClinicManager"])
    body = get_json_body()

    # FK resolution (P11): queue_entry, collector, room (if present).
    qe_id = body.get("queue_entry_id")
    collector_id = body.get("collector_id")
    if qe_id is None or collector_id is None:
        raise err("ERR_INVALID_REQUEST", "queue_entry_id and collector_id required")
    qe = get_fk("queue_entry", qe_id)
    collector = get_fk("provider", collector_id)
    room_id = body.get("room_id")
    room = None
    if room_id is not None:
        room = get_fk("exam_room", room_id)

    # Well-formedness (P20).
    order_type = body.get("order_type")
    if order_type not in ORDER_TYPES:
        raise err("ERR_INVALID_REQUEST", "invalid order_type")
    require_str(body, "employer_name")
    scheduled_start = parse_iso(body.get("scheduled_start"))
    if scheduled_start is None:
        raise err("ERR_INVALID_REQUEST", "scheduled_start must be ISO 8601")
    duration = body.get("duration_minutes", 30)
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 5:
        raise err("ERR_INVALID_REQUEST", "duration_minutes must be an integer >= 5")

    new_start = scheduled_start
    new_end = add_minutes(scheduled_start, duration)

    # P45 collector half-open overlap.
    for o in db.occ_health_orders.values():
        if o["collector_id"] != collector["id"]:
            continue
        if o["status"] not in ACTIVE_OCC_STATES:
            continue
        ex_start = o["scheduled_start"]
        ex_end = add_minutes(ex_start, o["duration_minutes"])
        if new_start < ex_end and ex_start < new_end:
            raise err("ERR_SLOT_CONFLICT", "collector slot conflict")

    # P48 room buffer-padded closed overlap (only when room_id set).
    if room is not None:
        for o in db.occ_health_orders.values():
            if o.get("room_id") != room["id"]:
                continue
            if o["status"] not in ACTIVE_OCC_STATES:
                continue
            ex_start = o["scheduled_start"]
            ex_end = add_minutes(ex_start, o["duration_minutes"])
            if (new_start < add_minutes(ex_end, CLEAN_BUFFER_MINUTES)
                    and ex_start < add_minutes(new_end, CLEAN_BUFFER_MINUTES)):
                raise err("ERR_ROOM_SLOT_CONFLICT", "room slot conflict")

    # P49 room requirement rule.
    if order_type in ROOM_REQUIRED_TYPES and room_id is None:
        raise err("ERR_OCC_ROOM_REQUIRED", "%s requires room_id" % order_type)
    if order_type == "DRUG_SCREEN" and room_id is not None:
        raise err("ERR_OCC_ROOM_REQUIRED", "DRUG_SCREEN must omit room_id")

    order = stamp_create({
        "queue_entry_id": qe["id"],
        "order_type": order_type,
        "employer_name": body["employer_name"],
        "scheduled_start": scheduled_start,
        "duration_minutes": duration,
        "collector_id": collector["id"],
        "room_id": room_id,
        "result": "PENDING",
        "status": "SCHEDULED",
    })
    db.occ_health_orders[order["id"]] = order
    return ok_object(serialize.occ_health_order(order), 201)


@bp.route("/occ-health-orders", methods=["GET"])
def list_occ_orders():
    authorize(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.occ_health_orders.values())
    for key in ("queue_entry_id", "collector_id", "room_id"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.occ_health_order(o) for o in page], limit, offset, len(items))


@bp.route("/occ-health-orders/<oid>", methods=["GET"])
def get_occ_order(oid):
    authorize(READ_ROLES)
    order = get_path("occ_health_order", oid)
    return ok_object(serialize.occ_health_order(order))


@bp.route("/occ-health-orders/<oid>/start", methods=["POST"])
def start_occ_order(oid):
    authorize(["Provider"])
    order = get_path("occ_health_order", oid)
    if order["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "order not SCHEDULED")
    if clock.now() < order["scheduled_start"]:
        raise err("ERR_INVALID_STATE", "current clock before scheduled_start")
    order["status"] = "IN_PROGRESS"
    touch(order)
    return ok_object(serialize.occ_health_order(order))


@bp.route("/occ-health-orders/<oid>/result", methods=["POST"])
def result_occ_order(oid):
    authorize(["Provider"])
    order = get_path("occ_health_order", oid)
    body = get_json_body()
    result = body.get("result")
    if result not in RESULT_VALUES:
        raise err("ERR_INVALID_REQUEST", "invalid result")
    if order["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "order not IN_PROGRESS")

    order["result"] = result
    order["status"] = "COMPLETED"
    touch(order)

    # Cascade: create an OCC_HEALTH charge on any Visit for the same queue entry.
    visit = _visit_for_queue_entry(order["queue_entry_id"])
    if visit is not None:
        charge = stamp_create({
            "visit_id": visit["id"],
            "cpt_code": "OCC_%s" % order["order_type"],
            "amount_cents": 1,
            "source_type": "OCC_HEALTH",
            "voided": False,
        })
        db.charges[charge["id"]] = charge

    return ok_object(serialize.occ_health_order(order))


@bp.route("/occ-health-orders/<oid>/cancel", methods=["POST"])
def cancel_occ_order(oid):
    authorize(["FrontDeskClerk", "ClinicManager", "Provider"])
    order = get_path("occ_health_order", oid)
    if order["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "order not SCHEDULED or IN_PROGRESS")
    order["status"] = "CANCELLED"
    touch(order)
    return ok_object(serialize.occ_health_order(order))


def _visit_for_queue_entry(qe_id):
    for v in db.visits.values():
        if v["queue_entry_id"] == qe_id:
            return v
    return None
