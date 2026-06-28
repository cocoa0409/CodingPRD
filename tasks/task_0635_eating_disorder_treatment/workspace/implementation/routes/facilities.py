"""Facilities, Programs, Cohorts (PRD §3.1)."""
from flask import Blueprint

import errors
from db import store
from errors import ApiError
from middleware import require_auth_and_roles
from response import success, list_response
from services.common import (
    base_record,
    check_fk,
    get_json_body,
    get_optional_json_body,
    get_or_404,
    list_collection,
    require_field,
    serialize,
    touch,
    validate_enum,
    validate_int,
    validate_non_empty_string,
)
from services.domain import recompute_program_counters

bp = Blueprint("facilities", __name__)

ALL_READ_ROLES = ["Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"]
LOC_VALUES = {"RESIDENTIAL", "PHP", "IOP", "OP"}
AGE_BANDS = {"ADOLESCENT", "ADULT"}


# --------------------------- Facilities ---------------------------
@bp.route("/edt/facilities", methods=["POST"])
@require_auth_and_roles(["Admin"])
def create_facility():
    body = get_json_body()
    name = validate_non_empty_string(require_field(body, "name"), "name")
    timezone = body.get("timezone", "UTC")
    if "timezone" in body and body["timezone"] is not None:
        timezone = validate_non_empty_string(body["timezone"], "timezone")
    with store.lock:
        rec = base_record()
        rec.update({"name": name, "timezone": timezone})
        store.facilities[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/facilities", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_facilities():
    page, limit, offset, total = list_collection("facilities")
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/facilities/<fid>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_facility(fid):
    rec = get_or_404("facilities", fid, errors.ERR_FACILITY_NOT_FOUND)
    return success(serialize(rec), status=200)


# --------------------------- Programs ---------------------------
@bp.route("/edt/programs", methods=["POST"])
@require_auth_and_roles(["Admin"])
def create_program():
    body = get_json_body()
    facility_id = require_field(body, "facility_id")
    level_of_care = validate_enum(require_field(body, "level_of_care"), "level_of_care", LOC_VALUES)
    bed_capacity = validate_int(require_field(body, "bed_capacity"), "bed_capacity", minimum=1)
    with store.lock:
        check_fk("facility_id", facility_id)
        rec = base_record()
        rec.update({
            "facility_id": facility_id,
            "level_of_care": level_of_care,
            "bed_capacity": bed_capacity,
            "beds_occupied": 0,
            "beds_available": bed_capacity,
            "occupancy_posture": "OPEN",
            "status": "OPEN",
        })
        store.programs[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/programs", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_programs():
    page, limit, offset, total = list_collection(
        "programs", filters={"facility_id": "facility_id", "level_of_care": "level_of_care"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/programs/<pgid>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_program(pgid):
    rec = get_or_404("programs", pgid, errors.ERR_PROGRAM_NOT_FOUND)
    return success(serialize(rec), status=200)


@bp.route("/edt/programs/<pgid>/close", methods=["POST"])
@require_auth_and_roles(["Admin"])
def close_program(pgid):
    get_optional_json_body()
    with store.lock:
        rec = get_or_404("programs", pgid, errors.ERR_PROGRAM_NOT_FOUND)
        # Closing moves status to CLOSED; derived bed counters are untouched
        # (PRD §3.1). No INVALID_STATE guard is specified for close.
        rec["status"] = "CLOSED"
        touch(rec)
        return success(serialize(rec), status=200)


# --------------------------- Cohorts ---------------------------
@bp.route("/edt/cohorts", methods=["POST"])
@require_auth_and_roles(["Admin", "Intake"])
def create_cohort():
    body = get_json_body()
    program_id = require_field(body, "program_id")
    facility_id = require_field(body, "facility_id")
    name = validate_non_empty_string(require_field(body, "name"), "name")
    age_band = validate_enum(require_field(body, "age_band"), "age_band", AGE_BANDS)
    slot_capacity = validate_int(require_field(body, "slot_capacity"), "slot_capacity", minimum=1)
    with store.lock:
        check_fk("program_id", program_id)
        check_fk("facility_id", facility_id)
        rec = base_record()
        rec.update({
            "program_id": program_id,
            "facility_id": facility_id,
            "name": name,
            "age_band": age_band,
            "slot_capacity": slot_capacity,
            "slots_filled": 0,
        })
        store.cohorts[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/cohorts", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_cohorts():
    page, limit, offset, total = list_collection(
        "cohorts", filters={"program_id": "program_id", "facility_id": "facility_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/cohorts/<cid>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_cohort(cid):
    rec = get_or_404("cohorts", cid, errors.ERR_COHORT_NOT_FOUND)
    return success(serialize(rec), status=200)
