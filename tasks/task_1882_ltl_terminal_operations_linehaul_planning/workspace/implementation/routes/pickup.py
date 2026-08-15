"""Pickup route and pickup stop endpoints (PRD section 3.3)."""
from flask import Blueprint, request

import db
from errors import (err_invalid_request, err_invalid_state,
                    err_route_not_dispatched, err_stop_outside_shift)
from middleware import require_roles
from response import success, success_list
from routes.common import (as_int, as_str, body_json, check_route_completion,
                           get_path, new_record, paginate, resolve_fk,
                           ser_route, ser_stop, touch)
from services.timeutil import parse_date

bp = Blueprint("pickup", __name__)

_READ_ROLES = ("TerminalAdmin", "Dispatcher", "DockSupervisor")


# --- PickupRoute ---------------------------------------------------------------

@bp.route("/ltl/pickup-routes", methods=["POST"])
@require_roles("Dispatcher")
def create_route():
    body = body_json()
    terminal = resolve_fk("terminals", body.get("terminal_id"), "terminal_id")
    route_date = body.get("route_date")
    try:
        parse_date(route_date)
    except (ValueError, TypeError):
        raise err_invalid_request("route_date must be a YYYY-MM-DD date")
    driver_id = as_str(body, "driver_id")
    shift_start = as_int(body, "shift_start_minute", minimum=0, maximum=1439)
    shift_end = as_int(body, "shift_end_minute", minimum=1, maximum=1440)
    if shift_end <= shift_start:
        raise err_invalid_request("shift_end_minute must be strictly greater than shift_start_minute")
    rec = new_record({
        "terminal_id": terminal["id"], "route_date": route_date,
        "driver_id": driver_id,
        "shift_start_minute": shift_start, "shift_end_minute": shift_end,
        "status": "PLANNED",
    })
    db.store["pickup_routes"][rec["id"]] = rec
    return success(ser_route(rec), 201)


@bp.route("/ltl/pickup-routes", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_routes():
    items = list(db.store["pickup_routes"].values())
    for param in ("terminal_id", "route_date", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if str(r.get(param)) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_route(r) for r in page], total, limit, offset)


@bp.route("/ltl/pickup-routes/<routeId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_route(routeId):
    return success(ser_route(get_path("pickup_routes", routeId)))


@bp.route("/ltl/pickup-routes/<routeId>/dispatch", methods=["POST"])
@require_roles("Dispatcher")
def dispatch_route(routeId):
    route = get_path("pickup_routes", routeId)
    if route["status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED route can be dispatched")
    planned_stops = [s for s in db.store["pickup_stops"].values()
                     if s["route_id"] == route["id"] and s["status"] == "PLANNED"]
    if not planned_stops:
        raise err_invalid_state("Dispatch requires at least one PLANNED stop on the route")
    route["status"] = "DISPATCHED"
    touch(route)
    return success(ser_route(route))


@bp.route("/ltl/pickup-routes/<routeId>/recall", methods=["POST"])
@require_roles("Dispatcher")
def recall_route(routeId):
    route = get_path("pickup_routes", routeId)
    if route["status"] != "DISPATCHED":
        raise err_invalid_state("Only a DISPATCHED route can be recalled")
    stops = [s for s in db.store["pickup_stops"].values() if s["route_id"] == route["id"]]
    if any(s["status"] == "ARRIVED" for s in stops):
        raise err_invalid_state("A route with an ARRIVED stop cannot be recalled")
    route["status"] = "RECALLED"
    touch(route)
    for s in stops:
        if s["status"] == "PLANNED":
            s["status"] = "SKIPPED"
            touch(s)
    return success(ser_route(route))


@bp.route("/ltl/pickup-routes/<routeId>/stops", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_route_stops(routeId):
    route = get_path("pickup_routes", routeId)
    items = [s for s in db.store["pickup_stops"].values() if s["route_id"] == route["id"]]
    page, total, limit, offset = paginate(items)
    return success_list([ser_stop(s) for s in page], total, limit, offset)


# --- PickupStop ----------------------------------------------------------------

@bp.route("/ltl/pickup-stops", methods=["POST"])
@require_roles("Dispatcher")
def create_stop():
    body = body_json()
    route = resolve_fk("pickup_routes", body.get("route_id"), "route_id")
    shipment = resolve_fk("shipments", body.get("shipment_id"), "shipment_id")
    # Field type checks needed before the priority-11 window comparison.
    stop_sequence = body.get("stop_sequence")
    if stop_sequence is None or not isinstance(stop_sequence, int) or isinstance(stop_sequence, bool):
        raise err_invalid_request("stop_sequence must be an integer")
    pam = body.get("planned_arrival_minute")
    if pam is None or not isinstance(pam, int) or isinstance(pam, bool):
        raise err_invalid_request("planned_arrival_minute must be an integer")
    # Priority 11: planned arrival inside the shift window, endpoints included.
    if pam < route["shift_start_minute"] or pam > route["shift_end_minute"]:
        raise err_stop_outside_shift()
    # Priority 20: remaining ranges.
    if stop_sequence < 1:
        raise err_invalid_request("stop_sequence must be >= 1")
    rec = new_record({
        "route_id": route["id"], "shipment_id": shipment["id"],
        "stop_sequence": stop_sequence, "planned_arrival_minute": pam,
        "status": "PLANNED",
    })
    db.store["pickup_stops"][rec["id"]] = rec
    return success(ser_stop(rec), 201)


@bp.route("/ltl/pickup-stops", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_stops():
    items = list(db.store["pickup_stops"].values())
    for param in ("route_id", "shipment_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_stop(s) for s in page], total, limit, offset)


@bp.route("/ltl/pickup-stops/<stopId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_stop(stopId):
    return success(ser_stop(get_path("pickup_stops", stopId)))


@bp.route("/ltl/pickup-stops/<stopId>/arrive", methods=["POST"])
@require_roles("Dispatcher")
def arrive_stop(stopId):
    stop = get_path("pickup_stops", stopId)
    if stop["status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED stop can be marked arrived")
    route = db.store["pickup_routes"][stop["route_id"]]
    # Priority 17: the route must be DISPATCHED.
    if route["status"] != "DISPATCHED":
        raise err_route_not_dispatched()
    stop["status"] = "ARRIVED"
    touch(stop)
    return success(ser_stop(stop))


@bp.route("/ltl/pickup-stops/<stopId>/complete", methods=["POST"])
@require_roles("Dispatcher")
def complete_stop(stopId):
    stop = get_path("pickup_stops", stopId)
    if stop["status"] != "ARRIVED":
        raise err_invalid_state("Only an ARRIVED stop can be completed")
    shipment = db.store["shipments"][stop["shipment_id"]]
    if shipment["handling_status"] != "TENDERED":
        raise err_invalid_state("Pickup completion requires the shipment to be TENDERED")
    stop["status"] = "PICKED_UP"
    touch(stop)
    shipment["handling_status"] = "ON_DOCK"
    touch(shipment)
    # The bubble-up route-completion check runs when a stop leaves PLANNED
    # into SKIPPED (skip / recall / shipment-cancel paths) — not on pickup
    # completion, so a dispatcher can keep adding stops to a live route.
    return success(ser_stop(stop))


@bp.route("/ltl/pickup-stops/<stopId>/skip", methods=["POST"])
@require_roles("Dispatcher")
def skip_stop(stopId):
    stop = get_path("pickup_stops", stopId)
    if stop["status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED stop can be skipped")
    stop["status"] = "SKIPPED"
    touch(stop)
    check_route_completion(db.store["pickup_routes"][stop["route_id"]])
    return success(ser_stop(stop))
