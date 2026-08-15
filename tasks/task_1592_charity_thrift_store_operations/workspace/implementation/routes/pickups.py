"""PickupRoute + PickupStop endpoints (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint

from db import db, new_record, touch, parse_ts
from errors import (
    ApiError, not_found, invalid_request,
    ERR_ROUTE_INVALID_STATE, ERR_ROUTE_EMPTY, ERR_ROUTE_CAPACITY_EXCEEDED,
    ERR_STOP_INVALID_STATE, ERR_STOP_OUT_OF_SEQUENCE, ERR_STOP_WINDOW_CONFLICT,
    ERR_DONOR_INACTIVE, ERR_DRIVER_NOT_STAFF, ERR_FORBIDDEN_OWNERSHIP,
    ERR_NOT_FOUND,
)
from middleware import require_roles, get_body, ALL_ROLES, paginate, query_filters, apply_filters
from response import success_object, success_list
from services.helpers import recompute_route_rollups

bp = Blueprint("pickups", __name__)

TRAVEL_BUFFER_MINUTES = 30
TERMINAL_STOP_STATES = ("COMPLETED", "NO_SHOW", "CANCELLED")


def route_view(r):
    return dict(r)


def stop_view(s):
    return dict(s)


def _get_route(route_id):
    r = db.routes.get(route_id)
    if r is None:
        raise not_found("pickup route")
    return r


def _get_stop(stop_id):
    s = db.stops.get(stop_id)
    if s is None:
        raise not_found("pickup stop")
    return s


def _check_window_conflicts(route_id, new_start, new_end, exclude_stop_id=None):
    """30-minute travel buffer on both sides vs stops in SCHEDULED | EN_ROUTE.
    Exactly 30 minutes of separation is allowed (half-open with buffer)."""
    buffer = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for s in db.stops.values():
        if s["route_id"] != route_id or s["id"] == exclude_stop_id:
            continue
        if s["status"] not in ("SCHEDULED", "EN_ROUTE"):
            continue
        s_start = parse_ts(s["window_start"])
        s_end = parse_ts(s["window_end"])
        if not (new_start >= s_end + buffer or s_start >= new_end + buffer):
            raise ApiError(ERR_STOP_WINDOW_CONFLICT, 422,
                           "Stop window violates the 30-minute travel buffer")


@bp.route("/api/pickup-routes", methods=["POST"])
def create_route():
    require_roles(["StoreManager"])
    payload = get_body(
        required=[("route_date", "string"), ("driver_worker_id", "string"),
                  ("truck_capacity_cuft", "number")],
    )
    if float(payload["truck_capacity_cuft"]) <= 0:
        raise invalid_request("truck_capacity_cuft must be > 0")
    driver = db.workers.get(payload["driver_worker_id"])
    if driver is None:
        raise not_found("worker")
    if driver["status"] != "ACTIVE" or driver["employment_type"] != "STAFF":
        raise ApiError(ERR_DRIVER_NOT_STAFF, 422,
                       "Route driver must be an ACTIVE STAFF worker")
    rec = new_record()
    rec.update({
        "route_date": payload["route_date"],
        "driver_worker_id": payload["driver_worker_id"],
        "truck_capacity_cuft": payload["truck_capacity_cuft"],
        "status": "DRAFT",
        "stop_count": 0,
        "total_volume_cuft": 0,
    })
    db.routes[rec["id"]] = rec
    return success_object(route_view(rec), status=201)


@bp.route("/api/pickup-routes/<route_id>", methods=["GET"])
def get_route(route_id):
    require_roles(ALL_ROLES)
    return success_object(route_view(_get_route(route_id)))


@bp.route("/api/pickup-routes", methods=["GET"])
def list_routes():
    require_roles(ALL_ROLES)
    filters = query_filters(["driver_worker_id", "status"])
    records = apply_filters(list(db.routes.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([route_view(r) for r in page], limit, offset, total)


@bp.route("/api/pickup-routes/<route_id>/stops", methods=["POST"])
def add_stop(route_id):
    require_roles(["StoreManager"])
    payload = get_body(
        required=[("donor_id", "string"), ("window_start", "string"),
                  ("window_end", "string"), ("estimated_volume_cuft", "number")],
    )
    if float(payload["estimated_volume_cuft"]) <= 0:
        raise invalid_request("estimated_volume_cuft must be > 0")
    try:
        w_start = parse_ts(payload["window_start"])
        w_end = parse_ts(payload["window_end"])
    except (ValueError, TypeError):
        raise invalid_request("window_start/window_end must be ISO8601 timestamps")
    if not w_end > w_start:
        raise invalid_request("window_end must be strictly after window_start")
    route = _get_route(route_id)
    donor = db.donors.get(payload["donor_id"])
    if donor is None:
        raise not_found("donor")
    # state: stops join only while DRAFT
    if route["status"] != "DRAFT":
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                       "Stops can be added only to a DRAFT route")
    # capacity (priority 9) before temporal buffer (priority 10)
    recompute_route_rollups(route)
    if float(route["total_volume_cuft"]) + float(payload["estimated_volume_cuft"]) \
            > float(route["truck_capacity_cuft"]):
        raise ApiError(ERR_ROUTE_CAPACITY_EXCEEDED, 422,
                       "Stop volume would exceed the truck capacity")
    _check_window_conflicts(route["id"], w_start, w_end)
    # donor ACTIVE (priority 11)
    if donor["status"] != "ACTIVE":
        raise ApiError(ERR_DONOR_INACTIVE, 422, "Referenced donor is INACTIVE")
    rec = new_record()
    rec.update({
        "route_id": route["id"],
        "donor_id": payload["donor_id"],
        "window_start": payload["window_start"],
        "window_end": payload["window_end"],
        "estimated_volume_cuft": payload["estimated_volume_cuft"],
        "status": "SCHEDULED",
        "completed_batch_id": None,
    })
    db.stops[rec["id"]] = rec
    recompute_route_rollups(route)
    touch(route)
    return success_object(stop_view(rec), status=201)


@bp.route("/api/pickup-routes/<route_id>/stops", methods=["GET"])
def list_route_stops(route_id):
    require_roles(ALL_ROLES)
    _get_route(route_id)
    records = [s for s in db.stops.values() if s["route_id"] == route_id]
    page, limit, offset, total = paginate(records)
    return success_list([stop_view(s) for s in page], limit, offset, total)


@bp.route("/api/pickup-stops/<stop_id>", methods=["GET"])
def get_stop(stop_id):
    require_roles(ALL_ROLES)
    return success_object(stop_view(_get_stop(stop_id)))


@bp.route("/api/pickup-stops", methods=["GET"])
def list_stops():
    require_roles(ALL_ROLES)
    filters = query_filters(["donor_id", "route_id", "completed_batch_id", "status"])
    records = apply_filters(list(db.stops.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([stop_view(s) for s in page], limit, offset, total)


@bp.route("/api/pickup-routes/<route_id>/publish", methods=["POST"])
def publish_route(route_id):
    require_roles(["StoreManager"])
    get_body()
    route = _get_route(route_id)
    if route["status"] != "DRAFT":
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                       "publish requires a DRAFT route")
    scheduled = [s for s in db.stops.values()
                 if s["route_id"] == route["id"] and s["status"] == "SCHEDULED"]
    if len(scheduled) < 1:
        raise ApiError(ERR_ROUTE_EMPTY, 422,
                       "publish requires at least one SCHEDULED stop")
    route["status"] = "PUBLISHED"
    touch(route)
    return success_object(route_view(route))


@bp.route("/api/pickup-routes/<route_id>/unpublish", methods=["POST"])
def unpublish_route(route_id):
    require_roles(["StoreManager"])
    get_body()
    route = _get_route(route_id)
    if route["status"] != "PUBLISHED":
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                       "unpublish requires a PUBLISHED route")
    for s in db.stops.values():
        if s["route_id"] == route["id"] and s["status"] != "SCHEDULED":
            raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                           "unpublish requires every stop still SCHEDULED")
    route["status"] = "DRAFT"
    touch(route)
    return success_object(route_view(route))


@bp.route("/api/pickup-routes/<route_id>/start", methods=["POST"])
def start_route(route_id):
    require_roles(["StoreManager"])
    get_body()
    route = _get_route(route_id)
    if route["status"] != "PUBLISHED":
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                       "start requires a PUBLISHED route")
    route["status"] = "IN_PROGRESS"
    touch(route)
    return success_object(route_view(route))


@bp.route("/api/pickup-routes/<route_id>/complete", methods=["POST"])
def complete_route(route_id):
    require_roles(["StoreManager"])
    get_body()
    route = _get_route(route_id)
    if route["status"] != "IN_PROGRESS":
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                       "complete requires an IN_PROGRESS route")
    for s in db.stops.values():
        if s["route_id"] == route["id"] and s["status"] not in TERMINAL_STOP_STATES:
            raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                           "complete requires every stop terminal")
    route["status"] = "COMPLETED"
    touch(route)
    return success_object(route_view(route))


@bp.route("/api/pickup-routes/<route_id>/cancel", methods=["POST"])
def cancel_route(route_id):
    require_roles(["StoreManager"])
    get_body()
    route = _get_route(route_id)
    if route["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                       "cancel requires a DRAFT or PUBLISHED route")
    route["status"] = "CANCELLED"
    for s in db.stops.values():
        if s["route_id"] == route["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
    recompute_route_rollups(route)
    touch(route)
    return success_object(route_view(route))


def _driver_owns_route(user_id, stop):
    route = db.routes.get(stop["route_id"])
    if route is None:
        raise not_found("pickup route")
    if user_id != route["driver_worker_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Driver does not own this route")
    return route


@bp.route("/api/pickup-stops/<stop_id>/depart", methods=["POST"])
def depart_stop(stop_id):
    user_id, role = require_roles(["Driver"])
    get_body()
    stop = _get_stop(stop_id)
    route = db.routes.get(stop["route_id"])
    if route is None:
        raise not_found("pickup route")
    # ownership (priority 5) precedes state checks (priority 6)
    if user_id != route["driver_worker_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Driver does not own this route")
    # route must be IN_PROGRESS
    if route["status"] != "IN_PROGRESS":
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                       "depart requires the route IN_PROGRESS")
    # stop from-state
    if stop["status"] != "SCHEDULED":
        raise ApiError(ERR_STOP_INVALID_STATE, 409,
                       "depart requires a SCHEDULED stop")
    # sequencing: every earlier-windowed stop must be terminal
    my_start = parse_ts(stop["window_start"])
    for s in db.stops.values():
        if s["route_id"] == route["id"] and s["id"] != stop["id"]:
            if parse_ts(s["window_start"]) < my_start and s["status"] not in TERMINAL_STOP_STATES:
                raise ApiError(ERR_STOP_OUT_OF_SEQUENCE, 422,
                               "An earlier-windowed stop on the route is not terminal")
    stop["status"] = "EN_ROUTE"
    touch(stop)
    return success_object(stop_view(stop))


@bp.route("/api/pickup-stops/<stop_id>/complete", methods=["POST"])
def complete_stop(stop_id):
    user_id, role = require_roles(["Driver"])
    get_body()
    stop = _get_stop(stop_id)
    route = _driver_owns_route(user_id, stop)
    if stop["status"] != "EN_ROUTE":
        raise ApiError(ERR_STOP_INVALID_STATE, 409,
                       "complete requires an EN_ROUTE stop")
    stop["status"] = "COMPLETED"
    # cascade: auto-create the donor's PICKUP_STOP donation batch
    batch = new_record()
    batch.update({
        "donor_id": stop["donor_id"],
        "source": "PICKUP_STOP",
        "pickup_stop_id": stop["id"],
        "receipt_requested": True,
        "status": "OPEN",
        "item_count": 0,
        "untriaged_count": 0,
        "provisional_value_cents": 0,
        "sold_item_count": 0,
        "closed_at": None,
    })
    db.batches[batch["id"]] = batch
    stop["completed_batch_id"] = batch["id"]
    touch(stop)
    return success_object(stop_view(stop))


@bp.route("/api/pickup-stops/<stop_id>/no-show", methods=["POST"])
def no_show_stop(stop_id):
    user_id, role = require_roles(["Driver"])
    get_body()
    stop = _get_stop(stop_id)
    _driver_owns_route(user_id, stop)
    if stop["status"] != "EN_ROUTE":
        raise ApiError(ERR_STOP_INVALID_STATE, 409,
                       "no-show requires an EN_ROUTE stop")
    stop["status"] = "NO_SHOW"
    touch(stop)
    return success_object(stop_view(stop))


@bp.route("/api/pickup-stops/<stop_id>/reschedule", methods=["POST"])
def reschedule_stop(stop_id):
    require_roles(["StoreManager"])
    payload = get_body(
        required=[("target_route_id", "string"), ("window_start", "string"),
                  ("window_end", "string")],
    )
    try:
        w_start = parse_ts(payload["window_start"])
        w_end = parse_ts(payload["window_end"])
    except (ValueError, TypeError):
        raise invalid_request("window_start/window_end must be ISO8601 timestamps")
    if not w_end > w_start:
        raise invalid_request("window_end must be strictly after window_start")
    stop = _get_stop(stop_id)
    target = db.routes.get(payload["target_route_id"])
    if target is None:
        raise ApiError(ERR_NOT_FOUND, 404, "target route not found")
    if stop["status"] != "NO_SHOW":
        raise ApiError(ERR_STOP_INVALID_STATE, 409,
                       "reschedule requires a NO_SHOW stop")
    if target["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409,
                       "reschedule target route must be DRAFT or PUBLISHED")
    recompute_route_rollups(target)
    if float(target["total_volume_cuft"]) + float(stop["estimated_volume_cuft"]) \
            > float(target["truck_capacity_cuft"]):
        raise ApiError(ERR_ROUTE_CAPACITY_EXCEEDED, 422,
                       "Stop volume would exceed the truck capacity")
    _check_window_conflicts(target["id"], w_start, w_end)
    donor = db.donors.get(stop["donor_id"])
    if donor is None:
        raise not_found("donor")
    if donor["status"] != "ACTIVE":
        raise ApiError(ERR_DONOR_INACTIVE, 422, "Referenced donor is INACTIVE")
    rec = new_record()
    rec.update({
        "route_id": target["id"],
        "donor_id": stop["donor_id"],
        "window_start": payload["window_start"],
        "window_end": payload["window_end"],
        "estimated_volume_cuft": stop["estimated_volume_cuft"],
        "status": "SCHEDULED",
        "completed_batch_id": None,
    })
    db.stops[rec["id"]] = rec
    recompute_route_rollups(target)
    touch(target)
    return success_object(stop_view(rec), status=201)
