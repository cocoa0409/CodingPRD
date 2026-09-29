"""Clock, campuses, policies, rooms, set-asides, projections, budgets, crews."""

from flask import Blueprint

import constants as C
from clock import clock, parse_instant
from db import db, new_record, public, touch
from errors import fail
from middleware import require
from response import created, ok
from routes.common import list_response
from services.reliance import district_summary, governing_study, school_metrics
from validation import (
    get_body, lookup, need_enum, need_int, need_number, need_school_year,
    need_string, need_string_array, opt_enum, opt_int, opt_number,
    raw_field, resolve_body_fk, MISSING,
)

bp = Blueprint("config", __name__)


# ------------------------------------------------------- logical clock -----
@bp.post("/_clock/set_current_utc")
def set_clock():
    require(["DistrictAdmin"])
    body = get_body()
    text = need_string(body, "to_iso8601", 1, 64)
    moment = parse_instant(text)
    if moment is None:
        fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO 8601 instant.")
    clock.set(moment)
    return ok({"current_utc": clock.iso()})


# ------------------------------------------------------------- schools -----
@bp.post("/schools")
def create_school():
    require(["DistrictAdmin"])
    body = get_body()
    name = need_string(body, "name", 1, 120)
    grade_configuration = need_enum(body, "grade_configuration", C.GRADE_CONFIGURATIONS)
    site_acreage = need_number(body, "site_acreage", minimum=0.5)
    fire_lane = need_number(body, "fire_lane_clear_width_ft", minimum=0)
    electrical = need_number(body, "electrical_spare_capacity_kw", minimum=0)
    sewer = need_int(body, "sewer_spare_connections", minimum=0)
    reliance_years = opt_int(body, "consecutive_reliance_years", default=0, minimum=0)

    rec = new_record({
        "name": name,
        "grade_configuration": grade_configuration,
        "site_acreage": site_acreage,
        "fire_lane_clear_width_ft": fire_lane,
        "electrical_spare_capacity_kw": electrical,
        "sewer_spare_connections": sewer,
        "consecutive_reliance_years": reliance_years,
        "hosted_portable_seats": 0,
        "reliance_flag": "NONE",
        "certified_study_id": None,
    })
    db.schools[rec["id"]] = rec
    return created(public(rec))


@bp.get("/schools/<school_id>")
def read_school(school_id):
    require(C.ALL_EXCEPT_CREW_LEAD)
    return ok(public(lookup("school", school_id)))


@bp.get("/schools/<school_id>/reliance-report")
def reliance_report(school_id):
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier", "AssetManager"])
    school = lookup("school", school_id)
    if governing_study(school["id"]) is None:
        fail("ERR_NO_CERTIFIED_STUDY",
             "This campus has no CERTIFIED capacity study to report on.")
    metrics = school_metrics(school)
    return ok({
        "school_id": school["id"],
        "certified_study_id": metrics["certified_study_id"],
        "permanent_seats": metrics["permanent_seats"],
        "hosted_portable_seats": metrics["hosted_portable_seats"],
        "portable_seat_share_pct": metrics["portable_seat_share_pct"],
        "consecutive_reliance_years": metrics["consecutive_reliance_years"],
        "reliance_flag": metrics["reliance_flag"],
        "narrative_required": metrics["narrative_required"],
    })


@bp.get("/reliance-summary")
def reliance_summary():
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier"])
    return ok(district_summary())


# ------------------------------------------------- class size policies -----
@bp.post("/class-size-policies")
def create_policy():
    require(["DistrictAdmin"])
    body = get_body()
    grade_band = need_enum(body, "grade_band", C.GRADE_BANDS)
    school_year = need_school_year(body, "effective_school_year")
    max_class_size = need_int(body, "max_class_size", 1, 40)
    min_area = need_number(body, "min_area_sqft_per_seat", exclusive_min=0)
    lab_premium = need_number(body, "lab_area_premium_sqft", minimum=0)

    for existing in db.policies.values():
        if (existing["grade_band"] == grade_band
                and existing["effective_school_year"] == school_year):
            fail("ERR_DUPLICATE_POLICY",
                 "A policy for that grade band and school year already exists.")

    rec = new_record({
        "grade_band": grade_band,
        "effective_school_year": school_year,
        "max_class_size": max_class_size,
        "min_area_sqft_per_seat": min_area,
        "lab_area_premium_sqft": lab_premium,
    }, versioned=False)
    db.policies[rec["id"]] = rec
    return created(public(rec))


@bp.get("/class-size-policies/<policy_id>")
def read_policy(policy_id):
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier"])
    return ok(public(lookup("policy", policy_id)))


# --------------------------------------------------------------- rooms -----
@bp.post("/rooms")
def create_room():
    require(["DistrictAdmin"])
    body = get_body()
    school = resolve_body_fk("school", body, "school_id")
    room_number = need_string(body, "room_number", 1, 20)
    room_type = need_enum(body, "room_type", C.ROOM_TYPES)
    area_sqft = need_number(body, "area_sqft", exclusive_min=0)
    if school is None:
        need_string(body, "school_id")

    for existing in db.rooms.values():
        if (existing["school_id"] == school["id"]
                and existing["room_number"] == room_number):
            fail("ERR_DUPLICATE_ROOM",
                 "Room number '%s' already exists on this campus." % room_number)

    rec = new_record({
        "school_id": school["id"],
        "room_number": room_number,
        "room_type": room_type,
        "area_sqft": area_sqft,
        "status": "IN_SERVICE",
    })
    db.rooms[rec["id"]] = rec
    return created(public(rec))


@bp.get("/rooms/<room_id>")
def read_room(room_id):
    require(C.ALL_EXCEPT_CREW_LEAD)
    return ok(public(lookup("room", room_id)))


@bp.get("/rooms")
def list_rooms():
    require(C.ALL_EXCEPT_CREW_LEAD)
    return list_response(db.rooms, ["school_id", "room_type", "status"])


@bp.patch("/rooms/<room_id>")
def patch_room(room_id):
    require(["DistrictAdmin"])
    room = lookup("room", room_id)
    body = get_body()
    status = opt_enum(body, "status", C.ROOM_STATUSES)
    area_sqft = opt_number(body, "area_sqft", exclusive_min=0)
    if status is not None:
        room["status"] = status
    if area_sqft is not None:
        room["area_sqft"] = area_sqft
    touch(room)
    return ok(public(room))


# ------------------------------------------------------- set-asides --------
@bp.post("/program-set-asides")
def create_set_aside():
    require(["DistrictAdmin"])
    body = get_body()
    school = resolve_body_fk("school", body, "school_id")
    program_type = need_enum(body, "program_type", C.PROGRAM_TYPES)
    reserved_room_type = need_enum(body, "reserved_room_type", C.ROOM_TYPES)
    reserved_room_count = need_int(body, "reserved_room_count", minimum=1)
    seats_excluded = need_int(body, "seats_excluded_per_room", minimum=0)
    if school is None:
        need_string(body, "school_id")

    rec = new_record({
        "school_id": school["id"],
        "program_type": program_type,
        "reserved_room_type": reserved_room_type,
        "reserved_room_count": reserved_room_count,
        "seats_excluded_per_room": seats_excluded,
    })
    db.set_asides[rec["id"]] = rec
    return created(public(rec))


@bp.get("/program-set-asides/<set_aside_id>")
def read_set_aside(set_aside_id):
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier", "AssetManager"])
    return ok(public(lookup("set_aside", set_aside_id)))


@bp.get("/program-set-asides")
def list_set_asides():
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier", "AssetManager"])
    return list_response(db.set_asides, ["school_id", "program_type"])


# -------------------------------------------------- enrollment projections -
@bp.post("/enrollment-projections")
def create_projection():
    require(["FacilitiesPlanner", "DistrictAdmin"])
    body = get_body()
    school = resolve_body_fk("school", body, "school_id")
    school_year = need_school_year(body, "school_year")
    grade_level = need_int(body, "grade_level", 0, 12)
    projected_students = need_int(body, "projected_students", minimum=0)
    source = need_enum(body, "source", C.PROJECTION_SOURCES)
    confidence_tier = need_enum(body, "confidence_tier", C.CONFIDENCE_TIERS)
    if school is None:
        need_string(body, "school_id")

    rec = new_record({
        "school_id": school["id"],
        "school_year": school_year,
        "grade_level": grade_level,
        "projected_students": projected_students,
        "source": source,
        "confidence_tier": confidence_tier,
    }, versioned=False)
    db.projections[rec["id"]] = rec
    return created(public(rec))


@bp.get("/enrollment-projections/<projection_id>")
def read_projection(projection_id):
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier"])
    return ok(public(lookup("projection", projection_id)))


@bp.get("/enrollment-projections")
def list_projections():
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier"])
    return list_response(db.projections, ["school_id", "school_year", "grade_level"])


# ----------------------------------------------------- capital budgets -----
@bp.post("/capital-budgets")
def create_budget():
    require(["DistrictAdmin"])
    body = get_body()
    fiscal_year = need_school_year(body, "fiscal_year")
    authorized = need_int(body, "authorized_cents", minimum=1)
    rec = new_record({
        "fiscal_year": fiscal_year,
        "authorized_cents": authorized,
        "encumbered_cents": 0,
        "expended_cents": 0,
        "uncommitted_cents": authorized,
    })
    db.budgets[rec["id"]] = rec
    return created(public(rec))


@bp.get("/capital-budgets/<budget_id>")
def read_budget(budget_id):
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier",
             "OperationsScheduler", "AssetManager"])
    return ok(public(lookup("budget", budget_id)))


# -------------------------------------------------- installation crews -----
@bp.post("/installation-crews")
def create_crew():
    require(["DistrictAdmin"])
    body = get_body()
    name = need_string(body, "name", 1, 80)
    max_concurrent_jobs = need_int(body, "max_concurrent_jobs", 1, 6)
    work_types = need_string_array(body, "certified_work_types", C.WORK_TYPES, 1)
    rec = new_record({
        "name": name,
        "max_concurrent_jobs": max_concurrent_jobs,
        "certified_work_types": work_types,
    })
    db.crews[rec["id"]] = rec
    return created(public(rec))


@bp.get("/installation-crews/<crew_id>")
def read_crew(crew_id):
    require(["DistrictAdmin", "FacilitiesPlanner", "OperationsScheduler", "CrewLead"])
    return ok(public(lookup("crew", crew_id)))
