"""Shelter and ShelterUnit endpoints."""

from flask import Blueprint

from db import public
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_HOUSING_SPECIALIST,
                        ROLE_SHELTER_MANAGER, auth)
from response import created, ok
from routes.common import filtered, get_shelter, get_unit, insert, list_page
from services import derive
from validation import (get_body, opt_bool, opt_int, q_enum, q_str, req_enum, req_int,
                        req_str)

bp = Blueprint("shelters", __name__)

UNIT_TYPES = ("STANDARD", "ADA_ACCESSIBLE", "FAMILY_SUITE")
UNIT_STATUSES = ("AVAILABLE", "HOLD", "OCCUPIED")


@bp.post("/shelters")
def create_shelter():
    auth((ROLE_SHELTER_MANAGER, ROLE_AGENCY_ADMIN))
    body = get_body()
    name = req_str(body, "name", 1, 120)
    confidential_location = opt_bool(body, "confidential_location", True)
    nightly_rate_cents = req_int(body, "nightly_rate_cents", 1000, 100000)
    weekend_surcharge_cents = opt_int(body, "weekend_surcharge_cents", 0, 0, 50000)
    child_supplement_cents = opt_int(body, "child_supplement_cents", 0, 0, 50000)

    shelter = insert("shelters", {
        "name": name,
        "confidential_location": confidential_location,
        "nightly_rate_cents": nightly_rate_cents,
        "weekend_surcharge_cents": weekend_surcharge_cents,
        "child_supplement_cents": child_supplement_cents,
        "total_bed_capacity": 0,
        "available_beds": 0,
        "capacity_posture": "FULL",
        "settled_revenue_cents": 0,
    })
    return created(public(shelter))


@bp.get("/shelters/<shelter_id>")
def read_shelter(shelter_id):
    auth((ROLE_SHELTER_MANAGER, ROLE_HOTLINE_ADVOCATE, ROLE_HOUSING_SPECIALIST,
          ROLE_AGENCY_ADMIN))
    return ok(public(get_shelter(shelter_id)))


@bp.post("/shelters/<shelter_id>/units")
def create_unit(shelter_id):
    auth((ROLE_SHELTER_MANAGER, ROLE_AGENCY_ADMIN))
    body = get_body()
    unit_label = req_str(body, "unit_label", 1, 20)
    unit_type = req_enum(body, "unit_type", UNIT_TYPES)
    bed_capacity = req_int(body, "bed_capacity", 1, 8)
    shelter = get_shelter(shelter_id)

    for existing in derive.where("shelter_units", shelter_id=shelter["id"]):
        if existing["unit_label"] == unit_label:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "unit_label is already used in this shelter")

    unit = insert("shelter_units", {
        "shelter_id": shelter["id"],
        "unit_label": unit_label,
        "unit_type": unit_type,
        "bed_capacity": bed_capacity,
        "reserved_beds": 0,
        "occupied_beds": 0,
        "available_beds": bed_capacity,
        "status": "AVAILABLE",
    })
    derive.shelter_rollup(shelter)
    return created(public(unit))


@bp.get("/shelters/<shelter_id>/units")
def list_units(shelter_id):
    auth((ROLE_SHELTER_MANAGER, ROLE_HOTLINE_ADVOCATE, ROLE_AGENCY_ADMIN))
    shelter = get_shelter(shelter_id)
    filters = {
        "shelter_id": shelter["id"],
        "unit_label": q_str("unit_label"),
        "unit_type": q_enum("unit_type", UNIT_TYPES),
        "status": q_enum("status", UNIT_STATUSES),
    }
    rows = sorted(filtered("shelter_units", filters),
                  key=lambda r: (r["unit_label"], r["_seq"]))
    return list_page(rows)


@bp.get("/shelter-units/<unit_id>")
def read_unit(unit_id):
    auth((ROLE_SHELTER_MANAGER, ROLE_HOTLINE_ADVOCATE, ROLE_AGENCY_ADMIN))
    return ok(public(get_unit(unit_id)))
