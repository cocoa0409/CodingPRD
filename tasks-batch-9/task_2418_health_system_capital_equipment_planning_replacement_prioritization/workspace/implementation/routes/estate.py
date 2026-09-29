"""Facilities and departments (PRD section 3.1)."""

import re

from flask import Blueprint

import lookups
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import CAPITAL_PLANNER, guard
from response import created_response, object_response
from validation import (body, enum_field, int_field, pagination, q_bool, q_str,
                        raw_ref, str_field)

bp = Blueprint("estate", __name__)

REGIONS = ("NORTH", "SOUTH", "EAST", "WEST")
MODALITIES = ("CT", "MRI", "CATH_LAB", "ULTRASOUND", "LAB", "SURGICAL")
CODE_RE = re.compile(r"^[A-Z0-9]{2,8}\Z")


# ------------------------------------------------------------------ Facility

@bp.route("/capital/facilities", methods=["POST"])
@guard(CAPITAL_PLANNER)
def create_facility():
    data = body()
    name = str_field(data, "name", 1, 120, non_blank=True)
    code = str_field(data, "code", 2, 8)
    if CODE_RE.match(code) is None:
        raise ApiError("ERR_VALIDATION")
    region = enum_field(data, "region", REGIONS)
    ceiling = int_field(data, "max_concurrent_construction", 1, 5,
                        required=False, default=1)

    for row in db.facilities.values():
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_KEY")

    row = new_row({
        "name": name,
        "code": code,
        "region": region,
        "max_concurrent_construction": ceiling,
        "active_asset_count": 0,
    })
    db.facilities[row["id"]] = row
    return created_response(serializers.facility(row))


@bp.route("/capital/facilities/<facility_id>", methods=["PATCH"])
@guard(CAPITAL_PLANNER)
def patch_facility(facility_id):
    row = lookups.facility(facility_id)
    data = body()
    name = str_field(data, "name", 1, 120, required=False, non_blank=True)
    region = enum_field(data, "region", REGIONS, required=False)
    ceiling = int_field(data, "max_concurrent_construction", 1, 5, required=False)

    if name is not None:
        row["name"] = name
    if region is not None:
        row["region"] = region
    if ceiling is not None:
        row["max_concurrent_construction"] = ceiling
    touch(row)
    return object_response(serializers.facility(row))


@bp.route("/capital/facilities/<facility_id>", methods=["GET"])
@guard()
def get_facility(facility_id):
    return object_response(serializers.facility(lookups.facility(facility_id)))


@bp.route("/capital/facilities", methods=["GET"])
@guard()
def list_facilities():
    limit, offset = pagination()
    rows = lookups.filtered(db.facilities.values(), [
        ("region", q_str("region")),
        ("code", q_str("code")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.facility)


# ---------------------------------------------------------------- Department

@bp.route("/capital/departments", methods=["POST"])
@guard(CAPITAL_PLANNER)
def create_department():
    data = body()
    ref = raw_ref(data, "facility_id")
    if ref is not None:
        lookups.facility(ref)

    facility_id = str_field(data, "facility_id", 1, None)
    facility = lookups.facility(facility_id)
    name = str_field(data, "name", 1, 120)
    modality_scope = enum_field(data, "modality_scope", MODALITIES)

    row = new_row({
        "facility_id": facility["id"],
        "name": name,
        "modality_scope": modality_scope,
        "utilization_penalty_points": 0,
        "underperformance_flag": False,
    })
    db.departments[row["id"]] = row
    return created_response(serializers.department(row))


@bp.route("/capital/departments/<department_id>", methods=["PATCH"])
@guard(CAPITAL_PLANNER)
def patch_department(department_id):
    row = lookups.department(department_id)
    data = body()
    name = str_field(data, "name", 1, 120, required=False)
    modality_scope = enum_field(data, "modality_scope", MODALITIES, required=False)

    if name is not None:
        row["name"] = name
    if modality_scope is not None:
        row["modality_scope"] = modality_scope
    touch(row)
    return object_response(serializers.department(row))


@bp.route("/capital/departments/<department_id>", methods=["GET"])
@guard()
def get_department(department_id):
    return object_response(
        serializers.department(lookups.department(department_id)))


@bp.route("/capital/departments", methods=["GET"])
@guard()
def list_departments():
    limit, offset = pagination()
    rows = lookups.filtered(db.departments.values(), [
        ("facility_id", q_str("facility_id")),
        ("modality_scope", q_str("modality_scope")),
        ("underperformance_flag", q_bool("underperformance_flag")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.department)
