"""Facility declaration, sanitation validation, reads."""

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import (
    AIR_HANDLING_CLASSES,
    GLUTEN_OPERATIONS,
    READ_FACILITIES,
    ROLE_APPLICANT_CONTACT,
    ROLE_CERTIFICATION_REVIEWER,
    ROLE_FIELD_AUDITOR,
    SANITATION_METHODS,
    SANITATION_SWAB_LIMIT_PPM,
    SANITATION_VALIDITY_DAYS,
)
from errors import ApiError
from services import calc

bp = Blueprint("facilities", __name__)


@bp.post("/gfco/facilities")
def create_facility():
    user_id, _ = mw.authenticate([ROLE_APPLICANT_CONTACT])
    data = mw.body()
    applicant_id = mw.req_str(data, "applicant_id")
    site_name = mw.req_str(data, "site_name")
    air_handling_class = mw.req_enum(data, "air_handling_class", AIR_HANDLING_CLASSES)
    shared = mw.opt_bool(data, "shared_equipment_present", False)
    operations = mw.opt_enum(
        data, "gluten_containing_operations", GLUTEN_OPERATIONS, "NONE"
    )
    query.fetch("applicant", applicant_id)
    if applicant_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    row = db.insert(
        db.facilities,
        {
            "applicant_id": applicant_id,
            "site_name": site_name,
            "shared_equipment_present": shared,
            "gluten_containing_operations": operations,
            "air_handling_class": air_handling_class,
            "sanitation_validation_status": "UNVALIDATED",
            "sanitation_method": None,
            "sanitation_swab_ppm": None,
            "sanitation_validated_on": None,
            "sanitation_expires_on": None,
            "last_closed_audit_outcome": "NONE",
            "last_closed_audit_closed_on": None,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/facilities/<facility_id>")
def get_facility(facility_id):
    mw.authenticate(READ_FACILITIES)
    return response.ok(response.serialize(query.fetch("facility", facility_id)))


@bp.get("/gfco/facilities")
def list_facilities():
    mw.authenticate(READ_FACILITIES)
    return query.listing(
        db.facilities,
        {
            "applicant_id": query.arg("applicant_id"),
            "sanitation_validation_status": query.arg("sanitation_validation_status"),
        },
    )


@bp.post("/gfco/facilities/<facility_id>/sanitation-validation")
def validate_sanitation(facility_id):
    mw.authenticate([ROLE_CERTIFICATION_REVIEWER, ROLE_FIELD_AUDITOR])
    data = mw.body()
    swab_ppm = mw.req_num(data, "swab_ppm", minimum=0)
    method = mw.req_enum(data, "method", SANITATION_METHODS)
    validated_on = mw.req_dt(data, "validated_on")
    facility = query.fetch("facility", facility_id)
    if calc.dec(swab_ppm) > calc.dec(SANITATION_SWAB_LIMIT_PPM):
        raise ApiError("ERR_SANITATION_SWAB_ABOVE_LIMIT")
    facility["sanitation_validation_status"] = "VALIDATED"
    facility["sanitation_method"] = method
    facility["sanitation_swab_ppm"] = swab_ppm
    facility["sanitation_validated_on"] = validated_on
    facility["sanitation_expires_on"] = clock.add_days(
        validated_on, SANITATION_VALIDITY_DAYS
    )
    db.touch(facility)
    return response.ok(response.serialize(facility))
