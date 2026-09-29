"""Season routes: creation, the haul-chain sequencing and the commit."""

from flask import Blueprint

import calc
import db
import errors
import serializers as ser
import validators as v
from errors import fail
from middleware import (ROLE_CONTRACT_NEGOTIATOR, ROLE_GENERAL_MANAGER,
                        ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                        ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok

bp = Blueprint("routes_api", __name__)


@bp.post("/routes")
def create_route():
    require_role(ROLE_ROUTE_MANAGER, ROLE_PLATFORM_ADMIN)
    body = v.get_body()
    name = v.req_str(body, "name")
    season_year = v.req_int(body, "season_year", minimum=2020, maximum=2100)
    home_base_state = v.req_str(body, "home_base_state")
    row = db.create(db.store.routes, {
        "name": name,
        "season_year": season_year,
        "home_base_state": home_base_state,
        "status": "DRAFT",
        "total_travel_hours": 0,
    })
    return created(ser.route(row))


@bp.get("/routes/<route_id>")
def get_route(route_id):
    require_role(ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
                 ROLE_TICKETING_AUDITOR, ROLE_CONTRACT_NEGOTIATOR)
    return ok(ser.route(v.path_row("routes", route_id)))


@bp.post("/routes/<route_id>/sequence")
def sequence_route(route_id):
    require_role(ROLE_ROUTE_MANAGER)
    route = v.path_row("routes", route_id)
    if route["status"] != "DRAFT":
        fail(errors.ERR_ROUTE_STATE_INVALID,
             "Only a DRAFT route may be sequenced.")
    if not calc.stops_of_route(route["id"]):
        fail(errors.ERR_ROUTE_HAS_NO_STOPS,
             "The route has no non-DARK stop to sequence.")
    calc.route_travel_feasibility(route)
    route["status"] = "SEQUENCED"
    db.touch(route)
    return ok(ser.route(route))


@bp.post("/routes/<route_id>/commit")
def commit_route(route_id):
    require_role(ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER)
    route = v.path_row("routes", route_id)
    if route["status"] != "SEQUENCED":
        fail(errors.ERR_ROUTE_STATE_INVALID,
             "Only a SEQUENCED route may be committed.")
    for stop in calc.stops_of_route(route["id"]):
        if calc.live_contract_of_stop(stop["id"]) is None:
            fail(errors.ERR_STOP_NOT_CONTRACTED,
                 "Every non-DARK stop must carry a live contract.")
    route["status"] = "COMMITTED"
    db.touch(route)
    return ok(ser.route(route))
