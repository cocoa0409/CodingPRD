"""Project, utility-owner, facility, investigation and logical-clock administration
(PRD sections 3.1, 3.2, 2.5)."""
from flask import Blueprint

import calc
import db as store
import enums
import serializers as ser
import services
from errors import ApiError
from middleware import authenticate, must_get
from response import created, ok
from validation import (bad, body_json, field_bool, field_datetime, field_enum, field_id,
                        field_int, field_number, field_str, present)

bp = Blueprint("admin", __name__)


# =========================================================== projects =========

@bp.post("/uro/projects")
def create_project():
    authenticate(("ProgramAdmin",))
    body = body_json()
    name = field_str(body, "name", min_len=1, max_len=160)
    route = field_str(body, "route_designation", min_len=1, max_len=24)
    letting_raw, _letting_dt = field_datetime(body, "letting_date")
    start_raw, start_dt = field_datetime(body, "construction_start_date")
    end_raw, end_dt = field_datetime(body, "construction_end_date")
    if end_dt <= start_dt:
        bad("Field 'construction_end_date' must be strictly later than 'construction_start_date'.")
    year = field_int(body, "row_acquisition_year", minimum=1850, maximum=2100)
    authority = field_int(body, "reimbursement_authority_cents", minimum=0)
    overhead = field_int(body, "contract_daily_overhead_cents", minimum=0)

    rec = store.base_record()
    rec.update({
        "name": name,
        "route_designation": route,
        "letting_date": letting_raw,
        "construction_start_date": start_raw,
        "construction_end_date": end_raw,
        "_construction_start_dt": start_dt,
        "_construction_end_dt": end_dt,
        "row_acquisition_year": year,
        "reimbursement_authority_cents": authority,
        "contract_daily_overhead_cents": overhead,
        "status": "PLANNING",
    })
    store.db.projects[rec["id"]] = rec
    return created(ser.project_out(rec))


@bp.patch("/uro/projects/<project_id>")
def patch_project(project_id):
    authenticate(("ProgramAdmin",))
    body = body_json()
    authority = field_int(body, "reimbursement_authority_cents", required=False, minimum=0)
    overhead = field_int(body, "contract_daily_overhead_cents", required=False, minimum=0)
    letting_raw, _letting_dt = field_datetime(body, "letting_date", required=False)

    project = must_get("project", project_id)
    services.guard_project_open(project)

    if authority is not None:
        project["reimbursement_authority_cents"] = authority
    if overhead is not None:
        project["contract_daily_overhead_cents"] = overhead
    if letting_raw is not None:
        project["letting_date"] = letting_raw
    services.recompute_project(project)
    return ok(ser.project_out(project))


@bp.post("/uro/projects/<project_id>/close")
def close_project(project_id):
    authenticate(("ProgramAdmin",))
    body = body_json()
    field_str(body, "closure_note", required=False, min_len=0, max_len=2000, allow_blank=True)

    project = must_get("project", project_id)
    if project["status"] != "UNDER_CONSTRUCTION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A project may only be closed from UNDER_CONSTRUCTION.")
    services.guard_posture(project)

    conflicts = store.conflicts_of_project(project_id)
    if any(c["status"] != "CLEARED" for c in conflicts):
        raise ApiError("ERR_PROJECT_CLOSE_BLOCKED",
                       "Every conflict of the project must be CLEARED before closure.")
    for agreement in store.agreements_of_project(project_id):
        if agreement["settlement_status"] not in ("SETTLED", "VOIDED_OUT"):
            raise ApiError("ERR_PROJECT_CLOSE_BLOCKED",
                           "Every agreement must be SETTLED or VOIDED_OUT before closure.")
    for claim in store.claims_of_project(project_id):
        if claim["status"] in ("SUBMITTED", "UNDER_ANALYSIS"):
            raise ApiError("ERR_PROJECT_CLOSE_BLOCKED",
                           "No delay claim may remain SUBMITTED or UNDER_ANALYSIS at closure.")

    project["status"] = "CLOSED"
    services.recompute_project(project, bubble=False)
    return ok(ser.project_out(project))


# ====================================================== utility owners ========

@bp.post("/uro/utility-owners")
def create_owner():
    authenticate(("ProgramAdmin",))
    body = body_json()
    legal_name = field_str(body, "legal_name", min_len=1, max_len=160)
    utility_type = field_enum(body, "utility_type", enums.UTILITY_TYPE)
    is_public = field_bool(body, "is_public_agency", required=False, default=False)
    rate = field_number(body, "indirect_cost_rate_pct", minimum=0, maximum=35, max_decimals=2)

    rec = store.base_record()
    rec.update({
        "legal_name": legal_name,
        "utility_type": utility_type,
        "is_public_agency": is_public,
        "indirect_cost_rate_pct": body["indirect_cost_rate_pct"],
        "_rate_dec": rate,
        "delinquency_strikes": 0,
        "reimbursement_hold": False,
    })
    store.db.owners[rec["id"]] = rec
    return created(ser.owner_out(rec))


@bp.post("/uro/utility-owners/<owner_id>/release-hold")
def release_hold(owner_id):
    authenticate(("ProgramAdmin",))
    body = body_json()
    field_str(body, "release_note", min_len=1, max_len=2000)

    owner = must_get("owner", owner_id)
    services.release_hold_cascade(owner)
    return ok(ser.owner_out(owner))


# =========================================================== facilities =======

@bp.post("/uro/facilities")
def create_facility():
    authenticate(("ProgramAdmin", "UtilityCoordinator"))
    body = body_json()
    owner_id = field_id(body, "owner_id")
    facility_type = field_enum(body, "facility_type", enums.FACILITY_TYPE)
    station_begin = field_number(body, "station_begin", minimum=0)
    station_end = field_number(body, "station_end")
    if station_end <= station_begin:
        bad("Field 'station_end' must be strictly greater than 'station_begin'.")
    field_number(body, "offset_ft")
    depth_in = field_int(body, "depth_in", minimum=0)
    material = field_str(body, "material", min_len=1, max_len=40)
    installed_year = field_int(body, "installed_year", minimum=1850, maximum=2100)
    occupancy_basis = field_enum(body, "occupancy_basis", enums.OCCUPANCY_BASIS)
    record_source = field_enum(body, "record_source", enums.RECORD_SOURCE)

    must_get("owner", owner_id)

    rec = store.base_record()
    rec.update({
        "owner_id": owner_id,
        "facility_type": facility_type,
        "station_begin": body["station_begin"],
        "station_end": body["station_end"],
        "offset_ft": body["offset_ft"],
        "depth_in": depth_in,
        "material": material,
        "installed_year": installed_year,
        "occupancy_basis": occupancy_basis,
        "record_source": record_source,
    })
    store.db.facilities[rec["id"]] = rec
    return created(ser.facility_out(rec))


# ======================================================== investigations =====

@bp.post("/uro/investigations")
def create_investigation():
    authenticate(("UtilityCoordinator",))
    body = body_json()
    project_id = field_id(body, "project_id")
    facility_id = field_id(body, "facility_id")
    quality_level = field_enum(body, "quality_level", enums.QUALITY_LEVEL)
    method = field_enum(body, "method", enums.INVESTIGATION_METHOD)
    measured_depth = field_int(body, "measured_depth_in", minimum=0)
    field_number(body, "station_at_investigation", minimum=0)

    project = must_get("project", project_id)
    facility = must_get("facility", facility_id)
    services.guard_project_open(project)

    rec = store.base_record(with_version=False)
    rec.update({
        "project_id": project_id,
        "facility_id": facility_id,
        "quality_level": quality_level,
        "method": method,
        "measured_depth_in": measured_depth,
        "station_at_investigation": body["station_at_investigation"],
        "performed_at": store.db.clock_raw,
        "contradicts_record": calc.contradicts_record(quality_level, measured_depth,
                                                      facility["depth_in"]),
    })
    store.db.investigations[rec["id"]] = rec
    return created(ser.investigation_out(rec))


# ======================================================== logical clock ======

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("ProgramAdmin",))
    body = body_json()
    raw, parsed = field_datetime(body, "current_utc")
    store.db.set_clock(raw, parsed)
    return ok({"current_utc": raw})
