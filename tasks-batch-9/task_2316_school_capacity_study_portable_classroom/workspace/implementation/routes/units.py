"""Portable units (two state dimensions) and candidate pads."""

from flask import Blueprint

import constants as C
from db import db, new_record, public, touch
from errors import fail
from middleware import require
from response import created, ok
from routes.common import list_response
from services import cascade
from services.feasibility import assess
from validation import (
    get_body, lookup, need_date, need_enum, need_int, need_number, need_string,
    opt_bool, opt_enum, opt_int, resolve_body_fk,
)

bp = Blueprint("units", __name__)


# ----------------------------------------------------- portable units ------
@bp.post("/portable-units")
def create_unit():
    require(["AssetManager", "DistrictAdmin"])
    body = get_body()
    # rule 5: the only body foreign key on this entity
    replaced = resolve_body_fk("unit", body, "replaced_unit_id")
    # rule 6
    asset_tag = need_string(body, "asset_tag", 1, 24)
    size_class = need_enum(body, "size_class", C.SIZE_CLASSES)
    condition_grade = opt_enum(body, "condition_grade", C.CONDITION_GRADES, "B")
    ada_ramp = opt_bool(body, "ada_ramp_installed", False)
    acquisition = need_int(body, "acquisition_cost_cents", minimum=1)
    in_service_year = need_int(body, "in_service_year", 1970, 2100)
    prior_relocations = opt_int(body, "prior_relocation_count", default=0,
                                minimum=0, maximum=4)
    # rule 32: asset_tag is unique across the whole inventory
    for existing in db.units.values():
        if existing["asset_tag"] == asset_tag:
            fail("ERR_DUPLICATE_ASSET_TAG",
                 "Asset tag '%s' is already in the inventory." % asset_tag)

    rec = new_record({
        "asset_tag": asset_tag,
        "size_class": size_class,
        "rated_seats": C.RATED_SEATS[size_class],
        "condition_grade": condition_grade,
        "condition_status": "SERVICEABLE",
        "allocation_status": "IN_STORAGE",
        "ada_ramp_installed": ada_ramp,
        "acquisition_cost_cents": acquisition,
        "in_service_year": in_service_year,
        "current_school_id": None,
        "replaced_unit_id": replaced["id"] if replaced else None,
        "prior_relocation_count": prior_relocations,
        "lifetime_relocation_count": prior_relocations,
        "accumulated_relocation_cost_cents": 0,
    })
    db.units[rec["id"]] = rec
    return created(public(rec))


@bp.get("/portable-units/<unit_id>")
def read_unit(unit_id):
    require(C.ALL_EXCEPT_CREW_LEAD)
    return ok(public(lookup("unit", unit_id)))


@bp.get("/portable-units")
def list_units():
    require(C.ALL_EXCEPT_CREW_LEAD)
    return list_response(db.units, [
        "current_school_id", "replaced_unit_id", "allocation_status",
        "condition_status", "size_class",
    ])


@bp.post("/portable-units/<unit_id>/condition")
def record_condition(unit_id):
    require(["AssetManager"])
    unit = lookup("unit", unit_id)
    body = get_body()
    condition_status = need_enum(body, "condition_status", C.CONDITION_STATUSES)
    condition_grade = need_enum(body, "condition_grade", C.CONDITION_GRADES)
    # rule 10: the condition dimension may move on any unit that is not DISPOSED
    if unit["allocation_status"] == "DISPOSED":
        fail("ERR_UNIT_STATE_INVALID", "A DISPOSED unit cannot be inspected.")
    if condition_status == "SERVICEABLE" and condition_grade == "D":
        fail("ERR_UNIT_STATE_INVALID",
             "A unit cannot be declared SERVICEABLE at grade D.")

    unit["condition_status"] = condition_status
    unit["condition_grade"] = condition_grade
    touch(unit)

    if condition_status == "UNSAFE":
        cascade.unsafe_cascade(unit)
    return ok(public(unit))


@bp.post("/portable-units/<unit_id>/record-existing-placement")
def record_existing_placement(unit_id):
    require(["AssetManager", "DistrictAdmin"])
    unit = lookup("unit", unit_id)
    body = get_body()
    # rule 5
    school = resolve_body_fk("school", body, "school_id")
    site = resolve_body_fk("site", body, "placement_site_id")
    # rule 6
    if school is None:
        need_string(body, "school_id")
    if site is None:
        need_string(body, "placement_site_id")
    need_date(body, "installed_on")
    # rule 10
    if unit["allocation_status"] != "IN_STORAGE":
        fail("ERR_UNIT_STATE_INVALID",
             "A unit in %s cannot be recorded as an existing placement."
             % unit["allocation_status"])
    if unit["condition_status"] == "UNSAFE":
        fail("ERR_UNIT_STATE_INVALID",
             "An UNSAFE unit cannot be recorded as an existing placement.")
    # rule 23
    if site["school_id"] != school["id"]:
        fail("ERR_SITE_SCHOOL_MISMATCH",
             "The named pad belongs to another campus.")
    # rule 31
    if site["occupied_by_unit_id"] is not None:
        fail("ERR_SITE_OCCUPIED", "That pad is already occupied.")

    cascade.legacy_placement(unit, school, site)
    return ok(public(unit))


# ------------------------------------------------------ placement sites ----
@bp.post("/placement-sites")
def create_site():
    require(["DistrictAdmin"])
    body = get_body()
    school = resolve_body_fk("school", body, "school_id")
    if school is None:
        need_string(body, "school_id")
    pad_code = need_string(body, "pad_code", 1, 20)
    pad_length = need_number(body, "pad_length_ft", exclusive_min=0)
    pad_width = need_number(body, "pad_width_ft", exclusive_min=0)
    fire_distance = need_number(body, "distance_to_fire_lane_ft", minimum=0)
    electrical = need_number(body, "electrical_drop_available_kw", minimum=0)
    sewer = opt_bool(body, "sewer_connection_available", False)
    ada = opt_bool(body, "ada_path_of_travel_compliant", False)
    # rule 32
    for existing in db.sites.values():
        if (existing["school_id"] == school["id"]
                and existing["pad_code"] == pad_code):
            fail("ERR_DUPLICATE_PAD_CODE",
                 "Pad code '%s' already exists on this campus." % pad_code)

    rec = new_record({
        "school_id": school["id"],
        "pad_code": pad_code,
        "pad_length_ft": pad_length,
        "pad_width_ft": pad_width,
        "distance_to_fire_lane_ft": fire_distance,
        "electrical_drop_available_kw": electrical,
        "sewer_connection_available": sewer,
        "ada_path_of_travel_compliant": ada,
        "feasibility_status": "UNASSESSED",
        "mitigation_flags": [],
        "infeasible_reason": None,
        "assessed_for_size_class": None,
        "occupied_by_unit_id": None,
    })
    db.sites[rec["id"]] = rec
    return created(public(rec))


@bp.get("/placement-sites/<site_id>")
def read_site(site_id):
    require(C.ALL_EXCEPT_CREW_LEAD)
    return ok(public(lookup("site", site_id)))


@bp.get("/placement-sites")
def list_sites():
    require(C.ALL_EXCEPT_CREW_LEAD)
    return list_response(
        db.sites, ["school_id", "occupied_by_unit_id", "feasibility_status"])


@bp.post("/placement-sites/<site_id>/assess")
def assess_site(site_id):
    require(["FacilitiesPlanner"])
    site = lookup("site", site_id)
    body = get_body()
    size_class = opt_enum(body, "candidate_size_class", C.SIZE_CLASSES,
                          C.DEFAULT_SIZE_CLASS)
    # rule 31: an occupied pad cannot be assessed at all
    if site["occupied_by_unit_id"] is not None:
        fail("ERR_SITE_OCCUPIED", "An occupied pad cannot be assessed.")

    school = db.schools[site["school_id"]]
    site.update(assess(site, school, size_class))
    touch(site)
    return ok(public(site))
