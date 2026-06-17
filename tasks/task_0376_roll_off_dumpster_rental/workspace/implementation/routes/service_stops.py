"""ServiceStop endpoints (PRD sections 3.6, 3.7, 3.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import get_stop, get_order, check_stop_owner, paginate
from middleware import require_auth, require_role
from response import success
import serialize
from serialize import service_stop as ser
from billing import run_pickup_billing, find_pickup_ticket, _date_diff_days

import validate

bp = Blueprint("service_stops", __name__)


@bp.get("/service-stops")
def list_stops():
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "Contractor"])
    limit, offset = validate.get_pagination()
    records = list(db.service_stops.values())
    if role == "Contractor":
        owned = {o["id"] for o in db.rental_orders.values()
                 if o["account_id"] == user_id}
        records = [s for s in records if s["order_id"] in owned]
    order_id = request.args.get("order_id")
    route_id = request.args.get("route_id")
    stop_type = request.args.get("stop_type")
    status = request.args.get("status")
    if order_id is not None:
        records = [s for s in records if s["order_id"] == order_id]
    if route_id is not None:
        records = [s for s in records if s["route_id"] == route_id]
    if stop_type is not None:
        records = [s for s in records if s["stop_type"] == stop_type]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return paginate(records, ser, limit, offset)


@bp.get("/service-stops/<stop_id>")
def get_stop_ep(stop_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "Contractor"])
    stop = get_stop(stop_id)
    check_stop_owner(stop, role, user_id)
    return success(ser(stop), status=200)


@bp.post("/service-stops/<stop_id>/complete")
def complete_stop(stop_id):
    _, role = require_auth()
    require_role(role, ["Dispatcher"])
    stop = get_stop(stop_id)

    # state (priority 5): stop ASSIGNED, route DISPATCHED.
    if stop["status"] != "ASSIGNED":
        raise err("ERR_STOP_NOT_ASSIGNED", "Service stop is not ASSIGNED")
    route = db.routes.get(stop["route_id"]) if stop["route_id"] else None
    if route is None or route["status"] != "DISPATCHED":
        raise err("ERR_ROUTE_NOT_DISPATCHED", "Route is not DISPATCHED")

    order = db.rental_orders.get(stop["order_id"])
    stop_type = stop["stop_type"]

    if stop_type == "DELIVERY":
        # order must be SCHEDULED.
        if order["logistics_status"] != "SCHEDULED":
            raise err("ERR_ORDER_NOT_SCHEDULED", "Order is not SCHEDULED")
        _complete_delivery(stop, order, route)
    elif stop_type == "SWAP":
        # order must be ON_SITE; weigh-ticket required.
        if order["logistics_status"] != "ON_SITE":
            raise err("ERR_ORDER_NOT_ON_SITE", "Order is not ON_SITE")
        if find_pickup_ticket(order["id"], stop_id) is None:
            raise err("ERR_WEIGH_TICKET_REQUIRED", "A weigh ticket is required for this stop")
        _complete_swap(stop, order)
    elif stop_type == "PICKUP":
        # order must be ON_SITE; weigh-ticket required.
        if order["logistics_status"] != "ON_SITE":
            raise err("ERR_ORDER_NOT_ON_SITE", "Order is not ON_SITE")
        ticket = find_pickup_ticket(order["id"], stop_id)
        if ticket is None:
            raise err("ERR_WEIGH_TICKET_REQUIRED", "A weigh ticket is required for this stop")
        _complete_pickup(stop, order, route, ticket)

    return success(ser(stop), status=200)


def _complete_delivery(stop, order, route):
    stop["status"] = "COMPLETED"
    db.touch(stop)
    order["logistics_status"] = "ON_SITE"
    order["delivered_on"] = route["service_date"]
    db.touch(order)
    container = db.containers.get(order["container_id"]) if order["container_id"] else None
    if container is not None:
        container["status"] = "ON_SITE"
        db.touch(container)


def _complete_swap(stop, order):
    stop["status"] = "COMPLETED"
    db.touch(stop)
    # The hauled-away can goes ON_SITE -> AWAITING_DUMP; order stays ON_SITE.
    container = db.containers.get(order["container_id"]) if order["container_id"] else None
    if container is not None:
        container["status"] = "AWAITING_DUMP"
        db.touch(container)


def _complete_pickup(stop, order, route, ticket):
    stop["status"] = "COMPLETED"
    db.touch(stop)

    # Logistics: ON_SITE -> AWAITING_PICKUP; stamp picked_up_on, recompute rental_days.
    order["logistics_status"] = "AWAITING_PICKUP"
    order["picked_up_on"] = route["service_date"]
    order["rental_days"] = _date_diff_days(order["delivered_on"], route["service_date"])
    db.touch(order)

    # Container ON_SITE -> AWAITING_DUMP.
    container = db.containers.get(order["container_id"]) if order["container_id"] else None
    if container is not None:
        container["status"] = "AWAITING_DUMP"
        db.touch(container)

    # Billing cascade: UNBILLED -> ESTIMATED -> FINALIZED + invoice + ledger.
    ctype = db.container_types.get(order["container_type_id"])
    run_pickup_billing(order, stop, ticket, ctype)

    # Tail: AWAITING_PICKUP -> COMPLETED once billing finalized.
    order["logistics_status"] = "COMPLETED"
    db.touch(order)


@bp.post("/service-stops/<stop_id>/cancel")
def cancel_stop(stop_id):
    user_id, role = require_auth()
    require_role(role, ["Dispatcher", "Contractor"])
    stop = get_stop(stop_id)
    check_stop_owner(stop, role, user_id)

    status = stop["status"]
    if status == "UNASSIGNED":
        stop["status"] = "CANCELLED"
        db.touch(stop)
        return success(ser(stop), status=200)
    if status == "ASSIGNED":
        route = db.routes.get(stop["route_id"]) if stop["route_id"] else None
        # ASSIGNED stop cancellable only while route still PLANNING.
        if route is None or route["status"] != "PLANNING":
            raise err("ERR_ROUTE_NOT_PLANNING", "Route is not PLANNING")
        stop["status"] = "CANCELLED"
        db.touch(stop)
        db.touch(route)  # stop_count recomputed (computed on read), version bumps
        return success(ser(stop), status=200)
    raise err("ERR_STOP_NOT_CANCELLABLE", "Service stop is not cancellable")
