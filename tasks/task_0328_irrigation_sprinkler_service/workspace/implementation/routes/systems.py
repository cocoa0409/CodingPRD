"""IrrigationSystem and Zone routes (PRD §3.2, §3.5, §3.8)."""
from flask import Blueprint, request

from db import db, LOCK, stamp_new
import domain
import errors
import lookups
from cascades import decommission_system
from domain import serialize
from errors import fail
from listing import list_response
from middleware import get_auth, require_role
from response import success
from validation import get_body, require_str, require_int, require_enum, optional_bool

bp = Blueprint("systems", __name__)

PLANT_TYPES = {"TURF", "SHRUB", "DRIP", "ROTOR"}


# ---------------- IrrigationSystem ----------------
@bp.route("/irrigation-systems", methods=["POST"])
def create_system():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        property_id = require_str(body, "property_id")
        lookups.get_property(property_id)
        controller_model = require_str(body, "controller_model")
        static_psi = require_int(body, "static_psi", minimum=0, maximum=200)
        has_backflow_device = optional_bool(body, "has_backflow_device", default=False)
        rec = {
            "property_id": property_id,
            "controller_model": controller_model,
            "static_psi": static_psi,
            "has_backflow_device": has_backflow_device,
            "season_state": "DORMANT",
            "backflow_status": "UNTESTED",
            "lifecycle_state": "OPERATIONAL",
            "zone_count": 0,
            "committed_cost_cents": 0,
            "provisional_winter_risk": 0,
            "assessed_winter_risk": 0,
        }
        stamp_new(rec)
        db.irrigation_systems[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/irrigation-systems/<sid>", methods=["GET"])
def get_system(sid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer", "Technician"})
    with LOCK:
        rec = lookups.get_system(sid)
        return success(serialize(rec), status=200)


@bp.route("/irrigation-systems", methods=["GET"])
def list_systems():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer", "Technician"})
    with LOCK:
        rows = list(db.irrigation_systems.values())
        property_id = request.args.get("property_id")
        if property_id is not None:
            rows = [s for s in rows if s["property_id"] == property_id]
        return list_response(rows)


@bp.route("/irrigation-systems/<sid>/blowout-quote", methods=["GET"])
def blowout_quote(sid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer"})
    with LOCK:
        system = lookups.get_system(sid)
        zone_count = system["zone_count"]
        price = domain.blowout_price(zone_count, system["static_psi"])
        return success(
            {
                "system_id": system["id"],
                "zone_count": zone_count,
                "blowout_price_cents": price,
            },
            status=200,
        )


@bp.route("/irrigation-systems/<sid>/decommission", methods=["POST"])
def decommission(sid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        system = lookups.get_system(sid)
        if system["lifecycle_state"] != "OPERATIONAL":
            fail(errors.ERR_SYSTEM_ALREADY_DECOMMISSIONED, "System already decommissioned")
        decommission_system(system)
        return success(serialize(system), status=200)


# ---------------- Zone ----------------
@bp.route("/zones", methods=["POST"])
def create_zone():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician"})
    with LOCK:
        body = get_body()
        system_id = require_str(body, "system_id")
        system = lookups.get_system(system_id)
        zone_number = require_int(body, "zone_number", minimum=1)
        plant_type = require_enum(body, "plant_type", PLANT_TYPES)
        head_count = require_int(body, "head_count", minimum=1)
        gpm_per_head = require_int(body, "gpm_per_head", minimum=1)
        # ERR_DUPLICATE_ZONE_NUMBER (priority 10) — unique among non-ARCHIVED zones
        for z in domain.zones_of_system(system_id):
            if z["zone_state"] != "ARCHIVED" and z["zone_number"] == zone_number:
                fail(errors.ERR_DUPLICATE_ZONE_NUMBER, "zone_number already in use on this system")
        rec = {
            "system_id": system_id,
            "zone_number": zone_number,
            "plant_type": plant_type,
            "head_count": head_count,
            "gpm_per_head": gpm_per_head,
            "zone_state": "MAPPED",
        }
        stamp_new(rec)
        db.zones[rec["id"]] = rec
        # A new MAPPED zone changes zone_count and winter-risk exposure.
        domain.recompute_system_derived(system)
        return success(serialize(rec), status=201)


@bp.route("/zones/<zid>", methods=["GET"])
def get_zone(zid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer", "Technician"})
    with LOCK:
        rec = lookups.get_zone(zid)
        return success(serialize(rec), status=200)


@bp.route("/zones", methods=["GET"])
def list_zones():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer", "Technician"})
    with LOCK:
        rows = list(db.zones.values())
        system_id = request.args.get("system_id")
        if system_id is not None:
            rows = [z for z in rows if z["system_id"] == system_id]
        return list_response(rows)
