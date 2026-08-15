"""Site inventory registration + market-survey list."""
from flask import Blueprint

from db import store, new_entity, public
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import (
    authenticate, body, require_fields, check_enums, get_path,
    PARCEL_TYPES, ENV_PHASES, ALL_ROLES,
)
from response import success_object
from routes import list_response
from services.calc import D

bp = Blueprint("sites", __name__)


@bp.post("/api/sites")
def create_site():
    authenticate(["LeasingManager"])
    b = body()
    require_fields(b, [
        ("site_name", "string", True),
        ("submarket", "string", True),
        ("parcel_type", "string", True),
        ("total_sf", "int", True),
        ("clear_height_ft", "number", True),
        ("dock_doors", "int", True),
        ("power_amps", "int", True),
        ("yard_depth_ft", "int", True),
        ("zoning_designation", "string", True),
        ("environmental_phase", "string", True),
        ("asking_rate_psf", "number", True),
    ])
    check_enums(b, [
        ("parcel_type", PARCEL_TYPES),
        ("environmental_phase", ENV_PHASES),
    ])
    # total_sf must be > 0 and is immutable after registration (PRD §3.1).
    if b["total_sf"] <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "total_sf must be greater than zero", 400)
    ent = new_entity({
        "site_name": b["site_name"],
        "submarket": b["submarket"],
        "parcel_type": b["parcel_type"],
        "total_sf": b["total_sf"],
        "clear_height_ft": D(b["clear_height_ft"]),
        "dock_doors": b["dock_doors"],
        "power_amps": b["power_amps"],
        "yard_depth_ft": b["yard_depth_ft"],
        "zoning_designation": b["zoning_designation"],
        "environmental_phase": b["environmental_phase"],
        "asking_rate_psf": D(b["asking_rate_psf"]),
        "reserved_sf": 0,
        "available_sf": b["total_sf"],
        "status": "LISTED",
    })
    store.sites[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/api/sites")
def list_sites():
    authenticate(ALL_ROLES)
    return list_response(store.sites.values(), [
        ("submarket", lambda e: e["submarket"]),
        ("status", lambda e: e["status"]),
        ("parcel_type", lambda e: e["parcel_type"]),
    ])


@bp.get("/api/sites/<sid>")
def get_site(sid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.sites, sid, "site")))
