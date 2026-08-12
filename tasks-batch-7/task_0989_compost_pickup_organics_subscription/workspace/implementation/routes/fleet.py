"""Route, generate-stops, weigh-ticket posting, and Bin endpoints."""

from flask import Blueprint, request

import response
from db import new_entity, store, touch
from errors import (ERR_INVALID_STATE, ERR_SERVICE_DATE_WEEKDAY_MISMATCH,
                    ApiError, not_found, unprocessable)
from middleware import auth, require_roles
from services import (BIN_TYPES, WEEKDAYS, by_seq, post_weigh_ticket, ser_bin,
                      ser_route, ser_weigh_ticket)
from utils import (D, WEEKDAY_NAMES, bad_request, get_body, paginate,
                   pagination_params, parse_date, require_enum, require_int,
                   require_num, require_str)

bp = Blueprint("fleet", __name__)


@bp.post("/routes")
def create_route():
    _, role = auth()
    require_roles(role, "OperationsManager")
    body = get_body()
    route = new_entity(common=True)
    route.update({
        "code": require_str(body, "code"),
        "weekday": require_enum(body, "weekday", WEEKDAYS),
        "max_stops": require_int(body, "max_stops"),
    })
    store["routes"][route["id"]] = route
    return response.ok(ser_route(route), code=201)


@bp.get("/routes/<rid>")
def get_route(rid):
    _, role = auth()
    require_roles(role, "Driver", "OperationsManager")
    route = store["routes"].get(rid)
    if route is None:
        not_found("Route not found")
    return response.ok(ser_route(route))


@bp.post("/routes/<rid>/generate-stops")
def generate_stops(rid):
    _, role = auth()
    require_roles(role, "OperationsManager")
    body = get_body()
    sd = parse_date(body.get("service_date"), "service_date")
    route = store["routes"].get(rid)
    if route is None:
        not_found("Route not found")
    if WEEKDAY_NAMES[sd.weekday()] != route["weekday"]:
        unprocessable(ERR_SERVICE_DATE_WEEKDAY_MISMATCH,
                      "service_date weekday does not match route weekday")
    sd_str = sd.isoformat()
    pickup_ids = []
    for sub in by_seq(store["subscriptions"].values()):
        if (sub["route_id"] != rid or sub["service_status"] != "ACTIVE"
                or sub["start_date"] > sd_str):
            continue
        covered = any(p["subscription_id"] == sub["id"]
                      and p["service_date"] == sd_str
                      for p in store["pickups"].values())
        if covered:
            continue
        p = new_entity(common=True)
        p.update({
            "subscription_id": sub["id"], "route_id": rid,
            "service_date": sd_str, "status": "SCHEDULED",
            "fullness_pct": None, "estimated_kg": None, "final_kg": None,
            "collected_bin_id": None, "replacement_bin_id": None,
            "_earned_cents": 0, "_forfeited": 0,
        })
        store["pickups"][p["id"]] = p
        pickup_ids.append(p["id"])
    return response.ok({"created_count": len(pickup_ids),
                        "pickup_ids": pickup_ids})


@bp.post("/routes/<rid>/weigh-tickets")
def create_weigh_ticket(rid):
    _, role = auth()
    require_roles(role, "Driver", "OperationsManager")
    body = get_body()
    sd = parse_date(body.get("service_date"), "service_date")
    gross = require_num(body, "gross_kg")
    tare = require_num(body, "tare_kg")
    route = store["routes"].get(rid)
    if route is None:
        not_found("Route not found")
    ticket = post_weigh_ticket(route, sd.isoformat(), gross, tare)
    return response.ok(ser_weigh_ticket(ticket), code=201)


@bp.get("/weigh-tickets")
def list_weigh_tickets():
    _, role = auth()
    require_roles(role, "Driver", "OperationsManager")
    limit, offset = pagination_params()
    items = by_seq(store["weigh_tickets"].values())
    val = request.args.get("route_id")
    if val is not None:
        items = [w for w in items if w["route_id"] == val]
    page, total = paginate(items, limit, offset)
    return response.ok_list([ser_weigh_ticket(w) for w in page], limit,
                            offset, total)


@bp.get("/weigh-tickets/<wid>")
def get_weigh_ticket(wid):
    _, role = auth()
    require_roles(role, "Driver", "OperationsManager")
    w = store["weigh_tickets"].get(wid)
    if w is None:
        not_found("Weigh ticket not found")
    return response.ok(ser_weigh_ticket(w))


# ---------------------------------------------------------------------------
# Bins
# ---------------------------------------------------------------------------
@bp.post("/bins")
def create_bin():
    _, role = auth()
    require_roles(role, "OperationsManager")
    body = get_body()
    b = new_entity(common=True)
    b.update({
        "bin_type": require_enum(body, "bin_type", BIN_TYPES),
        "nominal_capacity_kg": D(require_num(body, "nominal_capacity_kg")),
        "status": "IN_DEPOT", "condition": "CLEAN",
        "current_subscription_id": None,
    })
    store["bins"][b["id"]] = b
    return response.ok(ser_bin(b), code=201)


@bp.get("/bins")
def list_bins():
    _, role = auth()
    require_roles(role, "Driver", "OperationsManager")
    limit, offset = pagination_params()
    items = by_seq(store["bins"].values())
    for param, field in (("current_subscription_id", "current_subscription_id"),
                         ("status", "status"), ("condition", "condition")):
        val = request.args.get(param)
        if val is not None:
            items = [b for b in items if b[field] == val]
    page, total = paginate(items, limit, offset)
    return response.ok_list([ser_bin(b) for b in page], limit, offset, total)


@bp.get("/bins/<bid>")
def get_bin(bid):
    _, role = auth()
    require_roles(role, "Driver", "OperationsManager")
    b = store["bins"].get(bid)
    if b is None:
        not_found("Bin not found")
    return response.ok(ser_bin(b))


@bp.post("/bins/<bid>/wash")
def wash_bin(bid):
    _, role = auth()
    require_roles(role, "OperationsManager")
    b = store["bins"].get(bid)
    if b is None:
        not_found("Bin not found")
    if not (b["status"] == "IN_DEPOT" and b["condition"] == "NEEDS_WASH"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Wash requires status IN_DEPOT and condition NEEDS_WASH")
    b["condition"] = "CLEAN"
    touch(b)
    return response.ok(ser_bin(b))
