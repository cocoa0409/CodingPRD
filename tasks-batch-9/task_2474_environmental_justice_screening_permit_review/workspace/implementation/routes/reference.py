"""Screening areas, burden indicators, facilities, venues and the logical clock."""
from flask import Blueprint

import constants as C
import serialize
from db import clock_year, db, iso_ts, new_row, set_clock, touch
from errors import ApiError, bad_request
from middleware import authenticate
from response import list_response, object_response, paginate
from services import cascade, repo
from validators import (body_json, f_bool, f_enum, f_int, f_lang_array, f_num,
                        f_str, parse_instant, q_enum, q_pagination)

bp = Blueprint("reference", __name__)


# ------------------------------------------------------------- screening areas
@bp.post("/ej/screening-areas")
def create_screening_area():
    authenticate((C.ROLE_PROGRAM_ADMIN,))
    body = body_json()
    area_code = f_str(body, "area_code", min_len=1, max_len=32)
    county = f_str(body, "county", min_len=1)
    population = f_int(body, "population", minimum=1)
    limited_english_pct = f_num(
        body, "limited_english_pct", minimum=C.D("0.0"), maximum=C.D("100.0")
    )
    languages = f_lang_array(body, "required_translation_languages", required=False,
                             default=[])
    baseline_load_tpy = f_num(body, "baseline_load_tpy", exclusive_min=C.D("0"))

    for existing in db.screening_areas.values():
        if existing["area_code"] == area_code:
            raise ApiError("ERR_AREA_CODE_DUPLICATE")

    if limited_english_pct >= C.TRANSLATION_TRIGGER_PCT and not languages:
        raise ApiError("ERR_TRANSLATION_LANGUAGES_REQUIRED")

    row = new_row()
    row.update(
        {
            "area_code": area_code,
            "county": county,
            "population": population,
            "limited_english_pct": limited_english_pct,
            "required_translation_languages": languages,
            "baseline_load_tpy": baseline_load_tpy,
            "demographic_component_statewide": C.D("0.00"),
            "health_component_statewide": C.D("0.00"),
            "pollution_component_statewide": C.D("0.00"),
            "ej_screen_score_statewide": C.D("0.00"),
            "ej_screen_score_county": C.D("0.00"),
            "enforcement_burden_points": 0,
            "designation": "UNDESIGNATED",
            "data_status": "CURRENT",
            "active_indicator_count": 0,
            "permitted_load_tpy": C.D("0.00"),
            "open_complaint_count": 0,
            "open_plan_count": 0,
            "translation_required": False,
        }
    )
    db.screening_areas[row["id"]] = row
    cascade.rescore_area(row, cascade=False)
    return object_response(serialize.screening_area(row), 201)


@bp.get("/ej/screening-areas/<area_id>")
def read_screening_area(area_id):
    authenticate(C.ALL_ROLES)
    area = repo.get_area(area_id)
    return object_response(serialize.screening_area(area))


@bp.post("/ej/screening-areas/<area_id>/recertify")
def recertify_screening_area(area_id):
    authenticate((C.ROLE_PROGRAM_ADMIN,))
    body_json()
    area = repo.get_area(area_id)
    if area["data_status"] != "STALE":
        raise ApiError("ERR_AREA_NOT_STALE")
    area["data_status"] = "CURRENT"
    cascade.rescore_area(area)
    return object_response(serialize.screening_area(area))


@bp.get("/ej/screening-areas/<area_id>/burden-indicators")
def list_area_indicators(area_id):
    authenticate(C.ALL_ROLES)
    limit, offset = q_pagination()
    status = q_enum("status", C.INDICATOR_STATUSES)
    indicator_code = q_enum("indicator_code", C.INDICATOR_CODES)
    area = repo.get_area(area_id)
    rows = repo.indicators_of(area["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if indicator_code is not None:
        rows = [r for r in rows if r["indicator_code"] == indicator_code]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.burden_indicator, page),
                         limit, offset, total)


@bp.get("/ej/screening-areas/<area_id>/facilities")
def list_area_facilities(area_id):
    authenticate(C.ALL_ROLES)
    limit, offset = q_pagination()
    facility_type = q_enum("facility_type", C.FACILITY_TYPES)
    area = repo.get_area(area_id)
    rows = repo.facilities_of(area["id"])
    if facility_type is not None:
        rows = [r for r in rows if r["facility_type"] == facility_type]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.facility, page),
                         limit, offset, total)


# ----------------------------------------------------------- burden indicators
@bp.post("/ej/burden-indicators")
def create_burden_indicator():
    authenticate((C.ROLE_PROGRAM_ADMIN, C.ROLE_EJ_ANALYST))
    body = body_json()
    screening_area_id = f_str(body, "screening_area_id")
    indicator_code = f_enum(body, "indicator_code", C.INDICATOR_CODES)
    category = f_enum(body, "category", C.INDICATOR_CATEGORIES)
    raw_value = f_num(body, "raw_value")
    statewide_percentile = f_num(body, "statewide_percentile")
    county_percentile = f_num(body, "county_percentile")
    vintage_year = f_int(body, "vintage_year")
    expected_version = f_int(body, "expected_screening_area_version")

    area = repo.get_area(screening_area_id)

    if expected_version != area["version"]:
        raise ApiError("ERR_STALE_AREA_VERSION")
    if C.INDICATOR_CATEGORY_MAP[indicator_code] != category:
        raise ApiError("ERR_INDICATOR_CATEGORY_MISMATCH")
    for value in (statewide_percentile, county_percentile):
        if value < C.D("0.00") or value > C.D("100.00"):
            raise ApiError("ERR_PERCENTILE_OUT_OF_RANGE")
    year = clock_year()
    if not (year - C.INDICATOR_VALIDITY_YEARS <= vintage_year <= year):
        raise ApiError("ERR_INDICATOR_VINTAGE_INVALID")

    displaced = None
    for existing in repo.indicators_of(area["id"]):
        if existing["status"] == "ACTIVE" and existing["indicator_code"] == indicator_code:
            displaced = existing
            break

    row = new_row()
    row.update(
        {
            "screening_area_id": area["id"],
            "indicator_code": indicator_code,
            "category": category,
            "raw_value": raw_value,
            "statewide_percentile": statewide_percentile,
            "county_percentile": county_percentile,
            "vintage_year": vintage_year,
            "status": "ACTIVE",
            "area_version_after": area["version"],
            "superseded_indicator_id": displaced["id"] if displaced else None,
        }
    )
    db.burden_indicators[row["id"]] = row

    if displaced is not None:
        displaced["status"] = "SUPERSEDED"
        touch(displaced)

    cascade.rescore_area(area)

    row["area_version_after"] = area["version"]
    if displaced is not None:
        displaced["area_version_after"] = area["version"]

    return object_response(serialize.burden_indicator(row), 201)


# ------------------------------------------------------------------- facilities
@bp.post("/ej/facilities")
def create_facility():
    authenticate((C.ROLE_PROGRAM_ADMIN,))
    body = body_json()
    screening_area_id = f_str(body, "screening_area_id")
    name = f_str(body, "name", min_len=1)
    facility_type = f_enum(body, "facility_type", C.FACILITY_TYPES)
    distance = f_int(body, "distance_to_area_centroid_m", minimum=0)

    area = repo.get_area(screening_area_id)

    row = new_row()
    row.update(
        {
            "screening_area_id": area["id"],
            "name": name,
            "facility_type": facility_type,
            "distance_to_area_centroid_m": distance,
            "existing_load_tpy": C.D("0.00"),
            "compliance_status": "IN_COMPLIANCE",
            "confirmed_violation_count": 0,
        }
    )
    db.facilities[row["id"]] = row
    return object_response(serialize.facility(row), 201)


@bp.get("/ej/facilities/<facility_id>")
def read_facility(facility_id):
    authenticate(C.ALL_ROLES)
    facility = repo.get_facility(facility_id)
    return object_response(serialize.facility(facility))


# ----------------------------------------------------------------------- venues
@bp.post("/ej/venues")
def create_venue():
    authenticate((C.ROLE_PROGRAM_ADMIN,))
    body = body_json()
    name = f_str(body, "name", min_len=1)
    address = f_str(body, "address", min_len=1)
    capacity = f_int(body, "capacity", minimum=1)
    transit_accessible = f_bool(body, "transit_accessible")
    ada_accessible = f_bool(body, "ada_accessible")
    interpretation_capable = f_bool(body, "interpretation_capable")
    status = f_enum(body, "status", C.VENUE_STATUSES, required=False, default="ACTIVE")

    row = new_row()
    row.update(
        {
            "name": name,
            "address": address,
            "capacity": capacity,
            "transit_accessible": transit_accessible,
            "ada_accessible": ada_accessible,
            "interpretation_capable": interpretation_capable,
            "status": status,
            "booked_meeting_count": 0,
        }
    )
    db.venues[row["id"]] = row
    return object_response(serialize.venue(row), 201)


@bp.get("/ej/venues/<venue_id>")
def read_venue(venue_id):
    authenticate(C.ALL_ROLES)
    venue = repo.get_venue(venue_id)
    return object_response(serialize.venue(venue))


@bp.get("/ej/venues/<venue_id>/meetings")
def list_venue_meetings(venue_id):
    authenticate(C.ALL_ROLES)
    limit, offset = q_pagination()
    status = q_enum("status", C.MEETING_STATUSES)
    venue = repo.get_venue(venue_id)
    rows = repo.meetings_of_venue(venue["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.public_meeting, page),
                         limit, offset, total)


# ------------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate((C.ROLE_PROGRAM_ADMIN,))
    body = body_json()
    raw = body.get("to_iso8601")
    if raw is None:
        raise bad_request("Field 'to_iso8601' is required.")
    instant = parse_instant(raw, "to_iso8601")
    set_clock(instant)
    return object_response({"current_utc": iso_ts(instant)})
