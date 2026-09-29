"""Logical clock, monitoring units, beds and technologist coverage windows."""
from datetime import timedelta

import cascade
import clock
import config
import derive
import response
import validation
from db import base_record, db, insert
from errors import ApiError
from web import ListResult, ObjectResult, RawResult, bp, endpoint, get_shift, get_unit

ALL_ROLES = config.ROLES
READ_UNIT_ROLES = ("UnitCoordinator", "Technologist", "Nurse", "Epileptologist")
SHIFT_READ_ROLES = ("UnitCoordinator", "Technologist", "Epileptologist")


# --- logical clock --------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(roles=ALL_ROLES, mutating=False)
def set_current_utc(user_id, role):
    data = validation.body()
    target = validation.req_datetime(data, "to_iso8601")
    if target < clock.now():
        raise ApiError("ERR_CLOCK_MONOTONIC",
                       "The logical clock may not move backwards.")
    clock.set_now(target)
    return RawResult({"current_utc": clock.iso(target)})


# --- monitoring units ----------------------------------------------------

@bp.route("/neurodiagnostics/units", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def create_unit(user_id, role):
    data = validation.body()
    name = validation.req_string(data, "name")
    bed_count = validation.req_int(data, "bed_count", minimum=1)
    quota = validation.req_number(data, "storage_quota_gb", exclusive_minimum=0)
    unit = base_record("unit")
    unit.update({
        "name": name,
        "bed_count": bed_count,
        "storage_quota_gb": quota,
        "retention_sweep_index": 0,
    })
    insert("units", unit)
    return ObjectResult(unit, 201)


@bp.route("/neurodiagnostics/units/<unit_id>", methods=["GET"])
@endpoint(roles=READ_UNIT_ROLES)
def read_unit(user_id, role, unit_id):
    return ObjectResult(get_unit(unit_id))


@bp.route("/neurodiagnostics/units/<unit_id>/retention-sweep", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def retention_sweep(user_id, role, unit_id):
    unit = get_unit(unit_id)
    now = clock.now()
    unit["retention_sweep_index"] += 1
    for package in derive.packages_of_unit(unit["id"]):
        if package["status"] not in ("BUILT", "DELIVERED"):
            continue
        expires_at = package.get("retention_expires_at")
        if expires_at is not None and now >= expires_at:
            package["status"] = "PURGED"
    for study in derive.studies_of_unit(unit["id"]):
        if study["data_state"] != "ARCHIVED":
            continue
        admission = db.admissions.get(study["admission_id"])
        if admission is not None and admission["clinical_state"] == "DISCHARGED":
            study["data_state"] = "PURGED"
    return ObjectResult(unit)


# --- beds ----------------------------------------------------------------

@bp.route("/neurodiagnostics/beds", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def create_bed(user_id, role):
    data = validation.body()
    unit_id = validation.req_id(data, "unit_id")
    label = validation.req_string(data, "label")
    get_unit(unit_id)
    bed = base_record("bed")
    bed.update({
        "unit_id": unit_id,
        "label": label,
        "released_at": None,
        "turnover_clear_at": None,
    })
    insert("beds", bed)
    return ObjectResult(bed, 201)


@bp.route("/neurodiagnostics/units/<unit_id>/beds", methods=["GET"])
@endpoint(roles=READ_UNIT_ROLES)
def list_unit_beds(user_id, role, unit_id):
    from flask import request
    get_unit(unit_id)
    limit, offset = response.read_pagination(request.args)
    records = derive.ordered(derive.beds_of_unit(unit_id))
    return ListResult(records, limit, offset)


# --- technologist shifts -------------------------------------------------

@bp.route("/neurodiagnostics/technologist-shifts", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def create_shift(user_id, role):
    data = validation.body()
    unit_id = validation.req_id(data, "unit_id")
    technologist_user_id = validation.req_string(data, "technologist_user_id")
    starts_at = validation.req_datetime(data, "starts_at")
    ends_at = validation.req_datetime(data, "ends_at")
    max_concurrent = validation.req_int(data, "max_concurrent_studies", minimum=1)
    get_unit(unit_id)
    if not ends_at > starts_at:
        raise ApiError("ERR_SHIFT_WINDOW_INVALID",
                       "ends_at must be strictly after starts_at.")
    shift = base_record("shift")
    shift.update({
        "unit_id": unit_id,
        "technologist_user_id": technologist_user_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "max_concurrent_studies": max_concurrent,
        "state": "SCHEDULED",
    })
    insert("shifts", shift)
    return ObjectResult(shift, 201)


@bp.route("/neurodiagnostics/units/<unit_id>/technologist-shifts", methods=["GET"])
@endpoint(roles=SHIFT_READ_ROLES)
def list_unit_shifts(user_id, role, unit_id):
    from flask import request
    get_unit(unit_id)
    limit, offset = response.read_pagination(request.args)
    records = derive.ordered(derive.shifts_of_unit(unit_id))
    return ListResult(records, limit, offset)


@bp.route("/neurodiagnostics/technologist-shifts/<shift_id>", methods=["GET"])
@endpoint(roles=SHIFT_READ_ROLES)
def read_shift(user_id, role, shift_id):
    return ObjectResult(get_shift(shift_id))


@bp.route("/neurodiagnostics/technologist-shifts/<shift_id>/activate", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def activate_shift(user_id, role, shift_id):
    shift = get_shift(shift_id)
    if shift["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SHIFT_STATE",
                       "Only a SCHEDULED coverage window may be activated.")
    shift["state"] = "ACTIVE"
    return ObjectResult(shift)


@bp.route("/neurodiagnostics/technologist-shifts/<shift_id>/close", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def close_shift(user_id, role, shift_id):
    shift = get_shift(shift_id)
    if shift["state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_SHIFT_STATE",
                       "Only an ACTIVE coverage window may be closed.")
    if derive.shift_assigned_study_count(shift) > 0:
        raise ApiError("ERR_SHIFT_HAS_ACTIVE_STUDIES",
                       "The coverage window still carries acquisitions.")
    shift["state"] = "CLOSED"
    return ObjectResult(shift)
