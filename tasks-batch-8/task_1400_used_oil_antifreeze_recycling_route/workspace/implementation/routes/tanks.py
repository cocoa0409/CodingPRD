"""Tank endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_SITE_STILL_CONTAMINATED,
    ERR_TANK_HAS_ACTIVE_STOPS,
    ERR_TANK_NOT_COMPANY_OWNED,
    ERR_TANK_NOT_CUSTOMER_OWNED,
    ERR_TANK_NOT_EMPTY,
    ERR_TANK_NOT_FOUND,
    ERR_TANK_NOT_PENDING_DECOMMISSION,
    ERR_TANK_NOT_PENDING_INSTALL,
    ERR_TANK_NOT_QUARANTINED,
    ERR_TANK_OVERFLOW,
    ERR_TANK_SITE_NOT_FOUND,
)
from middleware import get_body, opt_int, req_enum, req_int, req_str, require_roles
from response import success_list, success_object
from services import cascades

bp = Blueprint("tanks", __name__)

TANK_KINDS = {"USED_OIL", "ANTIFREEZE", "MIXED"}
OWNERSHIPS = {"COMPANY_OWNED", "CUSTOMER_OWNED"}
READ_ROLES = ("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator", "TankInstaller", "Driver")


def get_tank_or_404(tank_id):
    tank = db.get("tanks", tank_id)
    if tank is None:
        raise ApiError(ERR_TANK_NOT_FOUND, "Tank id not found", 404)
    return tank


@bp.post("/tanks")
@require_roles("TankInstaller")
def create_tank():
    body = get_body()
    tank_site_id = req_str(body, "tank_site_id")
    tank_kind = req_enum(body, "tank_kind", TANK_KINDS)
    capacity_gallons = req_int(body, "capacity_gallons", minimum=1)
    ownership = req_enum(body, "ownership", OWNERSHIPS)
    oil_share_pct = opt_int(body, "oil_share_pct", None, minimum=0, maximum=100)
    site = db.get("tank_sites", tank_site_id)
    if site is None:
        raise ApiError(ERR_TANK_SITE_NOT_FOUND, "TankSite id not found", 404)
    tank = db.create_entity("tanks", {
        "tank_site_id": tank_site_id,
        "tank_kind": tank_kind,
        "capacity_gallons": capacity_gallons,
        "current_volume_gallons": 0,
        "ownership": ownership,
        "installed_at": None,
        "ownership_status": "PENDING_INSTALL",
        "quarantine_status": "CLEAR",
        "_oil_share_pct": oil_share_pct,
        "_was_quarantined": False,
    })
    return success_object(db.serialize(tank), 201)


@bp.get("/tanks")
@require_roles(*READ_ROLES)
def list_tanks():
    items = db.all_entities("tanks")
    tank_site_id = request.args.get("tank_site_id")
    ownership_status = request.args.get("ownership_status")
    quarantine_status = request.args.get("quarantine_status")
    if tank_site_id is not None:
        items = [t for t in items if t["tank_site_id"] == tank_site_id]
    if ownership_status is not None:
        items = [t for t in items if t["ownership_status"] == ownership_status]
    if quarantine_status is not None:
        items = [t for t in items if t["quarantine_status"] == quarantine_status]
    return success_list([db.serialize(t) for t in db.sorted_created(items)])


@bp.get("/tanks/<tankId>")
@require_roles(*READ_ROLES)
def get_tank(tankId):
    return success_object(db.serialize(get_tank_or_404(tankId)))


@bp.post("/tanks/<tankId>/install")
@require_roles("TankInstaller")
def install_tank(tankId):
    tank = get_tank_or_404(tankId)
    if tank["ownership_status"] != "PENDING_INSTALL":
        raise ApiError(ERR_TANK_NOT_PENDING_INSTALL, "Tank not in PENDING_INSTALL", 409)
    if tank["ownership"] != "COMPANY_OWNED":
        raise ApiError(ERR_TANK_NOT_COMPANY_OWNED, "Install endpoint requires COMPANY_OWNED tank", 409)
    tank["installed_at"] = db.now_iso()
    tank["ownership_status"] = "INSTALLED"
    db.touch(tank)
    return success_object(db.serialize(tank))


@bp.post("/tanks/<tankId>/register-existing")
@require_roles("TankInstaller")
def register_existing_tank(tankId):
    tank = get_tank_or_404(tankId)
    if tank["ownership_status"] != "PENDING_INSTALL":
        raise ApiError(ERR_TANK_NOT_PENDING_INSTALL, "Tank not in PENDING_INSTALL", 409)
    if tank["ownership"] != "CUSTOMER_OWNED":
        raise ApiError(ERR_TANK_NOT_CUSTOMER_OWNED, "Register-existing requires CUSTOMER_OWNED tank", 409)
    tank["installed_at"] = db.now_iso()
    tank["ownership_status"] = "INSTALLED"
    db.touch(tank)
    return success_object(db.serialize(tank))


@bp.post("/tanks/<tankId>/decommission")
@require_roles("TankInstaller")
def decommission_tank(tankId):
    tank = get_tank_or_404(tankId)
    if tank["ownership_status"] != "INSTALLED":
        raise ApiError(
            ERR_TANK_NOT_PENDING_INSTALL,
            "Decommission requires an INSTALLED tank",
            409,
        )
    if tank["current_volume_gallons"] != 0:
        raise ApiError(ERR_TANK_NOT_EMPTY, "Decommission requires current_volume_gallons == 0", 409)
    for stop in db.all_entities("route_stops"):
        if stop["tank_id"] == tank["id"] and stop["status"] in cascades.NON_TERMINAL_STOP_STATES:
            raise ApiError(ERR_TANK_HAS_ACTIVE_STOPS, "Tank has non-terminal RouteStops", 409)
    tank["ownership_status"] = "DECOMMISSION_PENDING"
    db.touch(tank)
    return success_object(db.serialize(tank))


@bp.post("/tanks/<tankId>/decommission-confirm")
@require_roles("TankInstaller")
def decommission_confirm(tankId):
    tank = get_tank_or_404(tankId)
    if tank["ownership_status"] != "DECOMMISSION_PENDING":
        raise ApiError(
            ERR_TANK_NOT_PENDING_DECOMMISSION,
            "Decommission-confirm requires DECOMMISSION_PENDING",
            409,
        )
    tank["ownership_status"] = "DECOMMISSIONED"
    db.touch(tank)
    return success_object(db.serialize(tank))


@bp.post("/tanks/<tankId>/clear-quarantine")
@require_roles("EHSOfficer")
def clear_quarantine(tankId):
    tank = get_tank_or_404(tankId)
    if tank["quarantine_status"] != "QUARANTINED":
        raise ApiError(ERR_TANK_NOT_QUARANTINED, "Clear-quarantine requires QUARANTINED", 409)
    site = db.get("tank_sites", tank["tank_site_id"])
    if site is not None and site["status"] == "CONTAMINATED":
        raise ApiError(ERR_SITE_STILL_CONTAMINATED, "TankSite still CONTAMINATED", 409)
    tank["quarantine_status"] = "CLEAR"
    db.touch(tank)
    return success_object(db.serialize(tank))


@bp.post("/tanks/<tankId>/record-intake")
@require_roles("Driver", "RoutePlanner")
def record_intake(tankId):
    tank = get_tank_or_404(tankId)
    body = get_body()
    gallons = req_int(body, "gallons", minimum=1)
    if tank["current_volume_gallons"] + gallons > tank["capacity_gallons"]:
        raise ApiError(ERR_TANK_OVERFLOW, "Intake would exceed capacity_gallons", 409)
    tank["current_volume_gallons"] += gallons
    db.touch(tank)
    return success_object(db.serialize(tank))
