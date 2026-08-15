"""SpillIncident endpoints (PRD §3.9)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_ROUTE_NOT_FOUND,
    ERR_SPILL_NOT_FOUND,
    ERR_SPILL_NOT_OPEN,
    ERR_SPILL_NOT_REMEDIATED,
    ERR_SPILL_NOT_UNDER_INVESTIGATION,
    ERR_TANK_SITE_NOT_FOUND,
)
from middleware import get_body, req_enum, req_int, req_str, require_roles
from response import success_list, success_object
from services import cascades
from services.calc import RQ_THRESHOLD_GALLONS, spill_liability

bp = Blueprint("spills", __name__)

CAUSE_CODES = {"EQUIPMENT_FAILURE", "CUSTOMER_OVERFILL", "DRIVER_ERROR", "THIRD_PARTY", "UNKNOWN"}
READ_ROLES = ("RoutePlanner", "EHSOfficer", "Regulator")


def get_spill_or_404(spill_id):
    spill = db.get("spill_incidents", spill_id)
    if spill is None:
        raise ApiError(ERR_SPILL_NOT_FOUND, "SpillIncident id not found", 404)
    return spill


def _site_tank_ownership(site_id):
    """Ownership basis for EQUIPMENT_FAILURE attribution: company is liable
    when any tank at the site is company-owned."""
    for tank in cascades.tanks_of_site(site_id):
        if tank["ownership"] == "COMPANY_OWNED":
            return "COMPANY_OWNED"
    return "CUSTOMER_OWNED"


@bp.post("/spill-incidents")
@require_roles("Driver", "EHSOfficer")
def create_spill():
    body = get_body()
    route_id = req_str(body, "route_id")
    tank_site_id = req_str(body, "tank_site_id")
    gallons_spilled = req_int(body, "gallons_spilled", minimum=1)
    cause_code = req_enum(body, "cause_code", CAUSE_CODES)
    route = db.get("routes", route_id)
    if route is None:
        raise ApiError(ERR_ROUTE_NOT_FOUND, "Route id not found", 404)
    site = db.get("tank_sites", tank_site_id)
    if site is None:
        raise ApiError(ERR_TANK_SITE_NOT_FOUND, "TankSite id not found", 404)
    if request.user_role == "Driver" and route["driver_id"] != request.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Driver may only act on routes assigned to them",
            403,
        )
    rq_exceeded = gallons_spilled >= RQ_THRESHOLD_GALLONS
    spill = db.create_entity("spill_incidents", {
        "route_id": route_id,
        "tank_site_id": tank_site_id,
        "reported_by_user_id": request.user_id,
        "gallons_spilled": gallons_spilled,
        "reportable_quantity_exceeded": rq_exceeded,
        "liability_cents": None,
        "responsible_party": None,
        "cause_code": cause_code,
        "status": "OPEN",
        "_customer_share_cents": 0,
    })
    if rq_exceeded:
        cascades.contaminate_site(site)
    return success_object(db.serialize(spill), 201)


@bp.get("/spill-incidents")
@require_roles(*READ_ROLES)
def list_spills():
    items = db.all_entities("spill_incidents")
    for param in ("status", "tank_site_id", "route_id"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s[param] == value]
    return success_list([db.serialize(s) for s in db.sorted_created(items)])


@bp.get("/spill-incidents/<spillId>")
@require_roles(*READ_ROLES)
def get_spill(spillId):
    return success_object(db.serialize(get_spill_or_404(spillId)))


@bp.post("/spill-incidents/<spillId>/begin-investigation")
@require_roles("EHSOfficer")
def begin_investigation(spillId):
    spill = get_spill_or_404(spillId)
    if spill["status"] != "OPEN":
        raise ApiError(ERR_SPILL_NOT_OPEN, "Begin-investigation requires OPEN", 409)
    spill["status"] = "UNDER_INVESTIGATION"
    db.touch(spill)
    if spill["reportable_quantity_exceeded"]:
        site = db.get("tank_sites", spill["tank_site_id"])
        if site is not None:
            cascades.contaminate_site(site)
    return success_object(db.serialize(spill))


@bp.post("/spill-incidents/<spillId>/remediate")
@require_roles("EHSOfficer")
def remediate_spill(spillId):
    spill = get_spill_or_404(spillId)
    if spill["status"] != "UNDER_INVESTIGATION":
        raise ApiError(ERR_SPILL_NOT_UNDER_INVESTIGATION, "Remediate requires UNDER_INVESTIGATION", 409)
    liability, party, customer_share = spill_liability(
        spill["gallons_spilled"],
        spill["cause_code"],
        _site_tank_ownership(spill["tank_site_id"]),
        spill["reportable_quantity_exceeded"],
    )
    spill["liability_cents"] = liability
    spill["responsible_party"] = party
    spill["_customer_share_cents"] = customer_share
    spill["status"] = "REMEDIATED"
    db.touch(spill)
    return success_object(db.serialize(spill))


@bp.post("/spill-incidents/<spillId>/close")
@require_roles("EHSOfficer")
def close_spill(spillId):
    spill = get_spill_or_404(spillId)
    if spill["status"] != "REMEDIATED":
        raise ApiError(ERR_SPILL_NOT_REMEDIATED, "Close requires REMEDIATED", 409)
    if spill["liability_cents"] and spill["liability_cents"] > 0:
        spill["status"] = "CLOSED_WITH_LIABILITY"
        if spill["responsible_party"] in ("CUSTOMER", "SHARED"):
            site = db.get("tank_sites", spill["tank_site_id"])
            customer = cascades.customer_of_site(site) if site else None
            if customer is not None:
                customer["outstanding_charge_cents"] += spill["_customer_share_cents"]
                db.touch(customer)
    else:
        spill["status"] = "CLOSED_NO_ACTION"
    db.touch(spill)
    return success_object(db.serialize(spill))
