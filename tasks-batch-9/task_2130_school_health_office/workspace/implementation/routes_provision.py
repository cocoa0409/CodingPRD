"""Schools, nurses and coverage assignments."""
import re

from flask import Blueprint, request

import calc
import serializers as ser
from auth import (ALL_READ_ROLES, authorize, insert, must_exist,
                  resolve, rows)
from envelope import created, listing, ok, parse_pagination
from errors import fail
from store import db, new_record, parse_dt, sorted_rows, touch
from validators import Field, get_body, supplied, validate, value_or

bp = Blueprint("provision", __name__)

BUILDING_CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")
WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI"}


# ---------------------------------------------------------------------------
# School
# ---------------------------------------------------------------------------

@bp.post("/health-office/schools")
def create_school():
    authorize(["DistrictHealthAdmin"])
    body = get_body(request)
    values = validate(body, [
        Field("name", "string"),
        Field("building_code", "string"),
        Field("cot_capacity", "integer", required=False, minimum=1, maximum=20),
        Field("emergency_protocol_enabled", "boolean", required=False),
    ])
    code = values["building_code"]
    if not BUILDING_CODE_RE.match(code):
        fail("ERR_INVALID_FIELD_VALUE",
             "building_code must be 2-8 uppercase alphanumeric characters.")
    for school in rows("schools"):
        if school["building_code"] == code:
            fail("ERR_DUPLICATE_BUILDING_CODE", "building_code %s already exists." % code)
    record = new_record({
        "name": values["name"],
        "building_code": code,
        "cot_capacity": value_or(values, "cot_capacity", 2),
        "emergency_protocol_enabled": value_or(values, "emergency_protocol_enabled", True),
    })
    insert("schools", record)
    return created(ser.school_json(record))


@bp.get("/health-office/schools/<school_id>")
def get_school(school_id):
    authorize(ALL_READ_ROLES)
    school = must_exist("schools", school_id, "School")
    return ok(ser.school_json(school))


# ---------------------------------------------------------------------------
# Nurse
# ---------------------------------------------------------------------------

@bp.post("/health-office/nurses")
def create_nurse():
    authorize(["DistrictHealthAdmin"])
    body = get_body(request)
    values = validate(body, [
        Field("full_name", "string"),
        Field("credential", "enum", enum={"RN", "LPN", "HEALTH_AIDE"}),
        Field("weekly_contracted_minutes", "integer", minimum=0, maximum=3000),
        Field("delegation_authorized", "boolean", required=False),
    ])
    contracted = values["weekly_contracted_minutes"]
    record = new_record({
        "full_name": values["full_name"],
        "credential": values["credential"],
        "delegation_authorized": value_or(values, "delegation_authorized", False),
        "weekly_contracted_minutes": contracted,
        "committed_weekly_minutes": 0,
        "uncommitted_weekly_minutes": contracted,
        "employment_status": "ACTIVE",
    })
    insert("nurses", record)
    return created(ser.nurse_json(record))


@bp.get("/health-office/nurses/<nurse_id>")
def get_nurse(nurse_id):
    authorize(ALL_READ_ROLES)
    nurse = must_exist("nurses", nurse_id, "Nurse")
    return ok(ser.nurse_json(nurse))


@bp.patch("/health-office/nurses/<nurse_id>")
def patch_nurse(nurse_id):
    authorize(["DistrictHealthAdmin"])
    nurse = must_exist("nurses", nurse_id, "Nurse")
    body = get_body(request)
    values = validate(body, [
        Field("employment_status", "enum", required=False, enum={"ACTIVE", "INACTIVE"}),
        Field("delegation_authorized", "boolean", required=False),
    ])
    if supplied(values, "employment_status"):
        nurse["employment_status"] = values["employment_status"]
    if supplied(values, "delegation_authorized"):
        nurse["delegation_authorized"] = values["delegation_authorized"]
    touch(nurse)
    return ok(ser.nurse_json(nurse))


# ---------------------------------------------------------------------------
# CoverageAssignment
# ---------------------------------------------------------------------------

def _ranges_overlap(a_from, a_to, b_from, b_to):
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


@bp.post("/health-office/coverage-assignments")
def create_coverage():
    authorize(["DistrictHealthAdmin"])
    body = get_body(request)
    nurse = resolve("nurses", body.get("nurse_id"), "Nurse")
    school = resolve("schools", body.get("school_id"), "School")
    values = validate(body, [
        Field("nurse_id", "string"),
        Field("school_id", "string"),
        Field("weekday", "enum", enum=WEEKDAYS),
        Field("start_minute", "integer", minimum=0, exclusive_maximum=1440),
        Field("end_minute", "integer", maximum=1440),
        Field("effective_from", "datetime"),
        Field("effective_to", "datetime", required=False),
    ])
    start = values["start_minute"]
    end = values["end_minute"]
    if end <= start:
        fail("ERR_INVALID_FIELD_VALUE", "end_minute must be greater than start_minute.")
    effective_from = parse_dt(values["effective_from"])
    effective_to = parse_dt(values["effective_to"]) if supplied(values, "effective_to") else None

    # Ladder position 33 - interval rule 1 (pairwise, half-open, travel buffer)
    for other in calc.nurse_blocks(nurse["id"]):
        if calc.coverage_status(other) not in ("SCHEDULED", "ACTIVE"):
            continue
        if other["weekday"] != values["weekday"]:
            continue
        if not _ranges_overlap(effective_from, effective_to,
                               other["effective_from"], other.get("effective_to")):
            continue
        if other["school_id"] == school["id"]:
            if start < other["end_minute"] and other["start_minute"] < end:
                fail("ERR_COVERAGE_OVERLAP",
                     "The block overlaps an existing block at the same building.")
        else:
            buffer_minutes = calc.TRAVEL_BUFFER_MINUTES
            if not (start >= other["end_minute"] + buffer_minutes
                    or other["start_minute"] >= end + buffer_minutes):
                fail("ERR_COVERAGE_OVERLAP",
                     "The block leaves less than %d minutes of travel buffer."
                     % buffer_minutes)

    # Ladder position 47 - nurse minute conservation
    duration = end - start
    if nurse["uncommitted_weekly_minutes"] - duration < 0:
        fail("ERR_NURSE_HOURS_EXCEEDED",
             "The block would overdraw the nurse's contracted week.")
    nurse["committed_weekly_minutes"] += duration
    nurse["uncommitted_weekly_minutes"] -= duration
    touch(nurse)

    record = new_record({
        "nurse_id": nurse["id"],
        "school_id": school["id"],
        "weekday": values["weekday"],
        "start_minute": start,
        "end_minute": end,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "minutes_returned": False,
    })
    insert("coverage_assignments", record)
    return created(ser.coverage_json(record))


@bp.get("/health-office/coverage-assignments")
def list_coverage():
    authorize(ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("coverage_assignments")
    nurse_id = request.args.get("nurse_id")
    school_id = request.args.get("school_id")
    weekday = request.args.get("weekday")
    status = request.args.get("status")
    if nurse_id:
        result = [r for r in result if r["nurse_id"] == nurse_id]
    if school_id:
        result = [r for r in result if r["school_id"] == school_id]
    if weekday:
        result = [r for r in result if r["weekday"] == weekday]
    if status:
        result = [r for r in result if calc.coverage_status(r) == status]
    return listing([ser.coverage_json(r) for r in sorted_rows(result)], limit, offset)


@bp.get("/health-office/coverage-assignments/<block_id>")
def get_coverage(block_id):
    authorize(ALL_READ_ROLES)
    block = must_exist("coverage_assignments", block_id, "CoverageAssignment")
    return ok(ser.coverage_json(block))


@bp.post("/health-office/coverage-assignments/<block_id>/end")
def end_coverage(block_id):
    authorize(["DistrictHealthAdmin"])
    block = must_exist("coverage_assignments", block_id, "CoverageAssignment")
    body = get_body(request)
    values = validate(body, [Field("effective_to", "datetime")])
    block["effective_to"] = parse_dt(values["effective_to"])
    if not block.get("minutes_returned"):
        nurse = db.nurses.get(block["nurse_id"])
        if nurse is not None:
            duration = calc.duration_minutes(block)
            nurse["committed_weekly_minutes"] -= duration
            nurse["uncommitted_weekly_minutes"] += duration
            touch(nurse)
        block["minutes_returned"] = True
    touch(block)
    return ok(ser.coverage_json(block))
