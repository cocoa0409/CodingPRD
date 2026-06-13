"""Delivery-leg routes: schedule, fetch, list, dispatch/deliver/fail
(PRD §3.11).
"""
from flask import Blueprint, request

from common import (
    get_json, stamp_create, touch, paginate, parse_dt, require,
)
from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_VALIDATION_WINDOW, ERR_LEG_OUT_OF_ORDER, ERR_LEG_WINDOW_CONFLICT,
    ERR_STALE_ORDER_VERSION,
)
from middleware import authenticate, authorize
from response import success, success_list
from serializers import ser_leg
from services.helpers import get_or_404, recompute_route

bp = Blueprint("legs", __name__)


def _parse_route_version(body):
    """Body well-formedness for expected_route_version (PRD §3.12 body stage)."""
    if "expected_route_version" not in body or body["expected_route_version"] is None:
        raise err(ERR_INVALID_REQUEST, "expected_route_version is required")
    expected = body["expected_route_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_route_version must be an integer")
    return expected


def _check_route_version(expected, route):
    """OCC mismatch (runs after the state check per PRD §3.12)."""
    if expected != route["version"]:
        raise err(ERR_STALE_ORDER_VERSION, "expected_route_version mismatch")


@bp.route("/catering/delivery-legs", methods=["POST"])
def create_leg():
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "SalesCoordinator"})
    body = get_json()

    # existence left-to-right: order, route, preceding leg (PRD §2.6)
    order_id = require(body, "order_id")
    if not isinstance(order_id, str):
        raise err(ERR_INVALID_REQUEST, "order_id must be a string")
    order = get_or_404(db.orders, order_id)
    route_id = require(body, "route_id")
    if not isinstance(route_id, str):
        raise err(ERR_INVALID_REQUEST, "route_id must be a string")
    route = get_or_404(db.routes, route_id)

    preceding_leg_id = body.get("preceding_leg_id")
    if preceding_leg_id is not None:
        if not isinstance(preceding_leg_id, str):
            raise err(ERR_INVALID_REQUEST, "preceding_leg_id must be a string")
        get_or_404(db.delivery_legs, preceding_leg_id)

    window_start = parse_dt(require(body, "window_start"))
    window_end = parse_dt(require(body, "window_end"))
    if window_end <= window_start:
        raise err(ERR_VALIDATION_WINDOW, "window_end must be after window_start")

    rec = {
        "order_id": order_id,
        "route_id": route_id,
        "preceding_leg_id": preceding_leg_id,
        "window_start": window_start,
        "window_end": window_end,
        "stop_status": "PLANNED",
    }
    stamp_create(rec)
    db.delivery_legs[rec["id"]] = rec

    # set order.route_id if still null (PRD §3.11)
    if order["route_id"] is None:
        order["route_id"] = route_id
        touch(order)

    # recompute route posture (a new PLANNED leg leaves it OPEN, but the route
    # version still bumps because its derived state was recomputed) PRD §2.5
    recompute_route(route)
    return success(ser_leg(rec), status=201)


@bp.route("/catering/delivery-legs/<lid>", methods=["GET"])
def get_leg(lid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "EventCaptain", "SalesCoordinator"})
    rec = get_or_404(db.delivery_legs, lid)
    return success(ser_leg(rec))


@bp.route("/catering/delivery-legs", methods=["GET"])
def list_legs():
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "EventCaptain", "SalesCoordinator"})
    rows = list(db.delivery_legs.values())
    for f in ("order_id", "route_id", "preceding_leg_id", "stop_status"):
        val = request.args.get(f)
        if val is not None:
            rows = [r for r in rows if r[f] == val]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_leg(r) for r in page], limit, offset, total)


@bp.route("/catering/delivery-legs/<lid>/dispatch", methods=["POST"])
def dispatch_leg(lid):
    _, role = authenticate()
    authorize(role, {"EventCaptain"})
    leg = get_or_404(db.delivery_legs, lid)
    route = db.routes[leg["route_id"]]
    body = get_json()
    expected = _parse_route_version(body)

    # state: leg must be PLANNED
    if leg["stop_status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "leg is not PLANNED")
    # parent order must be GUARANTEED
    order = db.orders[leg["order_id"]]
    if order["lifecycle_status"] != "GUARANTEED":
        raise err(ERR_INVALID_STATE, "parent order is not GUARANTEED")

    # OCC route-version mismatch (business rule, after state)
    _check_route_version(expected, route)

    # window conflict check (priority 9) — checked before the route-order/
    # capacity check (priority 11) per validation ordering (SCAFFOLD §1.4)
    for other in db.delivery_legs.values():
        if other["id"] == leg["id"]:
            continue
        if other["route_id"] != leg["route_id"]:
            continue
        if other["stop_status"] != "DISPATCHED":
            continue
        # inclusive overlap at the endpoints
        if leg["window_start"] <= other["window_end"] and other["window_start"] <= leg["window_end"]:
            raise err(ERR_LEG_WINDOW_CONFLICT, "window overlaps another dispatched leg on the route")

    # route ordering + vehicle capacity (priority 11)
    if leg["preceding_leg_id"] is not None:
        prev = db.delivery_legs.get(leg["preceding_leg_id"])
        if prev is None or prev["stop_status"] not in ("DISPATCHED", "DELIVERED"):
            raise err(ERR_LEG_OUT_OF_ORDER, "preceding leg not yet dispatched/delivered")
    if route["dispatched_leg_count"] >= route["vehicle_capacity_legs"]:
        raise err(ERR_LEG_OUT_OF_ORDER, "vehicle leg capacity exceeded")

    leg["stop_status"] = "DISPATCHED"
    touch(leg)
    recompute_route(route)
    return success(ser_leg(leg))


@bp.route("/catering/delivery-legs/<lid>/deliver", methods=["POST"])
def deliver_leg(lid):
    _, role = authenticate()
    authorize(role, {"EventCaptain"})
    leg = get_or_404(db.delivery_legs, lid)
    route = db.routes[leg["route_id"]]
    body = get_json()
    expected = _parse_route_version(body)

    if leg["stop_status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "leg is not DISPATCHED")

    _check_route_version(expected, route)

    leg["stop_status"] = "DELIVERED"
    touch(leg)
    recompute_route(route)
    return success(ser_leg(leg))


@bp.route("/catering/delivery-legs/<lid>/fail", methods=["POST"])
def fail_leg(lid):
    _, role = authenticate()
    authorize(role, {"EventCaptain"})
    leg = get_or_404(db.delivery_legs, lid)
    route = db.routes[leg["route_id"]]
    body = get_json()
    expected = _parse_route_version(body)

    if leg["stop_status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "leg is not DISPATCHED")

    _check_route_version(expected, route)

    leg["stop_status"] = "FAILED"
    touch(leg)
    recompute_route(route)
    return success(ser_leg(leg))
