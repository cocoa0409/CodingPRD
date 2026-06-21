"""Route and RouteStop routes (PRD §3.6). OCC-guarded scheduling."""
from flask import Blueprint, request

from db import db, LOCK, stamp_new, touch
import domain
import errors
import lookups
from domain import serialize, MAX_STOPS_PER_ROUTE
from errors import fail
from listing import list_response
from middleware import get_auth, require_role
from response import success
from validation import get_body, require_str, require_int

bp = Blueprint("routing", __name__)


# ---------------- Route ----------------
@bp.route("/routes", methods=["POST"])
def create_route():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        technician_id = require_str(body, "technician_id")
        lookups.get_technician(technician_id)
        route_date = require_str(body, "route_date")
        rec = {
            "technician_id": technician_id,
            "route_date": route_date,
            "route_state": "PLANNING",
            "stops_used": 0,
            "minutes_committed": 0,
        }
        stamp_new(rec)
        db.routes[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician"})
    with LOCK:
        rec = lookups.get_route(rid)
        return success(serialize(rec), status=200)


@bp.route("/routes", methods=["GET"])
def list_routes():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician"})
    with LOCK:
        rows = list(db.routes.values())
        technician_id = request.args.get("technician_id")
        if technician_id is not None:
            rows = [r for r in rows if r["technician_id"] == technician_id]
        return list_response(rows)


@bp.route("/routes/<rid>/dispatch", methods=["POST"])
def dispatch_route(rid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        route = lookups.get_route(rid)
        # State (priority 5)
        if route["route_state"] != "PLANNING":
            fail(errors.ERR_ROUTE_NOT_PLANNING, "Route is not in PLANNING")
        # Empty-route guard (priority 14)
        if route["stops_used"] < 1:
            fail(errors.ERR_EMPTY_ROUTE, "Route has no scheduled stops")
        route["route_state"] = "DISPATCHED"
        touch(route)
        return success(serialize(route), status=200)


@bp.route("/routes/<rid>/close", methods=["POST"])
def close_route(rid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        route = lookups.get_route(rid)
        if route["route_state"] != "DISPATCHED":
            fail(errors.ERR_ROUTE_NOT_DISPATCHED, "Route is not DISPATCHED")
        route["route_state"] = "CLOSED"
        touch(route)
        return success(serialize(route), status=200)


# ---------------- RouteStop ----------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open intervals [start, end) overlap iff a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


@bp.route("/route-stops", methods=["POST"])
def create_route_stop():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        # Existence (priority 3), left-to-right: route_id then work_order_id.
        route_id = require_str(body, "route_id")
        route = lookups.get_route(route_id)
        work_order_id = require_str(body, "work_order_id")
        wo = lookups.get_workorder(work_order_id)

        # State preconditions (priority 5) come before generic field validation
        # (priority 99): route PLANNING, then WO PENDING, then WO UNSCHEDULED.
        if route["route_state"] != "PLANNING":
            fail(errors.ERR_ROUTE_NOT_PLANNING, "Route is not in PLANNING")
        if wo["completion_status"] != "PENDING":
            fail(errors.ERR_WORKORDER_NOT_PENDING, "Work order is not PENDING")
        if wo["dispatch_status"] != "UNSCHEDULED":
            fail(errors.ERR_WORKORDER_ALREADY_SCHEDULED, "Work order is already scheduled")

        # Field shapes needed for the business gates below.
        arrival_start_sec = require_int(body, "arrival_start_sec", minimum=0, maximum=86399)
        window_minutes = require_int(body, "window_minutes", minimum=1)
        expected_route_version = require_int(body, "expected_route_version")

        # OCC (priority 6): expected_route_version must equal Route.version.
        if expected_route_version != route["version"]:
            fail(errors.ERR_STALE_ROUTE_VERSION, "Route version is stale")

        # Season gate (priority 9): STARTUP requires system.season_state == WINTERIZED.
        if wo["job_type"] == "STARTUP":
            system = db.irrigation_systems.get(wo["system_id"])
            if system is None or system["season_state"] != "WINTERIZED":
                fail(errors.ERR_SEASON_STATE_BLOCKS_STARTUP, "System is not WINTERIZED")

        # Temporal overlap (priority 11): half-open window vs other SCHEDULED stops on this route.
        new_start = arrival_start_sec
        new_end = arrival_start_sec + window_minutes * 60
        for rs in db.route_stops.values():
            if rs["route_id"] != route_id or rs["stop_state"] != "SCHEDULED":
                continue
            ex_start = rs["arrival_start_sec"]
            ex_end = rs["arrival_start_sec"] + rs["window_minutes"] * 60
            if _intervals_overlap(new_start, new_end, ex_start, ex_end):
                fail(errors.ERR_ROUTESTOP_TIME_OVERLAP, "Stop window overlaps an existing scheduled stop")

        # Capacity (priority 12): prospective stop count and committed minutes.
        prospective_stops = route["stops_used"] + 1
        prospective_minutes = route["minutes_committed"] + window_minutes
        tech = db.technicians.get(route["technician_id"])
        shift_minutes = (tech["shift_end_sec"] - tech["shift_start_sec"]) // 60 if tech else 0
        if prospective_stops > MAX_STOPS_PER_ROUTE or prospective_minutes > shift_minutes:
            fail(errors.ERR_ROUTE_CAPACITY_EXCEEDED, "Route capacity exceeded")

        # Accept the stop.
        rec = {
            "route_id": route_id,
            "work_order_id": work_order_id,
            "arrival_start_sec": arrival_start_sec,
            "window_minutes": window_minutes,
            "stop_state": "SCHEDULED",
        }
        stamp_new(rec)
        db.route_stops[rec["id"]] = rec

        # Side effects: WO dispatch_status -> SCHEDULED, assign technician.
        wo["dispatch_status"] = "SCHEDULED"
        wo["assigned_technician_id"] = route["technician_id"]
        touch(wo)

        # Route stops_used / minutes_committed recomputed; version +1.
        # recompute_route_derived bumps version when the counts change; this add
        # always changes them, so the version advances by exactly one.
        domain.recompute_route_derived(route)

        return success(serialize(rec), status=201)


@bp.route("/route-stops/<rsid>", methods=["GET"])
def get_route_stop(rsid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician"})
    with LOCK:
        rec = lookups.get_route_stop(rsid)
        return success(serialize(rec), status=200)


@bp.route("/route-stops", methods=["GET"])
def list_route_stops():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician"})
    with LOCK:
        rows = list(db.route_stops.values())
        route_id = request.args.get("route_id")
        work_order_id = request.args.get("work_order_id")
        if route_id is not None:
            rows = [rs for rs in rows if rs["route_id"] == route_id]
        if work_order_id is not None:
            rows = [rs for rs in rows if rs["work_order_id"] == work_order_id]
        return list_response(rows)
