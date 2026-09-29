"""Courses, turf areas, playability readings and the logical clock."""

import re
from decimal import Decimal

from flask import Blueprint

import calc
import services
from envelope import created, ok
from errors import ApiError
from serializers import (course_out, reading_out, turf_area_out, weather_event_out)
from store import clock, set_clock, store
from util import ZERO, dec
from validators import (bad, body, endpoint, field_date, field_dt, field_enum, field_int,
                        field_num, field_str, field_uuid, pagination, path_uuid,
                        query_bool, query_enum, query_int, query_str, query_uuid)

from routes.common import list_response

bp = Blueprint("courses", __name__)

ALL_ROLES = ("Superintendent", "Agronomist", "Applicator", "TournamentOfficial",
             "EquipmentTechnician")

REGION_CODE_RE = re.compile(r"^[A-Z]{2}$")

AREA_TYPES = ("GREEN", "TEE", "FAIRWAY", "ROUGH", "APPROACH", "PRACTICE_GREEN")
SOIL_TYPES = ("SAND_USGA", "NATIVE_LOAM", "PUSH_UP_CLAY")
AGRONOMIC_STATUSES = ("ACTIVE", "UNDER_RENOVATION", "OUT_OF_PLAY")
WATER_POSTURES = ("OPEN", "RESTRICTED", "SUSPENDED")
PLAY_POSTURES = ("OPEN", "FROST_DELAY", "CART_PATH_ONLY", "CLOSED")
WEATHER_TYPES = ("FROST", "LIGHTNING", "HEAVY_RAIN", "STORM_DAMAGE")
WEATHER_STATUSES = ("ACTIVE", "CLEARED")


# --------------------------------------------------------------------------
# courses
# --------------------------------------------------------------------------
@bp.post("/courses")
@endpoint(("Superintendent",))
def create_course():
    payload = body()
    name = field_str(payload, "name", max_len=120)
    region_code = field_str(payload, "region_code", pattern=REGION_CODE_RE)
    allocation = field_num(payload, "annual_water_allocation_gal", exclusive_min=0)
    restricted = field_num(payload, "water_restricted_threshold_pct", required=False,
                           default=Decimal("80"), exclusive_min=0)
    suspended = field_num(payload, "water_suspended_threshold_pct", required=False,
                          default=Decimal("100"))
    if restricted >= suspended:
        bad("'water_restricted_threshold_pct' must be strictly below "
            "'water_suspended_threshold_pct'.")

    record = services.base_record()
    record.update({
        "name": name,
        "region_code": region_code,
        "annual_water_allocation_gal": allocation,
        "water_restricted_threshold_pct": restricted,
        "water_suspended_threshold_pct": suspended,
        "water_used_gal": Decimal("0.0"),
        "water_posture": "OPEN",
        "play_posture": "OPEN",
        "frost_delay_minutes": 0,
    })
    store.courses[record["id"]] = record
    return created(course_out(record))


@bp.get("/courses")
@endpoint(ALL_ROLES)
def list_courses():
    page = pagination()
    region_code = query_str("region_code")
    water_posture = query_enum("water_posture", WATER_POSTURES)
    play_posture = query_enum("play_posture", PLAY_POSTURES)
    records = [
        record for record in store.courses.values()
        if (region_code is None or record["region_code"] == region_code)
        and (water_posture is None or record["water_posture"] == water_posture)
        and (play_posture is None or record["play_posture"] == play_posture)
    ]
    return list_response(records, course_out, page=page)


@bp.get("/courses/<course_id>")
@endpoint(ALL_ROLES)
def get_course(course_id):
    path_uuid(course_id, "ERR_COURSE_NOT_FOUND")
    record = services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")
    return ok(course_out(record))


@bp.patch("/courses/<course_id>/water-allocation")
@endpoint(("Superintendent",))
def revise_water_allocation(course_id):
    path_uuid(course_id, "ERR_COURSE_NOT_FOUND")
    payload = body()
    allocation = field_num(payload, "annual_water_allocation_gal", required=False,
                           exclusive_min=0)
    restricted = field_num(payload, "water_restricted_threshold_pct", required=False,
                           exclusive_min=0)
    suspended = field_num(payload, "water_suspended_threshold_pct", required=False)
    record = services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")

    new_restricted = restricted if restricted is not None else dec(
        record["water_restricted_threshold_pct"])
    new_suspended = suspended if suspended is not None else dec(
        record["water_suspended_threshold_pct"])
    if new_restricted >= new_suspended:
        bad("'water_restricted_threshold_pct' must be strictly below "
            "'water_suspended_threshold_pct'.")

    if allocation is not None:
        record["annual_water_allocation_gal"] = allocation
    record["water_restricted_threshold_pct"] = new_restricted
    record["water_suspended_threshold_pct"] = new_suspended
    services.touch(record)
    services.rederive_water_posture(record)
    return ok(course_out(record))


@bp.get("/courses/<course_id>/water-assessment")
@endpoint(("Superintendent",))
def water_assessment(course_id):
    path_uuid(course_id, "ERR_COURSE_NOT_FOUND")
    record = services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")
    return ok(calc.water_overage_assessment(record))


@bp.get("/courses/<course_id>/weather-events")
@endpoint(("Superintendent", "Agronomist", "TournamentOfficial"))
def list_course_weather_events(course_id):
    path_uuid(course_id, "ERR_COURSE_NOT_FOUND")
    page = pagination()
    status = query_enum("status", WEATHER_STATUSES)
    event_type = query_enum("event_type", WEATHER_TYPES)
    services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")
    records = [
        record for record in store.weather_events.values()
        if record["course_id"] == course_id
        and (status is None or record["status"] == status)
        and (event_type is None or record["event_type"] == event_type)
    ]
    return list_response(
        records, weather_event_out, page=page,
        sort_key=lambda r: (r["declared_at"], r["created_at"], r["_seq"]),
        reverse=True,
    )


# --------------------------------------------------------------------------
# turf areas
# --------------------------------------------------------------------------
@bp.post("/turf-areas")
@endpoint(("Superintendent", "Agronomist"))
def create_turf_area():
    payload = body()
    course_id = field_uuid(payload, "course_id")
    area_type = field_enum(payload, "area_type", AREA_TYPES)
    hole_number = field_int(payload, "hole_number", required=False, minimum=1, maximum=18)
    if area_type == "PRACTICE_GREEN":
        if hole_number is not None:
            bad("'hole_number' must be null for a practice green.")
    elif hole_number is None:
        bad("'hole_number' is required unless the area type is PRACTICE_GREEN.")
    area_sq_ft = field_num(payload, "area_sq_ft", exclusive_min=0)
    mowing_height_mm = field_num(payload, "mowing_height_mm", exclusive_min=0, maximum=120)
    distance_to_water_ft = field_num(payload, "distance_to_water_ft", minimum=0)
    soil_type = field_enum(payload, "soil_type", SOIL_TYPES)
    target_moisture_pct = field_num(payload, "target_moisture_pct", required=False,
                                    default=Decimal("18"), exclusive_min=0,
                                    exclusive_max=60)

    services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")

    record = services.base_record()
    record.update({
        "course_id": course_id,
        "area_type": area_type,
        "hole_number": hole_number,
        "area_sq_ft": area_sq_ft,
        "mowing_height_mm": mowing_height_mm,
        "distance_to_water_ft": distance_to_water_ft,
        "soil_type": soil_type,
        "target_moisture_pct": target_moisture_pct,
        "current_moisture_pct": None,
        "agronomic_status": "ACTIVE",
        "nitrogen_applied_lb_per_1000_ytd": Decimal("0.000"),
        "nitrogen_projected_lb_per_1000": Decimal("0.000"),
        "rei_expires_at": None,
    })
    store.turf_areas[record["id"]] = record
    return created(turf_area_out(record))


@bp.get("/turf-areas")
@endpoint(("Superintendent", "Agronomist", "Applicator", "TournamentOfficial"))
def list_turf_areas():
    page = pagination()
    course_id = query_uuid("course_id")
    area_type = query_enum("area_type", AREA_TYPES)
    hole_number = query_int("hole_number", minimum=1, maximum=18)
    agronomic_status = query_enum("agronomic_status", AGRONOMIC_STATUSES)
    records = [
        record for record in store.turf_areas.values()
        if (course_id is None or record["course_id"] == course_id)
        and (area_type is None or record["area_type"] == area_type)
        and (hole_number is None or record["hole_number"] == hole_number)
        and (agronomic_status is None or record["agronomic_status"] == agronomic_status)
    ]
    return list_response(records, turf_area_out, page=page)


@bp.get("/turf-areas/<area_id>")
@endpoint(("Superintendent", "Agronomist", "Applicator", "TournamentOfficial"))
def get_turf_area(area_id):
    path_uuid(area_id, "ERR_TURF_AREA_NOT_FOUND")
    record = services.require(store.turf_areas, area_id, "ERR_TURF_AREA_NOT_FOUND")
    return ok(turf_area_out(record))


@bp.get("/turf-areas/<area_id>/playability-readings")
@endpoint(("Superintendent", "Agronomist", "TournamentOfficial"))
def list_area_readings(area_id):
    path_uuid(area_id, "ERR_TURF_AREA_NOT_FOUND")
    page = pagination()
    services.require(store.turf_areas, area_id, "ERR_TURF_AREA_NOT_FOUND")
    records = [r for r in store.readings.values() if r["turf_area_id"] == area_id]
    return list_response(
        records, reading_out, page=page,
        sort_key=lambda r: (r["measured_at"], r["created_at"], r["_seq"]),
        reverse=True,
    )


# --------------------------------------------------------------------------
# playability readings
# --------------------------------------------------------------------------
@bp.post("/playability-readings")
@endpoint(("Agronomist", "TournamentOfficial"))
def create_reading():
    payload = body()
    area_id = field_uuid(payload, "turf_area_id")
    measured_at = field_dt(payload, "measured_at")
    if measured_at > clock():
        bad("'measured_at' may not be after the current clock reading.")
    green_speed_ft = field_num(payload, "green_speed_ft", exclusive_min=0, maximum=16)
    firmness = field_num(payload, "firmness_gravities", exclusive_min=0, maximum=4)
    moisture_pct = field_num(payload, "moisture_pct", minimum=0, maximum=60)

    area = services.require(store.turf_areas, area_id, "ERR_TURF_AREA_NOT_FOUND")
    if area["agronomic_status"] == "OUT_OF_PLAY":
        raise ApiError("ERR_TURF_AREA_OUT_OF_PLAY")

    record = services.base_record(versioned=False)
    record.update({
        "turf_area_id": area_id,
        "measured_at": measured_at,
        "green_speed_ft": green_speed_ft,
        "firmness_gravities": firmness,
        "moisture_pct": moisture_pct,
        "within_tournament_spec": calc.reading_within_tournament_spec(
            green_speed_ft, firmness),
    })
    store.readings[record["id"]] = record

    services.recompute_turf_moisture(area)
    services.touch(area)
    return created(reading_out(record))


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint(("Superintendent",))
def set_current_utc():
    payload = body()
    instant = field_dt(payload, "current_utc")
    set_clock(instant)
    from util import fmt_dt
    return ok({"current_utc": fmt_dt(instant)})
