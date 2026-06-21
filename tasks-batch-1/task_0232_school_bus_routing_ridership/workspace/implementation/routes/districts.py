"""District endpoints (PRD §3.1, §3.11)."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok
from services import validate as v
from services.common import stamp_create, touch
from services.domain import district_public
from services.lookup import get_district

bp = Blueprint("districts", __name__)


@bp.post("/districts")
def create_district():
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    body = v.get_body()

    name = v.require_str(body, "name")
    school_lat = v.require_number(body, "school_lat")
    school_lng = v.require_number(body, "school_lng")
    walk_threshold_miles = v.optional_number(body, "walk_threshold_miles", 1.5)
    hazard_override_enabled = v.optional_bool(body, "hazard_override_enabled", True)
    missed_bus_grace_minutes = v.optional_int(body, "missed_bus_grace_minutes", 10)

    rec = {
        "name": name,
        "school_lat": school_lat,
        "school_lng": school_lng,
        "walk_threshold_miles": walk_threshold_miles,
        "hazard_override_enabled": hazard_override_enabled,
        "missed_bus_grace_minutes": missed_bus_grace_minutes,
        "service_day_index": 0,
    }
    stamp_create(rec)
    DB.districts[rec["id"]] = rec
    return ok(district_public(rec), 201)


@bp.get("/districts/<district_id>")
def get_district_ep(district_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    rec = get_district(district_id)
    return ok(district_public(rec), 200)


@bp.post("/districts/<district_id>/advance-service-day")
def advance_service_day(district_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    rec = get_district(district_id)
    rec["service_day_index"] = rec["service_day_index"] + 1
    touch(rec)
    return ok(district_public(rec), 200)
