"""Route endpoints."""

from flask import Blueprint, request

import errors
import serializers
from db import stamp_new, store
from envelope import ok
from listing import page_out
from validators import (
    HAZARD_CLASSES,
    as_bool,
    as_dt,
    as_enum_list,
    as_str,
    body,
    endpoint,
    opt,
    req,
)

bp = Blueprint("routes", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


@bp.route("/hazmat/routes", methods=["POST"])
@endpoint(["Regulator"])
def create_route(uid, role):
    b = body()
    route_code = as_str(req(b, "route_code"), "route_code")
    allowed = as_enum_list(req(b, "allowed_hazard_classes"),
                           "allowed_hazard_classes", HAZARD_CLASSES)
    restricted = as_bool(opt(b, "is_restricted_corridor", False),
                         "is_restricted_corridor")
    eff_from = as_dt(req(b, "effective_from"), "effective_from")
    eff_to = as_dt(req(b, "effective_to"), "effective_to")
    if eff_to <= eff_from:
        raise errors.invalid("effective_to must be strictly later than effective_from")
    # Closed-interval overlap for the same route_code: touching endpoints conflict.
    for r in store.routes.values():
        if r["route_code"] != route_code:
            continue
        if eff_from <= r["effective_to"] and r["effective_from"] <= eff_to:
            raise errors.conflict(errors.ERR_ROUTE_WINDOW_CONFLICT,
                                  "Route window overlaps an existing window for this route_code")
    route = {
        "route_code": route_code,
        "allowed_hazard_classes": allowed,
        "is_restricted_corridor": restricted,
        "effective_from": eff_from,
        "effective_to": eff_to,
    }
    stamp_new(route)
    store.routes[route["id"]] = route
    return ok(serializers.route(route), 201)


@bp.route("/hazmat/routes", methods=["GET"])
@endpoint(ALL_ROLES)
def list_routes(uid, role):
    rows = list(store.routes.values())
    route_code = request.args.get("route_code")
    if route_code is not None:
        rows = [r for r in rows if r["route_code"] == route_code]
    return page_out(rows, serializers.route)
