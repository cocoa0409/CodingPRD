"""TestRoute and RouteStop endpoints: planning, publish/cancel, arrive,
mark-missed, and the auto-completion cascade."""

from flask import Blueprint, g

import errors
from db import db, create_entity, touch, now
from helpers import list_response, account_of_route, account_of_stop, query_filter
from response import success_object, success_list
from serializers import test_route as ser_route, route_stop as ser_stop
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership, paginate)

bp = Blueprint("test_routes", __name__)

STOP_TERMINAL = ("SAMPLED", "SKIPPED", "MISSED")


def maybe_complete_route(route):
    """PUBLISHED route completes when every stop is SAMPLED/SKIPPED/MISSED."""
    if route["status"] != "PUBLISHED":
        return
    stops = [s for s in db["route_stops"].values() if s["route_id"] == route["id"]]
    if stops and all(s["status"] in STOP_TERMINAL for s in stops):
        route["status"] = "COMPLETED"
        touch(route)


@bp.route("/wt/test-routes", methods=["POST"])
def create_route():
    body = get_body()
    account = resolve_body_fk(body, "account_id", "accounts")
    vals = validate_shape(body, [
        ("account_id", "str", True),
        ("route_name", "str", True),
    ])
    ent = create_entity("test_routes", {
        "account_id": account["id"],
        "route_name": vals["route_name"],
        "status": "PLANNED",
    })
    return success_object(ser_route(ent), 201)


@bp.route("/wt/test-routes", methods=["GET"])
def list_routes():
    user = (g.role, g.user_id)
    items = list(db["test_routes"].values())
    account_id = query_filter("account_id")
    if account_id is not None:
        items = [r for r in items if r["account_id"] == account_id]
    status = query_filter("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, ser_route, account_of_route, user)


@bp.route("/wt/test-routes/<routeId>", methods=["GET"])
def get_route(routeId):
    ent = db["test_routes"].get(routeId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, ent["account_id"])
    ent = resolve("test_routes", routeId)
    return success_object(ser_route(ent), 200)


@bp.route("/wt/test-routes/<routeId>/stops", methods=["POST"])
def add_stop(routeId):
    route = resolve("test_routes", routeId)
    body = get_body()
    asset = resolve_body_fk(body, "asset_id", "assets")
    vals = validate_shape(body, [
        ("asset_id", "str", True),
        ("window_start", "iso", True),
        ("window_end", "iso", True),
        ("sequence_index", "int", True),
    ])
    # Tier 6: route must be PLANNED.
    if route["status"] != "PLANNED":
        raise errors.invalid_state("Stops can only be added to a PLANNED route")
    # Tier 10 field constraints.
    if not vals["window_end"] > vals["window_start"]:
        raise errors.field_constraint("window_end must be strictly after window_start")
    if vals["sequence_index"] < 1:
        raise errors.field_constraint("sequence_index must be at least 1")
    for s in db["route_stops"].values():
        if s["route_id"] == route["id"] and s["sequence_index"] == vals["sequence_index"]:
            raise errors.field_constraint("sequence_index must be unique within the route")
    # Tier 12: half-open window overlap on the same asset (adjacency allowed);
    # only SCHEDULED/ARRIVED stops participate.
    for s in db["route_stops"].values():
        if s["asset_id"] != asset["id"] or s["status"] not in ("SCHEDULED", "ARRIVED"):
            continue
        if vals["window_start"] < s["window_end"] and s["window_start"] < vals["window_end"]:
            raise errors.ApiError(errors.ERR_WINDOW_CONFLICT, 409,
                                  "Visit window overlaps another stop on the same asset")
    ent = create_entity("route_stops", {
        "route_id": route["id"],
        "asset_id": asset["id"],
        "window_start": vals["window_start"],
        "window_end": vals["window_end"],
        "sequence_index": vals["sequence_index"],
        "status": "SCHEDULED",
    })
    return success_object(ser_stop(ent), 201)


@bp.route("/wt/test-routes/<routeId>/stops", methods=["GET"])
def list_stops_of_route(routeId):
    route = db["test_routes"].get(routeId)
    if route is not None:
        check_cc_ownership(g.user_id, g.role, route["account_id"])
    route = resolve("test_routes", routeId)
    items = [s for s in db["route_stops"].values() if s["route_id"] == route["id"]]
    items.sort(key=lambda s: (s["sequence_index"], s["_seq"]))  # sequence_index ASC
    page, limit, offset, total = paginate(items)
    return success_list([ser_stop(s) for s in page], limit, offset, total)


@bp.route("/wt/test-routes/<routeId>/publish", methods=["POST"])
def publish_route(routeId):
    ent = resolve("test_routes", routeId)
    get_body()
    if ent["status"] != "PLANNED":
        raise errors.invalid_state("Route must be PLANNED to publish")
    if not any(s["route_id"] == ent["id"] and s["status"] == "SCHEDULED"
               for s in db["route_stops"].values()):
        raise errors.ApiError(errors.ERR_EMPTY_ROUTE, 409,
                              "Publish requires at least one SCHEDULED stop")
    ent["status"] = "PUBLISHED"
    touch(ent)
    return success_object(ser_route(ent), 200)


@bp.route("/wt/test-routes/<routeId>/cancel", methods=["POST"])
def cancel_route(routeId):
    ent = resolve("test_routes", routeId)
    get_body()
    if ent["status"] not in ("PLANNED", "PUBLISHED"):
        raise errors.invalid_state("Route must be PLANNED or PUBLISHED to cancel")
    ent["status"] = "CANCELLED"
    touch(ent)
    for s in db["route_stops"].values():
        if s["route_id"] == ent["id"] and s["status"] == "SCHEDULED":
            s["status"] = "SKIPPED"
            touch(s)
    return success_object(ser_route(ent), 200)


@bp.route("/wt/route-stops", methods=["GET"])
def list_stops():
    user = (g.role, g.user_id)
    items = list(db["route_stops"].values())
    route_id = query_filter("route_id")
    if route_id is not None:
        items = [s for s in items if s["route_id"] == route_id]
    asset_id = query_filter("asset_id")
    if asset_id is not None:
        items = [s for s in items if s["asset_id"] == asset_id]
    status = query_filter("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_stop, account_of_stop, user)


@bp.route("/wt/route-stops/<stopId>", methods=["GET"])
def get_stop(stopId):
    ent = db["route_stops"].get(stopId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, account_of_stop(ent))
    ent = resolve("route_stops", stopId)
    return success_object(ser_stop(ent), 200)


@bp.route("/wt/route-stops/<stopId>/arrive", methods=["POST"])
def arrive_stop(stopId):
    ent = resolve("route_stops", stopId)
    get_body()
    if ent["status"] != "SCHEDULED":
        raise errors.invalid_state("Stop must be SCHEDULED to arrive")
    # Tier 7 cross-entity gates: route PUBLISHED, then posture not FROZEN.
    route = db["test_routes"][ent["route_id"]]
    if route["status"] != "PUBLISHED":
        raise errors.ApiError(errors.ERR_ROUTE_NOT_PUBLISHED, 409,
                              "Arrive requires the owning route to be PUBLISHED")
    asset = db["assets"].get(ent["asset_id"])
    if asset is not None and asset["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_ASSET_FROZEN, 409,
                              "Asset posture FROZEN gates arrival")
    # Tier 11 temporal: clock in [window_start, window_end).
    current = now()
    if not (ent["window_start"] <= current < ent["window_end"]):
        raise errors.ApiError(errors.ERR_OUTSIDE_VISIT_WINDOW, 422,
                              "Current clock is outside the half-open visit window")
    ent["status"] = "ARRIVED"
    touch(ent)
    return success_object(ser_stop(ent), 200)


@bp.route("/wt/route-stops/<stopId>/mark-missed", methods=["POST"])
def mark_missed(stopId):
    ent = resolve("route_stops", stopId)
    get_body()
    if ent["status"] != "SCHEDULED":
        raise errors.invalid_state("Stop must be SCHEDULED to mark missed")
    if now() < ent["window_end"]:
        raise errors.ApiError(errors.ERR_WINDOW_NOT_ELAPSED, 422,
                              "The visit window has not elapsed yet")
    ent["status"] = "MISSED"
    touch(ent)
    maybe_complete_route(db["test_routes"][ent["route_id"]])
    return success_object(ser_stop(ent), 200)
