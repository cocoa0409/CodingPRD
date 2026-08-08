"""Portable units, sterilization loads and staff records."""

from flask import Blueprint

import calc
import cascades
import clock
import gates
import serializers
import store
import validation as v
from constants import (
    ENUM_CREDENTIAL_STATUS,
    ENUM_SPORE_RESULT,
    ENUM_STAFF_ROLE,
    ENUM_SUPERVISION_LEVEL,
    SPORE_INCUBATION_HOURS,
)
from envelope import array_response, object_response
from errors import ApiError
from timefmt import add_hours

bp = Blueprint("equipment", __name__)


# --------------------------------------------------------------------------
# Portable units
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/portable-units", methods=["POST"])
def create_portable_unit():
    v.authenticate(["ProgramAdmin"])
    body = v.body()
    unit_code = v.req_string(body, "unit_code")
    for existing in store.all_rows("portable_units"):
        if existing["unit_code"] == unit_code:
            raise ApiError("ERR_VALIDATION", "unit_code must be unique.")
    row = store.insert("portable_units", {
        "unit_code": unit_code,
        "status": "AVAILABLE",
        "last_calibrated_on": None,
        "last_passed_load_at": None,
        "quarantined_at": None,
    })
    v.mark_minted(row)
    return object_response(serializers.portable_unit(row), 201)


@bp.route("/mobile-dentistry/portable-units/<unit_id>", methods=["GET"])
def read_portable_unit(unit_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator", "FieldDentist", "DentalAssistant"])
    row = v.path_row("portable_units", unit_id)
    return object_response(serializers.portable_unit(row), 200)


@bp.route("/mobile-dentistry/portable-units/<unit_id>/calibrate", methods=["POST"])
def calibrate_portable_unit(unit_id):
    v.authenticate(["ProgramAdmin", "DentalAssistant"])
    row = v.path_row("portable_units", unit_id)
    body = v.body()
    calibrated_on = v.req_date(body, "calibrated_on")
    row["last_calibrated_on"] = calibrated_on
    v.touch(row)
    return object_response(serializers.portable_unit(row), 200)


# --------------------------------------------------------------------------
# Sterilization loads
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/sterilization-loads", methods=["POST"])
def create_sterilization_load():
    v.authenticate(["ProgramAdmin", "DentalAssistant", "FieldHygienist"])
    body = v.body()
    unit = v.fk_row(body, "portable_unit_id", "portable_units")
    loader = v.fk_row(body, "loaded_by_staff_id", "staff_members")
    visit = v.fk_row(body, "site_visit_id", "site_visits")

    for field in ("portable_unit_id", "loaded_by_staff_id"):
        v.need(body, field)
        if not isinstance(body.get(field), str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
    load_number = v.req_string(body, "load_number")
    cycle_completed_at = v.req_instant(body, "cycle_completed_at")
    if "site_visit_id" in body and body["site_visit_id"] is not None and not isinstance(body["site_visit_id"], str):
        raise ApiError("ERR_VALIDATION", "Field 'site_visit_id' must be a string.")

    period_id = gates.period_for_site_visit(visit) if visit else None
    gates.period_gate(period_id)

    row = store.insert("sterilization_loads", {
        "portable_unit_id": unit["id"],
        "site_visit_id": visit["id"] if visit else None,
        "loaded_by_staff_id": loader["id"],
        "result_recorded_by_staff_id": None,
        "load_number": load_number,
        "cycle_completed_at": cycle_completed_at,
        "incubation_ends_at": add_hours(cycle_completed_at, SPORE_INCUBATION_HOURS),
        "spore_result": "PENDING",
        "result_recorded_at": None,
        "auto_failed": False,
        "tainted_procedure_count": 0,
    })
    v.mark_minted(row)
    gates.mark_period_reports_stale(period_id)
    return object_response(serializers.sterilization_load(row), 201)


@bp.route("/mobile-dentistry/sterilization-loads", methods=["GET"])
def list_sterilization_loads():
    v.authenticate(["ProgramAdmin", "DentalAssistant", "FieldHygienist", "FieldDentist"])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("sterilization_loads"), {
        "portable_unit_id": "portable_unit_id",
        "site_visit_id": "site_visit_id",
        "loaded_by_staff_id": "loaded_by_staff_id",
        "result_recorded_by_staff_id": "result_recorded_by_staff_id",
        "spore_result": "spore_result",
    })
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.sterilization_load, page), limit, offset, total)


@bp.route("/mobile-dentistry/sterilization-loads/<load_id>", methods=["GET"])
def read_sterilization_load(load_id):
    v.authenticate(["ProgramAdmin", "DentalAssistant", "FieldHygienist", "FieldDentist"])
    row = v.path_row("sterilization_loads", load_id)
    return object_response(serializers.sterilization_load(row), 200)


@bp.route("/mobile-dentistry/sterilization-loads/<load_id>/spore-result", methods=["POST"])
def record_spore_result(load_id):
    v.authenticate(["DentalAssistant", "FieldHygienist", "FieldDentist"])
    row = v.path_row("sterilization_loads", load_id)
    body = v.body()
    reader = v.fk_row(body, "result_recorded_by_staff_id", "staff_members")

    v.enum_type_check(body, "result", required=True)
    v.need(body, "result_recorded_by_staff_id")
    if not isinstance(body.get("result_recorded_by_staff_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'result_recorded_by_staff_id' must be a string.")

    result = v.check_enum(body, "result", ENUM_SPORE_RESULT)

    period_id = gates.period_for_sterilization_load(row)
    gates.period_gate(period_id)

    # Rung 11 -- the reading is declared only out of PENDING.
    if row["spore_result"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")

    # Rung 14 -- segregation of duties.
    if reader["id"] == row["loaded_by_staff_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # Rung 17 clause (b) -- this load's own incubation must have finished.
    if clock.now() < row["incubation_ends_at"]:
        raise ApiError("ERR_SPORE_RESULT_PENDING")

    unit = store.get("portable_units", row["portable_unit_id"])

    if result == "PASSED":
        row["spore_result"] = "PASSED"
        row["result_recorded_at"] = clock.now()
        row["result_recorded_by_staff_id"] = reader["id"]
        v.touch(row)
        unit["last_passed_load_at"] = row["cycle_completed_at"]
        if unit["status"] == "QUARANTINED":
            unit["status"] = "AVAILABLE"
            unit["quarantined_at"] = None
        v.touch(unit)
    else:
        cascades.run_failed_spore_cascade(row, unit, recorded_by_staff_id=reader["id"], auto_failed=False)

    gates.mark_period_reports_stale(period_id)
    return object_response(serializers.sterilization_load(row), 200)


# --------------------------------------------------------------------------
# Staff members
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/staff-members", methods=["POST"])
def create_staff_member():
    v.authenticate(["ProgramAdmin"])
    body = v.body()
    full_name = v.req_string(body, "full_name")
    v.enum_type_check(body, "staff_role", required=True)
    license_number = v.req_string(body, "license_number")
    license_state = v.req_state_code(body, "license_state")
    v.enum_type_check(body, "supervision_level", required=True)
    v.enum_type_check(body, "credential_status")
    credential_expires_on = v.opt_date(body, "credential_expires_on")

    staff_role = v.check_enum(body, "staff_role", ENUM_STAFF_ROLE)
    supervision_level = v.check_enum(body, "supervision_level", ENUM_SUPERVISION_LEVEL)
    credential_status = v.check_enum(body, "credential_status", ENUM_CREDENTIAL_STATUS)

    row = store.insert("staff_members", {
        "full_name": full_name,
        "staff_role": staff_role,
        "license_number": license_number,
        "license_state": license_state,
        "supervision_level": supervision_level,
        "credential_status": credential_status or "ACTIVE",
        "credential_expires_on": credential_expires_on,
    })
    v.mark_minted(row)
    return object_response(serializers.staff_member(row), 201)


@bp.route("/mobile-dentistry/staff-members/<staff_id>", methods=["GET"])
def read_staff_member(staff_id):
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "DentalAssistant",
    ])
    row = v.path_row("staff_members", staff_id)
    return object_response(serializers.staff_member(row), 200)


@bp.route("/mobile-dentistry/staff-members/<staff_id>", methods=["PATCH"])
def update_staff_member(staff_id):
    v.authenticate(["ProgramAdmin"])
    row = v.path_row("staff_members", staff_id)
    body = v.body()

    v.enum_type_check(body, "credential_status")
    v.enum_type_check(body, "supervision_level")
    license_state = v.opt_state_code(body, "license_state")
    has_expiry = "credential_expires_on" in body
    credential_expires_on = v.opt_date(body, "credential_expires_on")

    credential_status = v.check_enum(body, "credential_status", ENUM_CREDENTIAL_STATUS)
    supervision_level = v.check_enum(body, "supervision_level", ENUM_SUPERVISION_LEVEL)

    if credential_status is not None:
        row["credential_status"] = credential_status
    if supervision_level is not None:
        row["supervision_level"] = supervision_level
    if license_state is not None:
        row["license_state"] = license_state
    if has_expiry:
        row["credential_expires_on"] = credential_expires_on
    v.touch(row)
    return object_response(serializers.staff_member(row), 200)
