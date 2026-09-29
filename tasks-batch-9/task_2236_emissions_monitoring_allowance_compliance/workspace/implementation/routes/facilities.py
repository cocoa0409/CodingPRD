"""Facilities and unit registration (PRD 3.1)."""

import re

from flask import Blueprint

from constants import (
    API_PREFIX,
    COMPLIANCE_POSTURES,
    CONTROL_DEVICES,
    DEFAULT_MAX_CONCURRENT_OUTAGES,
    FACILITY_STATUSES,
    FUEL_TYPES,
    PROGRAMS,
    ROLE_FACILITY_OPERATOR,
    ROLE_REGULATORY_REVIEWER,
)
from db import base_record, db, public, public_list, sort_rows, touch
from errors import fail
from lookup import find, get, units_of_facility
from middleware import ANY_ROLE, authenticate, enforce_facility_scope
from response import array_response, object_response
from validation import (
    apply_pagination,
    body_dict,
    check_range,
    dt_field,
    enum_field,
    int_field,
    list_field,
    match_filters,
    num_field,
    pagination,
    query_filters,
    str_field,
)

bp = Blueprint("facilities", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------------------
# facilities
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/facilities", methods=["POST"])
def create_facility():
    authenticate((ROLE_REGULATORY_REVIEWER,))
    body = body_dict()

    name = str_field(body, "name", required=True, min_len=1)
    orispl_code = str_field(body, "orispl_code", required=True, min_len=1, max_len=8)
    state_code = str_field(body, "state_code", required=True)
    if not STATE_CODE_RE.match(state_code):
        fail("ERR_INVALID_REQUEST", "state_code must be exactly two uppercase letters.")
    operator_org = str_field(body, "operator_org", required=True, min_len=1)
    programs = list_field(body, "programs", required=True)
    if not programs:
        fail("ERR_INVALID_REQUEST", "programs must be a non-empty array.")
    for program in programs:
        if not isinstance(program, str) or program not in PROGRAMS:
            fail("ERR_INVALID_REQUEST", "programs contains an unknown value.")
    deadline_raw, deadline = dt_field(body, "true_up_deadline_utc", required=True)
    max_outages = int_field(body, "max_concurrent_control_outages")

    check_range("max_concurrent_control_outages", max_outages, minimum=0, maximum=10)

    for facility in db.facilities.values():
        if facility["orispl_code"] == orispl_code:
            fail("ERR_DUPLICATE_ORISPL_CODE", "orispl_code is already registered.")

    facility = base_record()
    facility.update(
        {
            "name": name,
            "orispl_code": orispl_code,
            "state_code": state_code,
            "operator_org": operator_org,
            "programs": list(programs),
            "true_up_deadline_utc": deadline_raw,
            "max_concurrent_control_outages": (
                DEFAULT_MAX_CONCURRENT_OUTAGES if max_outages is None else max_outages
            ),
            "status": "OPERATING",
            "compliance_posture": "COMPLIANT",
            "_true_up_deadline": deadline,
        }
    )
    db.facilities[facility["id"]] = facility
    return object_response(public(facility), 201)


@bp.route(API_PREFIX + "/facilities", methods=["GET"])
def list_facilities():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "state_code": "str",
            "status": FACILITY_STATUSES,
            "compliance_posture": COMPLIANCE_POSTURES,
            "operator_org": "str",
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.facilities.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/facilities/<facility_id>", methods=["GET"])
def read_facility(facility_id):
    authenticate(ANY_ROLE)
    facility = get("facility", facility_id)
    return object_response(public(facility))


@bp.route(API_PREFIX + "/facilities/<facility_id>", methods=["PATCH"])
def update_facility(facility_id):
    authenticate((ROLE_REGULATORY_REVIEWER,))
    body = body_dict()

    deadline_raw, deadline = dt_field(body, "true_up_deadline_utc")
    max_outages = int_field(body, "max_concurrent_control_outages")
    status = enum_field(body, "status", FACILITY_STATUSES)
    check_range("max_concurrent_control_outages", max_outages, minimum=0, maximum=10)

    facility = get("facility", facility_id)

    if deadline_raw is not None:
        facility["true_up_deadline_utc"] = deadline_raw
        facility["_true_up_deadline"] = deadline
    if max_outages is not None:
        facility["max_concurrent_control_outages"] = max_outages
    if status is not None:
        facility["status"] = status
    touch(facility)
    return object_response(public(facility))


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/facilities/<facility_id>/units", methods=["POST"])
def create_unit(facility_id):
    caller = authenticate((ROLE_REGULATORY_REVIEWER, ROLE_FACILITY_OPERATOR))
    body = body_dict()
    enforce_facility_scope(caller, find("facility", facility_id))

    unit_identifier = str_field(body, "unit_identifier", required=True, min_len=1)
    primary_fuel = enum_field(body, "primary_fuel", FUEL_TYPES, required=True)
    nameplate = num_field(body, "nameplate_capacity_mw", required=True)
    max_rated = num_field(body, "max_rated_heat_input_mmbtu_hr", required=True)
    control_device = enum_field(body, "control_device", CONTROL_DEVICES)

    facility = get("facility", facility_id)

    check_range("nameplate_capacity_mw", nameplate, minimum=0, min_exclusive=True)
    check_range("max_rated_heat_input_mmbtu_hr", max_rated, minimum=0, min_exclusive=True)

    for existing in units_of_facility(facility["id"]):
        if existing["unit_identifier"] == unit_identifier:
            fail("ERR_INVALID_REQUEST", "unit_identifier is already used by this facility.")

    unit = base_record()
    unit.update(
        {
            "facility_id": facility["id"],
            "unit_identifier": unit_identifier,
            "primary_fuel": primary_fuel,
            "nameplate_capacity_mw": float(nameplate),
            "max_rated_heat_input_mmbtu_hr": float(max_rated),
            "control_device": control_device if control_device is not None else "NONE",
            "dispatch_state": "OFFLINE",
            "control_status": "AVAILABLE",
            "dispatch_restricted": False,
            "data_availability_pct": 100.0,
            "certified_so2_lbs_ytd": 0.0,
        }
    )
    db.units[unit["id"]] = unit
    return object_response(public(unit), 201)
