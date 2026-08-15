"""Site configuration endpoints (PRD 3.1) plus the operations dashboard."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import list_response, public
from services.core import new_record, recompute_site_mirrors
from validate import get_body, req_str, req_int, require_path_resource

bp = Blueprint("sites", __name__)


@bp.post("/sites")
def create_site():
    authorized(["GeneralManager"])
    body = get_body()
    name = req_str(body, "name")
    parking_total = req_int(body, "parking_total_spaces", non_negative=True)
    parking_paid = req_int(body, "parking_paid_capacity", non_negative=True)
    showers = req_int(body, "shower_units_count", non_negative=True)
    laundry = req_int(body, "laundry_machines_count", non_negative=True)
    if parking_paid > parking_total:
        raise_error(ERR_INVALID_REQUEST,
                    "parking_paid_capacity must be <= parking_total_spaces")
    rec = new_record("sites", {
        "name": name,
        "parking_total_spaces": parking_total,
        "parking_paid_capacity": parking_paid,
        "shower_units_count": showers,
        "laundry_machines_count": laundry,
        "diesel_retail_cents_per_gallon": None,
        "gas_regular_retail_cents_per_gallon": None,
        "def_retail_cents_per_gallon": None,
        "water_usage_gallons": 0.0,
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<rid>")
def get_site(rid):
    authorized(ALL_ROLES)
    site = require_path_resource("sites", rid)
    # Mirrors are derived from the logical clock: recompute lazily on read
    # (a pure derivation — no version bump; PRD 3.1)
    recompute_site_mirrors(site)
    return success_object(public(site))


@bp.get("/sites")
def list_sites():
    authorized(ALL_ROLES)
    for site in db["sites"].values():
        recompute_site_mirrors(site)
    return list_response("sites")


@bp.get("/sites/<rid>/dashboard")
def site_dashboard(rid):
    authorized(["GeneralManager", "ShiftManager", "FuelDeskLead"])
    site = require_path_resource("sites", rid)
    sid = site["id"]
    pumps = [p for p in db["pumps"].values() if p["site_id"] == sid]
    data = {
        "pumps_total": len(pumps),
        "pumps_in_use": len([p for p in pumps if p["status"] == "IN_USE"]),
        "parking_active_count": len([r for r in db["parking_reservations"].values()
                                     if r["site_id"] == sid and r["status"] == "ACTIVE"]),
        "shower_queue_depth": len([t for t in db["service_tickets"].values()
                                   if t["site_id"] == sid and t["service_type"] == "SHOWER"
                                   and t["status"] == "QUEUED"]),
        "laundry_queue_depth": len([t for t in db["service_tickets"].values()
                                    if t["site_id"] == sid and t["service_type"] == "LAUNDRY"
                                    and t["status"] == "QUEUED"]),
        "low_stock_count": len([i for i in db["stock_items"].values()
                                if i["site_id"] == sid and i["is_low_stock"]]),
    }
    return success_object(data)
