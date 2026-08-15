"""Opening endpoints (PRD §3.2, fab axis and ship-axis acceptance)."""

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_enum, req_int, req_number, require_existence)
from response import success, list_response, parse_pagination

bp = Blueprint("openings", __name__)

FIRE_RATINGS = ("NONE", "MIN_20", "MIN_45", "MIN_90")
RATING_RANK = {"NONE": 0, "MIN_20": 1, "MIN_45": 2, "MIN_90": 3}
FAB_STATUSES = ("QUEUED", "MACHINED", "FINISHED", "LABELED", "STAGED", "REWORK", "CANCELLED")
OPEN_PUNCH_STATES = ("REPORTED", "TRIAGED", "REWORK_AUTHORIZED", "IN_REWORK", "RESOLVED")


def serialize(o):
    return {
        "id": o["id"],
        "order_id": o["order_id"],
        "opening_no": o["opening_no"],
        "width_in": o["width_in"],
        "height_in": o["height_in"],
        "leaf_count": o["leaf_count"],
        "fire_rating": o["fire_rating"],
        "required_on_site_date": o["required_on_site_date"],
        "fab_status": o["fab_status"],
        "ship_status": o["ship_status"],
        "assigned_trip_id": o["assigned_trip_id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


@bp.post("/openings")
def create_opening():
    _, role = get_context()
    require_role(role, "Estimator")
    body = raw_body()
    # Rung 3: body FK existence.
    if body.get("order_id") is not None:
        order = require_existence(db.orders, body["order_id"], "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    else:
        order = None
    # Rung 4: payload well-formedness.
    validate_fields(body,
                    required=("order_id", "opening_no", "width_in", "height_in",
                              "fire_rating", "required_on_site_date"),
                    optional=("leaf_count",))
    opening_no = req_string(body, "opening_no")
    width_in = req_number(body, "width_in")
    height_in = req_number(body, "height_in")
    fire_rating = req_enum(body, "fire_rating", FIRE_RATINGS)
    required_on_site_date = req_string(body, "required_on_site_date")
    leaf_count = body.get("leaf_count", 1)
    if isinstance(leaf_count, bool) or not isinstance(leaf_count, int):
        raise err("ERR_INVALID_REQUEST", "leaf_count must be an integer")
    # Rung 8: opening_no unique within the order.
    for existing in db.openings.values():
        if existing["order_id"] == order["id"] and existing["opening_no"] == opening_no:
            raise err("ERR_OPENING_NO_NOT_UNIQUE", "opening_no already used within the order")
    # Rung 9: rating rank must not exceed the order's declared maximum.
    if RATING_RANK[fire_rating] > RATING_RANK[order["fire_rating_required"]]:
        raise err("ERR_OPENING_RATING_EXCEEDS_ORDER",
                  "Opening fire_rating exceeds the order's fire_rating_required")
    rec = db.new_record()
    rec.update({
        "order_id": order["id"],
        "opening_no": opening_no,
        "width_in": width_in,
        "height_in": height_in,
        "leaf_count": leaf_count,
        "fire_rating": fire_rating,
        "required_on_site_date": required_on_site_date,
        "fab_status": "QUEUED",
        "ship_status": "UNSCHEDULED",
        "assigned_trip_id": None,
    })
    db.openings[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/openings")
def list_openings():
    get_context()
    limit, offset = parse_pagination(request.args)
    order_id = request.args.get("order_id")
    assigned_trip_id = request.args.get("assigned_trip_id")
    fab_status = request.args.get("fab_status")
    ship_status = request.args.get("ship_status")
    items = [o for o in db.openings.values()
             if (order_id is None or o["order_id"] == order_id)
             and (assigned_trip_id is None or o["assigned_trip_id"] == assigned_trip_id)
             and (fab_status is None or o["fab_status"] == fab_status)
             and (ship_status is None or o["ship_status"] == ship_status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/openings/<oid>")
def get_opening(oid):
    get_context()
    opening = require_existence(db.openings, oid, "ERR_OPENING_NOT_FOUND", "Opening")
    return success(serialize(opening))


@bp.put("/openings/<oid>/status")
def transition_opening(oid):
    _, role = get_context()
    require_role(role, "ProductionLead")
    opening = require_existence(db.openings, oid, "ERR_OPENING_NOT_FOUND", "Opening")
    body = raw_body()
    validate_fields(body, required=("target_fab_status",))
    target = req_string(body, "target_fab_status")
    current = opening["fab_status"]

    if target == "MACHINED":
        if current != "QUEUED":
            raise err("ERR_INVALID_OPENING_STATUS_TRANSITION",
                      "Opening fab cannot transition from %s to MACHINED" % current)
        order = db.orders.get(opening["order_id"])
        if order is None or order["status"] != "IN_PRODUCTION":
            raise err("ERR_ORDER_NOT_IN_PRODUCTION",
                      "Opening machining requires order status IN_PRODUCTION")
        opening["fab_status"] = "MACHINED"

    elif target == "STAGED":
        if current == "FINISHED":
            if opening["fire_rating"] != "NONE":
                raise err("ERR_LABELING_REQUIRED",
                          "Rated openings must pass through LABELED before STAGED")
            opening["fab_status"] = "STAGED"
        elif current == "LABELED":
            verified = any(a for a in db.label_allocations.values()
                           if a["opening_id"] == oid and a["status"] == "VERIFIED")
            if not verified:
                raise err("ERR_LABEL_NOT_VERIFIED",
                          "Staging a LABELED opening requires a VERIFIED allocation")
            opening["fab_status"] = "STAGED"
        else:
            raise err("ERR_INVALID_OPENING_STATUS_TRANSITION",
                      "Opening fab cannot transition from %s to STAGED" % current)

    elif target in FAB_STATUSES:
        raise err("ERR_INVALID_OPENING_STATUS_TRANSITION",
                  "Opening fab cannot transition from %s to %s" % (current, target))
    else:
        raise err("ERR_INVALID_OPENING_STATUS_TRANSITION",
                  "Unknown opening fab status: %s" % target)

    db.touch(opening)
    return success(serialize(opening))


@bp.post("/openings/<oid>/accept")
def accept_opening(oid):
    _, role = get_context()
    require_role(role, "QAInspector")
    opening = require_existence(db.openings, oid, "ERR_OPENING_NOT_FOUND", "Opening")
    body = raw_body()
    validate_fields(body)
    ship = opening["ship_status"]
    if ship not in ("DELIVERED", "PUNCH_LISTED"):
        raise err("ERR_OPENING_NOT_DELIVERED",
                  "Accept requires ship status DELIVERED or PUNCH_LISTED")
    punches = [p for p in db.punch_items.values() if p["opening_id"] == oid]
    if ship == "DELIVERED":
        if any(p["status"] in OPEN_PUNCH_STATES for p in punches):
            raise err("ERR_OPEN_PUNCH_ITEMS", "Opening has open punch items")
    else:  # PUNCH_LISTED
        if any(p["status"] not in ("VERIFIED", "REJECTED_INVALID") for p in punches):
            raise err("ERR_OPEN_PUNCH_ITEMS",
                      "Every punch item must be VERIFIED or REJECTED_INVALID")
        if opening["fab_status"] != "STAGED":
            raise err("ERR_OPENING_NOT_RESTAGED",
                      "Punch-listed opening must be re-staged (fab STAGED) before acceptance")
    opening["ship_status"] = "ACCEPTED"
    db.touch(opening)
    return success(serialize(opening))
