"""RouteStop field-execution endpoints (PRD §3.4): arrive, begin-screening,
cancel-by-customer, skip-below-minimum, plus nested collection reads."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_DUPLICATE_CLIENT_REQUEST,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_ROUTE_NOT_DISPATCHED,
    ERR_ROUTE_STOP_NOT_FOUND,
    ERR_SITE_NOT_ACTIVE,
    ERR_SITE_OVERRIDE_ACTIVE,
    ERR_STOP_NOT_CANCELLABLE,
    ERR_STOP_NOT_EN_ROUTE,
    ERR_STOP_NOT_READY_TO_PUMP,
    ERR_STOP_NOT_SCHEDULED,
    ERR_TANK_QUARANTINED,
    ERR_VOLUME_ABOVE_MINIMUM,
)
from middleware import get_body, req_str, require_roles
from response import success_list, success_object
from services import cascades
from services.calc import ZONE_MINIMUM_GALLONS, market_price_or_none, settlement_calc

bp = Blueprint("route_stops", __name__)

READ_ROLES = ("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator", "Driver")


def get_stop_or_404(route_stop_id):
    stop = db.get("route_stops", route_stop_id)
    if stop is None:
        raise ApiError(ERR_ROUTE_STOP_NOT_FOUND, "RouteStop id not found", 404)
    return stop


def check_driver_owns_route(stop):
    """Entity-backed Driver identity (PRD §2.1): driver-executed mutations on a
    route compare the route's driver_id to X-User-ID."""
    route = db.get("routes", stop["route_id"])
    if route is not None and route["driver_id"] != request.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Driver may only act on routes assigned to them",
            403,
        )


@bp.get("/route-stops")
@require_roles(*READ_ROLES)
def list_route_stops():
    items = db.all_entities("route_stops")
    for param in ("route_id", "tank_site_id", "tank_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s[param] == value]
    return success_list([db.serialize(s) for s in db.sorted_created(items)])


@bp.get("/route-stops/<routeStopId>")
@require_roles(*READ_ROLES)
def get_route_stop(routeStopId):
    return success_object(db.serialize(get_stop_or_404(routeStopId)))


@bp.post("/route-stops/<routeStopId>/arrive")
@require_roles("Driver")
def arrive(routeStopId):
    stop = get_stop_or_404(routeStopId)
    check_driver_owns_route(stop)
    if stop["status"] != "SCHEDULED":
        raise ApiError(ERR_STOP_NOT_SCHEDULED, "Arrive requires SCHEDULED", 409)
    route = db.get("routes", stop["route_id"])
    if route is None or route["status"] not in ("DISPATCHED", "IN_PROGRESS"):
        raise ApiError(ERR_ROUTE_NOT_DISPATCHED, "Stop arrival requires route DISPATCHED or IN_PROGRESS", 409)
    tank = db.get("tanks", stop["tank_id"])
    if tank is not None and tank["quarantine_status"] != "CLEAR":
        raise ApiError(ERR_TANK_QUARANTINED, "Tank is quarantined; arrival/screening blocked", 409)
    site = db.get("tank_sites", stop["tank_site_id"])
    if site is None or site["status"] != "ACTIVE":
        raise ApiError(ERR_SITE_NOT_ACTIVE, "TankSite not ACTIVE", 409)
    stop["status"] = "EN_ROUTE"
    db.touch(stop)
    if route["status"] == "DISPATCHED":
        route["status"] = "IN_PROGRESS"
        db.touch(route)
    return success_object(db.serialize(stop))


@bp.post("/route-stops/<routeStopId>/begin-screening")
@require_roles("Driver")
def begin_screening(routeStopId):
    stop = get_stop_or_404(routeStopId)
    check_driver_owns_route(stop)
    if stop["status"] != "EN_ROUTE":
        raise ApiError(ERR_STOP_NOT_EN_ROUTE, "Begin-screening requires EN_ROUTE", 409)
    stop["status"] = "SCREENING"
    db.touch(stop)
    return success_object(db.serialize(stop))


@bp.post("/route-stops/<routeStopId>/cancel-by-customer")
@require_roles("RoutePlanner")
def cancel_by_customer(routeStopId):
    stop = get_stop_or_404(routeStopId)
    if stop["status"] not in ("SCHEDULED", "EN_ROUTE"):
        raise ApiError(ERR_STOP_NOT_CANCELLABLE, "Cancel-by-customer requires SCHEDULED or EN_ROUTE", 409)
    stop["status"] = "CANCELLED_CUSTOMER"
    db.touch(stop)
    return success_object(db.serialize(stop))


@bp.post("/route-stops/<routeStopId>/skip-below-minimum")
@require_roles("Driver")
def skip_below_minimum(routeStopId):
    stop = get_stop_or_404(routeStopId)
    check_driver_owns_route(stop)
    body = get_body()
    client_request_id = req_str(body, "client_request_id")
    if stop["status"] != "READY_TO_PUMP":
        raise ApiError(ERR_STOP_NOT_READY_TO_PUMP, "Skip requires READY_TO_PUMP", 409)
    tank = db.get("tanks", stop["tank_id"])
    site = db.get("tank_sites", stop["tank_site_id"])
    zone_min = ZONE_MINIMUM_GALLONS[site["density_zone"]]
    if tank["current_volume_gallons"] >= zone_min:
        raise ApiError(ERR_VOLUME_ABOVE_MINIMUM, "Skip requires current_volume < zone minimum", 409)
    if site["route_eligibility_override"]:
        raise ApiError(ERR_SITE_OVERRIDE_ACTIVE, "Skip blocked: site has route_eligibility_override = true", 409)
    for ticket in cascades.tickets_for_stop(stop["id"]):
        if ticket["client_request_id"] == client_request_id:
            raise ApiError(ERR_DUPLICATE_CLIENT_REQUEST, "client_request_id already used for this RouteStop", 409)
    route = db.get("routes", stop["route_id"])
    customer = cascades.customer_of_site(site)
    # Zero-volume audit ticket. The skip path never requires a published price;
    # when none exists the snapshot is 0 (net is then zero per the pinned sign rule).
    price = market_price_or_none(
        customer["market_zone"],
        tank["tank_kind"],
        route["scheduled_date"],
        tank.get("_oil_share_pct"),
    )
    frozen = stop.get("_halogen_count_at_screen")
    if frozen is None:
        frozen = customer["halogen_violation_count"]
    calc = settlement_calc(
        price if price is not None else 0,
        0,
        frozen,
        site["density_zone"],
        site["route_eligibility_override"],
    )
    stop["status"] = "SKIPPED_BELOW_MINIMUM"
    db.touch(stop)
    ticket = db.create_entity("pickup_tickets", {
        "route_stop_id": stop["id"],
        "client_request_id": client_request_id,
        "metered_volume_gallons": 0,
        "commodity_price_cents_per_gal": calc["commodity_price_cents_per_gal"],
        "settlement_direction": calc["settlement_direction"],
        "gross_amount_cents": calc["gross_amount_cents"],
        "surcharge_cents": calc["surcharge_cents"],
        "density_fee_cents": calc["density_fee_cents"],
        "net_amount_cents": calc["net_amount_cents"],
        "payment_status": "PROVISIONAL",
        "frozen_halogen_count": frozen,
        "tank_kind": tank["tank_kind"],
        "route_id": route["id"],
        "_was_settled": False,
        "_consumed_by": None,
    })
    return success_object(db.serialize(ticket), 200)


@bp.get("/route-stops/<routeStopId>/sample-screenings")
@require_roles("RoutePlanner", "LabTech", "EHSOfficer", "Regulator", "Driver")
def list_stop_screenings(routeStopId):
    get_stop_or_404(routeStopId)
    items = [s for s in db.all_entities("sample_screenings") if s["route_stop_id"] == routeStopId]
    return success_list([db.serialize(s) for s in db.sorted_created(items)])


@bp.get("/route-stops/<routeStopId>/pickup-tickets")
@require_roles(*READ_ROLES)
def list_stop_tickets(routeStopId):
    get_stop_or_404(routeStopId)
    items = cascades.tickets_for_stop(routeStopId)
    return success_list([db.serialize(t) for t in db.sorted_created(items)])
