"""TankSite endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CUSTOMER_NOT_ACTIVE,
    ERR_OPEN_SPILL_EXISTS,
    ERR_SITE_HAS_ACTIVE_STOPS,
    ERR_SITE_NOT_ACTIVE,
    ERR_TANK_SITE_NOT_FOUND,
)
from middleware import get_body, opt_bool, req_enum, req_str, require_roles
from response import success_list, success_object
from services import cascades

bp = Blueprint("tank_sites", __name__)

DENSITY_ZONES = {"URBAN", "SUBURBAN", "RURAL"}
READ_ROLES = ("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator", "TankInstaller", "Driver")
SPILL_TERMINAL_STATES = {"REMEDIATED", "CLOSED_NO_ACTION", "CLOSED_WITH_LIABILITY"}


def get_site_or_404(tank_site_id):
    site = db.get("tank_sites", tank_site_id)
    if site is None:
        raise ApiError(ERR_TANK_SITE_NOT_FOUND, "TankSite id not found", 404)
    return site


@bp.post("/tank-sites")
@require_roles("RoutePlanner")
def create_tank_site():
    body = get_body()
    customer_id = req_str(body, "customer_id")
    site_address = req_str(body, "site_address")
    density_zone = req_enum(body, "density_zone", DENSITY_ZONES)
    override = opt_bool(body, "route_eligibility_override", False)
    customer = db.get("customers", customer_id)
    if customer is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", "Customer id not found", 404)
    site = db.create_entity("tank_sites", {
        "customer_id": customer_id,
        "site_address": site_address,
        "density_zone": density_zone,
        "route_eligibility_override": override,
        "status": "ACTIVE",
        "_inactivated_by_cascade": False,
    })
    return success_object(db.serialize(site), 201)


@bp.get("/tank-sites")
@require_roles(*READ_ROLES)
def list_tank_sites():
    items = db.all_entities("tank_sites")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return success_list([db.serialize(s) for s in db.sorted_created(items)])


@bp.get("/tank-sites/<tankSiteId>")
@require_roles(*READ_ROLES)
def get_tank_site(tankSiteId):
    return success_object(db.serialize(get_site_or_404(tankSiteId)))


@bp.post("/tank-sites/<tankSiteId>/activate")
@require_roles("RoutePlanner")
def activate_tank_site(tankSiteId):
    site = get_site_or_404(tankSiteId)
    if site["status"] != "INACTIVE":
        raise ApiError(ERR_SITE_NOT_ACTIVE, "Activate requires an INACTIVE TankSite", 409)
    customer = cascades.customer_of_site(site)
    if customer is None or customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_NOT_ACTIVE, "Operation requires ACTIVE customer", 409)
    site["status"] = "ACTIVE"
    site["_inactivated_by_cascade"] = False
    db.touch(site)
    return success_object(db.serialize(site))


@bp.post("/tank-sites/<tankSiteId>/deactivate")
@require_roles("RoutePlanner")
def deactivate_tank_site(tankSiteId):
    site = get_site_or_404(tankSiteId)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_SITE_NOT_ACTIVE, "Deactivate requires an ACTIVE TankSite", 409)
    for stop in db.all_entities("route_stops"):
        if stop["tank_site_id"] == site["id"] and stop["status"] in cascades.NON_TERMINAL_STOP_STATES:
            raise ApiError(
                ERR_SITE_HAS_ACTIVE_STOPS,
                "TankSite has non-terminal RouteStops",
                409,
            )
    site["status"] = "INACTIVE"
    site["_inactivated_by_cascade"] = False
    db.touch(site)
    return success_object(db.serialize(site))


@bp.post("/tank-sites/<tankSiteId>/certify-clean")
@require_roles("EHSOfficer")
def certify_clean(tankSiteId):
    site = get_site_or_404(tankSiteId)
    if site["status"] != "CONTAMINATED":
        raise ApiError(ERR_SITE_NOT_ACTIVE, "Certify-clean requires a CONTAMINATED TankSite", 409)
    for spill in db.all_entities("spill_incidents"):
        if spill["tank_site_id"] == site["id"] and spill["status"] not in SPILL_TERMINAL_STATES:
            raise ApiError(ERR_OPEN_SPILL_EXISTS, "Open spill blocks the operation", 409)
    site["status"] = "ACTIVE"
    db.touch(site)
    for tank in cascades.tanks_of_site(site["id"]):
        if tank["quarantine_status"] != "CLEAR":
            tank["quarantine_status"] = "CLEAR"
            db.touch(tank)
    return success_object(db.serialize(site))


@bp.get("/tank-sites/<tankSiteId>/tanks")
@require_roles(*READ_ROLES)
def list_site_tanks(tankSiteId):
    get_site_or_404(tankSiteId)
    items = cascades.tanks_of_site(tankSiteId)
    return success_list([db.serialize(t) for t in db.sorted_created(items)])
