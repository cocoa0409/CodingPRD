"""ShuttleRoute and ShuttleTrip endpoints, plus service-level reporting."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from db import parse_dt, touch
from domain import (
    get_or_404, serialize_route, serialize_trip, round_half_up_2,
)
from errors import raise_error
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("routes_trips", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/parking/routes", methods=["POST"])
def create_route():
    require_roles("ShuttleDispatcher")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("lot_id", "code", "headway_target_minutes", "operating_cost_per_trip_cents"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    lot = get_or_404(db.lots, body["lot_id"])
    headway = body["headway_target_minutes"]
    if not isinstance(headway, int) or isinstance(headway, bool) or headway <= 0:
        raise_error("ERR_INVALID_REQUEST", "headway_target_minutes must be > 0")
    cost = body["operating_cost_per_trip_cents"]
    if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
        raise_error("ERR_INVALID_REQUEST", "operating_cost_per_trip_cents must be >= 0")
    # code unique within the lot's program
    for r in db.routes.values():
        r_lot = db.lots.get(r["lot_id"])
        if r_lot and r_lot["program_id"] == lot["program_id"] and r["code"] == body["code"]:
            raise_error("ERR_INVALID_REQUEST", "route code already used in this program")
    rec = db.new_record({
        "lot_id": lot["id"],
        "code": body["code"],
        "headway_target_minutes": headway,
        "operating_cost_per_trip_cents": cost,
        "status": "ACTIVE",
    })
    db.routes[rec["id"]] = rec
    return success_object(serialize_route(rec), 201)


@bp.route("/parking/routes/<rid>", methods=["GET"])
def get_route(rid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.routes, rid)
    return success_object(serialize_route(rec), 200)


@bp.route("/parking/routes", methods=["GET"])
def list_routes():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    items = sorted(db.routes.values(), key=lambda r: r["created_at"])
    out = []
    for r in items:
        if lot_id is not None and r["lot_id"] != lot_id:
            continue
        if status is not None and r["status"] != status:
            continue
        out.append(serialize_route(r))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/routes/<rid>/events", methods=["POST"])
def route_event(rid):
    require_roles("ShuttleDispatcher")
    route = get_or_404(db.routes, rid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    event_type = body.get("event_type")
    if event_type not in ("SUSPEND", "RESUME"):
        raise_error("ERR_INVALID_REQUEST", "invalid event_type")
    if event_type == "SUSPEND":
        if route["status"] != "ACTIVE":
            raise_error("ERR_INVALID_STATE", "SUSPEND requires the route to be ACTIVE")
        route["status"] = "SUSPENDED"
        touch(route)
        # Per PRD §3.8: trips are NOT cancelled on suspension.
    else:
        if route["status"] != "SUSPENDED":
            raise_error("ERR_INVALID_STATE", "RESUME requires the route to be SUSPENDED")
        route["status"] = "ACTIVE"
        touch(route)
    return success_object(serialize_route(route), 200)


@bp.route("/parking/routes/<rid>/service-level", methods=["GET"])
def service_level(rid):
    require_roles(*ALL_ROLES)
    route = get_or_404(db.routes, rid)
    window_start = parse_dt(request.args.get("window_start"))
    window_end = parse_dt(request.args.get("window_end"))
    mode = request.args.get("mode")
    if window_start is None or window_end is None:
        raise_error("ERR_INVALID_REQUEST", "window_start and window_end must be valid ISO datetimes")
    if mode not in ("SCHEDULED", "OBSERVED"):
        raise_error("ERR_INVALID_REQUEST", "mode must be SCHEDULED or OBSERVED")
    participants = []
    for t in db.trips.values():
        if t["route_id"] != route["id"]:
            continue
        sched = parse_dt(t["scheduled_departure_at"])
        if sched is None or not (window_start <= sched <= window_end):
            continue
        if mode == "SCHEDULED":
            participants.append((sched, t["created_at"]))
        else:
            actual = parse_dt(t["actual_departure_at"]) if t.get("actual_departure_at") else None
            if actual is not None and t["status"] in ("DEPARTED", "COMPLETED"):
                participants.append((actual, t["created_at"]))
    participants.sort(key=lambda x: (x[0], x[1]))
    trip_count = len(participants)
    if trip_count < 2:
        return success_object({
            "max_gap_minutes": None,
            "expected_wait_minutes": None,
            "sla_compliant": None,
            "trip_count": trip_count,
        }, 200)
    gaps = []
    for i in range(1, trip_count):
        delta = participants[i][0] - participants[i - 1][0]
        gaps.append(int(delta.total_seconds() // 60))
    max_gap = max(gaps)
    mean_gap = Decimal(sum(gaps)) / Decimal(len(gaps))
    expected_wait = round_half_up_2(mean_gap / Decimal(2))
    sla_compliant = max_gap <= 2 * route["headway_target_minutes"]
    return success_object({
        "max_gap_minutes": max_gap,
        "expected_wait_minutes": expected_wait,
        "sla_compliant": sla_compliant,
        "trip_count": trip_count,
    }, 200)


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------

@bp.route("/parking/trips", methods=["POST"])
def create_trip():
    require_roles("ShuttleDispatcher")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("route_id", "scheduled_departure_at"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    route = get_or_404(db.routes, body["route_id"])
    sched = parse_dt(body["scheduled_departure_at"])
    if sched is None:
        raise_error("ERR_INVALID_REQUEST", "scheduled_departure_at must be a valid ISO datetime")
    # spacing: >= 5 minutes among non-CANCELLED trips on the route; exactly 5 is acceptable
    for t in db.trips.values():
        if t["route_id"] == route["id"] and t["status"] != "CANCELLED":
            other = parse_dt(t["scheduled_departure_at"])
            if other is not None and abs((sched - other).total_seconds()) < 5 * 60:
                raise_error("ERR_TRIP_SPACING_CONFLICT",
                            "New trip within 5 minutes of an existing non-CANCELLED trip")
    rec = db.new_record({
        "route_id": route["id"],
        "scheduled_departure_at": body["scheduled_departure_at"],
        "actual_departure_at": None,
        "status": "SCHEDULED",
        "boarded_count": 0,
    })
    db.trips[rec["id"]] = rec
    return success_object(serialize_trip(rec), 201)


@bp.route("/parking/trips/<tid>", methods=["GET"])
def get_trip(tid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.trips, tid)
    return success_object(serialize_trip(rec), 200)


@bp.route("/parking/trips", methods=["GET"])
def list_trips():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    route_id = request.args.get("route_id")
    status = request.args.get("status")
    items = sorted(db.trips.values(), key=lambda t: t["created_at"])
    out = []
    for t in items:
        if route_id is not None and t["route_id"] != route_id:
            continue
        if status is not None and t["status"] != status:
            continue
        out.append(serialize_trip(t))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/trips/<tid>/events", methods=["POST"])
def trip_event(tid):
    require_roles("ShuttleDispatcher")
    trip = get_or_404(db.trips, tid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    event_type = body.get("event_type")
    if event_type not in ("DEPART", "COMPLETE", "CANCEL"):
        raise_error("ERR_INVALID_REQUEST", "invalid event_type")
    if event_type == "DEPART":
        if trip["status"] != "SCHEDULED":
            raise_error("ERR_INVALID_STATE", "DEPART requires the trip to be SCHEDULED")
        route = db.routes.get(trip["route_id"])
        if route is None or route["status"] != "ACTIVE":
            raise_error("ERR_ROUTE_NOT_ACTIVE", "Route is not ACTIVE")
        from db import fmt_dt, now
        trip["actual_departure_at"] = fmt_dt(now())
        trip["status"] = "DEPARTED"
        touch(trip)
    elif event_type == "COMPLETE":
        if trip["status"] != "DEPARTED":
            raise_error("ERR_INVALID_STATE", "COMPLETE requires the trip to be DEPARTED")
        boarded = body.get("boarded_count", 0)
        if not isinstance(boarded, int) or isinstance(boarded, bool) or boarded < 0:
            raise_error("ERR_INVALID_REQUEST", "boarded_count must be >= 0")
        trip["boarded_count"] = boarded
        trip["status"] = "COMPLETED"
        touch(trip)
    else:  # CANCEL
        if trip["status"] not in ("SCHEDULED", "DEPARTED"):
            raise_error("ERR_INVALID_STATE", "CANCEL requires SCHEDULED or DEPARTED")
        trip["status"] = "CANCELLED"
        touch(trip)
    return success_object(serialize_trip(trip), 200)
