"""Route + Stop endpoints (PRD §3.2)."""
from flask import request, Blueprint

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import serializers as ser
from services.common import check_enum, get_json_body, paginate, parse_pagination, require_fields

bp = Blueprint("routes", __name__)

STREAMS = {"TRASH", "RECYCLE", "ORGANICS"}
STOP_STATUSES = {"PENDING", "SERVICED", "SKIPPED"}


# ----------------------------- Route -----------------------------

@bp.route("/routes", methods=["POST"])
def create_route():
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["service_date", "stream"])
    check_enum(body["stream"], STREAMS, "stream")
    rec = base_record()
    rec.update(
        {
            "service_date": body["service_date"],
            "stream": body["stream"],
            "status": "PLANNED",
            "assigned_driver_id": body.get("assigned_driver_id"),
        }
    )
    db.routes[rec["id"]] = rec
    return success(ser.route(rec), status=201)


@bp.route("/routes/<route_id>", methods=["GET"])
def get_route(route_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Route not found.")
    return success(ser.route(rec), status=200)


@bp.route("/routes", methods=["GET"])
def list_routes():
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    parse_pagination()
    items = list(db.routes.values())
    status = request.args.get("status")
    stream = request.args.get("stream")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if stream is not None:
        items = [r for r in items if r["stream"] == stream]
    page, pagination = paginate(items)
    return success([ser.route(r) for r in page], status=200, pagination=pagination)


@bp.route("/routes/<route_id>", methods=["PATCH"])
def patch_route(route_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Route not found.")
    body = get_json_body()
    require_fields(body, ["assigned_driver_id"])
    if rec["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Driver can only be changed while the route is PLANNED.")
    rec["assigned_driver_id"] = body["assigned_driver_id"]
    touch(rec)
    return success(ser.route(rec), status=200)


@bp.route("/routes/<route_id>/dispatch", methods=["POST"])
def dispatch_route(route_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Route not found.")
    if rec["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Only a PLANNED route can be dispatched.")
    has_stop = any(s["route_id"] == route_id for s in db.stops.values())
    if rec["assigned_driver_id"] is None or not has_stop:
        raise err("ERR_DRIVER_NOT_ASSIGNED", "Route requires an assigned driver and at least one stop.")
    rec["status"] = "DISPATCHED"
    touch(rec)
    return success(ser.route(rec), status=200)


@bp.route("/routes/<route_id>/start", methods=["POST"])
def start_route(route_id):
    _, role = authenticate()
    require_roles(role, {"Driver"})
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Route not found.")
    if rec["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Only a DISPATCHED route can be started.")
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    return success(ser.route(rec), status=200)


@bp.route("/routes/<route_id>/complete", methods=["POST"])
def complete_route(route_id):
    _, role = authenticate()
    require_roles(role, {"Driver"})
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Route not found.")
    if rec["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Only an IN_PROGRESS route can be completed.")
    pending = any(
        s["route_id"] == route_id and s["status"] == "PENDING"
        for s in db.stops.values()
    )
    if pending:
        raise err("ERR_STOPS_PENDING", "Route has stops still PENDING.")
    rec["status"] = "COMPLETED"
    touch(rec)
    return success(ser.route(rec), status=200)


@bp.route("/routes/<route_id>/cancel", methods=["POST"])
def cancel_route(route_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Route not found.")
    if rec["status"] not in ("PLANNED", "DISPATCHED"):
        raise err("ERR_INVALID_STATE", "Route cannot be cancelled from its current state.")
    rec["status"] = "CANCELLED"
    touch(rec)
    # Cascade: PENDING stops -> SKIPPED
    for s in db.stops.values():
        if s["route_id"] == route_id and s["status"] == "PENDING":
            s["status"] = "SKIPPED"
            touch(s)
    return success(ser.route(rec), status=200)


# ----------------------------- Stop -----------------------------

@bp.route("/routes/<route_id>/stops", methods=["POST"])
def add_stop(route_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    route = db.routes.get(route_id)
    if route is None:
        raise err("ERR_NOT_FOUND", "Route not found.")
    body = get_json_body()
    # Body-reference existence (priority 5) precedes request-shape (priority 6).
    require_fields(body, ["account_id"])
    if body["account_id"] not in db.accounts:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced account does not exist.")
    require_fields(body, ["sequence"])
    sequence = body["sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise err("ERR_INVALID_REQUEST", "sequence must be an integer >= 1.")
    # ERR_DUPLICATE_SEQUENCE: unique within route.
    dup = any(
        s["route_id"] == route_id and s["sequence"] == sequence
        for s in db.stops.values()
    )
    if dup:
        raise err("ERR_DUPLICATE_SEQUENCE", "A stop with this sequence already exists on the route.")
    rec = base_record()
    rec.update(
        {
            "route_id": route_id,
            "account_id": body["account_id"],
            "sequence": sequence,
            "status": "PENDING",
        }
    )
    db.stops[rec["id"]] = rec
    return success(ser.stop(rec), status=201)


@bp.route("/routes/<route_id>/stops", methods=["GET"])
def list_route_stops(route_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    route = db.routes.get(route_id)
    if route is None:
        raise err("ERR_NOT_FOUND", "Route not found.")
    parse_pagination()
    items = [s for s in db.stops.values() if s["route_id"] == route_id]
    page, pagination = paginate(items)
    return success([ser.stop(s) for s in page], status=200, pagination=pagination)


@bp.route("/stops/<stop_id>", methods=["GET"])
def get_stop(stop_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    rec = db.stops.get(stop_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Stop not found.")
    return success(ser.stop(rec), status=200)


@bp.route("/stops", methods=["GET"])
def list_stops():
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    parse_pagination()
    items = list(db.stops.values())
    account_id = request.args.get("account_id")
    route_id = request.args.get("route_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if route_id is not None:
        items = [s for s in items if s["route_id"] == route_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pagination = paginate(items)
    return success([ser.stop(s) for s in page], status=200, pagination=pagination)
