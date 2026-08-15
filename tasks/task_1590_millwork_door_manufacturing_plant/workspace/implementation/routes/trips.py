"""DeliveryTrip endpoints (PRD §3.7): manifest building, dispatch lifecycle, fill figures."""

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_int, require_existence)
from response import success, list_response, parse_pagination
from services import fill

bp = Blueprint("trips", __name__)

TRIP_STATUSES = ("PLANNED", "DEPARTED", "DELIVERED", "CLOSED", "CANCELLED")


def serialize(t):
    return {
        "id": t["id"],
        "project_id": t["project_id"],
        "trip_code": t["trip_code"],
        "truck_capacity_leaves": t["truck_capacity_leaves"],
        "departure_date": t["departure_date"],
        "site_arrival_date": t["site_arrival_date"],
        "leaves_committed": t["leaves_committed"],
        "projected_fill_pct": fill.compute_projected_fill(t),
        "realized_fill_pct": t["realized_fill_pct"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _assigned_openings(trip_id):
    return [o for o in db.openings.values() if o.get("assigned_trip_id") == trip_id]


def _recompute_leaves(trip):
    trip["leaves_committed"] = sum(
        o["leaf_count"] for o in db.openings.values()
        if o.get("assigned_trip_id") == trip["id"] and o["ship_status"] == "SCHEDULED"
    )


@bp.post("/delivery-trips")
def create_trip():
    _, role = get_context()
    require_role(role, "PlantManager")
    body = raw_body()
    # Rung 3: body FK existence.
    if body.get("project_id") is not None:
        project = require_existence(db.projects, body["project_id"],
                                    "ERR_PROJECT_NOT_FOUND", "Project")
    else:
        project = None
    # Rung 4: payload, including the structural date rule.
    validate_fields(body, required=("project_id", "trip_code", "truck_capacity_leaves",
                                    "departure_date", "site_arrival_date"))
    trip_code = req_string(body, "trip_code")
    capacity = req_int(body, "truck_capacity_leaves")
    departure_date = req_string(body, "departure_date")
    site_arrival_date = req_string(body, "site_arrival_date")
    if site_arrival_date < departure_date:
        raise err("ERR_INVALID_TRIP_DATES", "site_arrival_date earlier than departure_date")
    # Rung 6: project must be OPEN.
    if project["status"] != "OPEN":
        raise err("ERR_PROJECT_NOT_OPEN", "Trip planning requires Project.status == OPEN")
    rec = db.new_record()
    rec.update({
        "project_id": project["id"],
        "trip_code": trip_code,
        "truck_capacity_leaves": capacity,
        "departure_date": departure_date,
        "site_arrival_date": site_arrival_date,
        "leaves_committed": 0,
        "realized_fill_pct": None,
        "status": "PLANNED",
    })
    db.delivery_trips[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/delivery-trips")
def list_trips():
    get_context()
    limit, offset = parse_pagination(request.args)
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    items = [t for t in db.delivery_trips.values()
             if (project_id is None or t["project_id"] == project_id)
             and (status is None or t["status"] == status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/delivery-trips/<tid>")
def get_trip(tid):
    get_context()
    trip = require_existence(db.delivery_trips, tid, "ERR_TRIP_NOT_FOUND", "DeliveryTrip")
    return success(serialize(trip))


@bp.post("/delivery-trips/<tid>/assign")
def assign_opening(tid):
    _, role = get_context()
    require_role(role, "ShippingCoordinator")
    trip = require_existence(db.delivery_trips, tid, "ERR_TRIP_NOT_FOUND", "DeliveryTrip")
    body = raw_body()
    if body.get("opening_id") is not None:
        opening = require_existence(db.openings, body["opening_id"],
                                    "ERR_OPENING_NOT_FOUND", "Opening")
    else:
        opening = None
    validate_fields(body, required=("opening_id",))
    # Rung 6: state gates in the declared order.
    if trip["status"] != "PLANNED":
        raise err("ERR_INVALID_TRIP_STATUS_TRANSITION",
                  "Assign requires trip PLANNED, not %s" % trip["status"])
    if opening["fab_status"] != "STAGED":
        raise err("ERR_OPENING_NOT_STAGED", "Assign requires opening fab STAGED")
    if opening["ship_status"] != "UNSCHEDULED":
        raise err("ERR_OPENING_ALREADY_SCHEDULED", "Assign requires opening ship UNSCHEDULED")
    # Rung 9 (referential): the opening's order must belong to the trip's project.
    order = db.orders.get(opening["order_id"])
    if order is None or order["project_id"] != trip["project_id"]:
        raise err("ERR_TRIP_PROJECT_MISMATCH",
                  "Opening's order belongs to a different project than the trip")
    # Rung 10 (temporal): jobsite arrival must not fall after the required date.
    if trip["site_arrival_date"] > opening["required_on_site_date"]:
        raise err("ERR_DELIVERY_WINDOW_MISSED",
                  "Trip arrival falls after the opening's required_on_site_date")
    # Rung 11 (fiscal): truck capacity — an exact fit is permitted.
    if trip["leaves_committed"] + opening["leaf_count"] > trip["truck_capacity_leaves"]:
        raise err("ERR_TRUCK_CAPACITY_EXCEEDED", "Truck capacity would be exceeded")
    opening["ship_status"] = "SCHEDULED"
    opening["assigned_trip_id"] = trip["id"]
    db.touch(opening)
    _recompute_leaves(trip)
    db.touch(trip)
    return success(serialize(trip))


@bp.post("/delivery-trips/<tid>/unassign")
def unassign_opening(tid):
    _, role = get_context()
    require_role(role, "ShippingCoordinator")
    trip = require_existence(db.delivery_trips, tid, "ERR_TRIP_NOT_FOUND", "DeliveryTrip")
    body = raw_body()
    if body.get("opening_id") is not None:
        opening = require_existence(db.openings, body["opening_id"],
                                    "ERR_OPENING_NOT_FOUND", "Opening")
    else:
        opening = None
    validate_fields(body, required=("opening_id",))
    if trip["status"] != "PLANNED":
        raise err("ERR_INVALID_TRIP_STATUS_TRANSITION",
                  "Unassign requires trip PLANNED, not %s" % trip["status"])
    if opening.get("assigned_trip_id") != trip["id"]:
        raise err("ERR_OPENING_NOT_ON_TRIP", "Opening is not assigned to this trip")
    opening["ship_status"] = "UNSCHEDULED"
    opening["assigned_trip_id"] = None
    db.touch(opening)
    _recompute_leaves(trip)
    db.touch(trip)
    return success(serialize(trip))


@bp.put("/delivery-trips/<tid>/status")
def transition_trip(tid):
    _, role = get_context()
    require_role(role, "ShippingCoordinator")
    trip = require_existence(db.delivery_trips, tid, "ERR_TRIP_NOT_FOUND", "DeliveryTrip")
    body = raw_body()
    validate_fields(body, required=("target_status",))
    target = req_string(body, "target_status")
    current = trip["status"]

    if target == "DEPARTED":
        if current != "PLANNED":
            raise err("ERR_INVALID_TRIP_STATUS_TRANSITION",
                      "Trip cannot transition from %s to DEPARTED" % current)
        assigned = _assigned_openings(tid)
        if not assigned:
            raise err("ERR_NO_OPENINGS_ASSIGNED", "Departure requires at least one assigned opening")
        for opening in assigned:
            if opening["fab_status"] != "STAGED":
                raise err("ERR_OPENINGS_NOT_STAGED",
                          "Every assigned opening must be fab STAGED")
        for opening in assigned:
            opening["ship_status"] = "SHIPPED"
            db.touch(opening)
        trip["realized_fill_pct"] = fill.compute_realized_fill(trip)
        trip["status"] = "DEPARTED"

    elif target == "DELIVERED":
        if current != "DEPARTED":
            raise err("ERR_INVALID_TRIP_STATUS_TRANSITION",
                      "Trip cannot transition from %s to DELIVERED" % current)
        for opening in _assigned_openings(tid):
            opening["ship_status"] = "DELIVERED"
            db.touch(opening)
        trip["status"] = "DELIVERED"

    elif target == "CLOSED":
        if current != "DELIVERED":
            raise err("ERR_INVALID_TRIP_STATUS_TRANSITION",
                      "Trip cannot transition from %s to CLOSED" % current)
        for opening in _assigned_openings(tid):
            if opening["ship_status"] != "ACCEPTED":
                raise err("ERR_OPENINGS_NOT_ACCEPTED",
                          "Every assigned opening must be ACCEPTED")
        trip["status"] = "CLOSED"

    elif target == "CANCELLED":
        if current != "PLANNED":
            raise err("ERR_INVALID_TRIP_STATUS_TRANSITION",
                      "Trip cannot transition from %s to CANCELLED" % current)
        for opening in _assigned_openings(tid):
            opening["ship_status"] = "UNSCHEDULED"
            opening["assigned_trip_id"] = None
            db.touch(opening)
        trip["leaves_committed"] = 0
        trip["status"] = "CANCELLED"

    elif target in TRIP_STATUSES:
        raise err("ERR_INVALID_TRIP_STATUS_TRANSITION",
                  "Trip cannot transition from %s to %s" % (current, target))
    else:
        raise err("ERR_INVALID_TRIP_STATUS_TRANSITION",
                  "Unknown trip status: %s" % target)

    db.touch(trip)
    return success(serialize(trip))
