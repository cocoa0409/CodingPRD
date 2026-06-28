"""Family-program enrollment and discharge plans (PRD §3.10)."""
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
    validate_bool,
    validate_enum,
    validate_int,
    validate_non_empty_string,
)

bp = Blueprint("family_discharge", __name__)

ALL_READ_ROLES = ["Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"]


# --------------------------- family programs ---------------------------
@bp.route("/edt/family-programs", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def create_family_program():
    body = get_json_body()
    admission_id = require_field(body, "admission_id")
    facility_id = require_field(body, "facility_id")
    family_contact_name = validate_non_empty_string(
        require_field(body, "family_contact_name"), "family_contact_name"
    )
    sessions_required = validate_int(require_field(body, "sessions_required"), "sessions_required", minimum=0)
    with store.lock:
        check_fk("admission_id", admission_id)
        check_fk("facility_id", facility_id)
        rec = base_record()
        rec.update({
            "admission_id": admission_id,
            "facility_id": facility_id,
            "family_contact_name": family_contact_name,
            "sessions_required": sessions_required,
            "sessions_completed": 0,
            "status": "ENROLLED",
        })
        store.family_programs[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/family-programs", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_family_programs():
    page, limit, offset, total = list_collection(
        "family_programs", filters={"admission_id": "admission_id", "facility_id": "facility_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/family-programs/<fp_id>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_family_program(fp_id):
    rec = get_or_404("family_programs", fp_id, errors.ERR_FAMILY_PROGRAM_NOT_FOUND)
    return success(serialize(rec), status=200)


@bp.route("/edt/family-programs/<fp_id>/complete-session", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def complete_session(fp_id):
    get_optional_json_body()
    with store.lock:
        fp = get_or_404("family_programs", fp_id, errors.ERR_FAMILY_PROGRAM_NOT_FOUND)
        fp["sessions_completed"] += 1
        # auto-advance to COMPLETED once completed >= required (PRD §3.10).
        if fp["sessions_completed"] >= fp["sessions_required"]:
            fp["status"] = "COMPLETED"
        touch(fp)
        return success(serialize(fp), status=200)


@bp.route("/edt/family-programs/<fp_id>/waive", methods=["POST"])
@require_auth_and_roles(["Clinician", "Admin"])
def waive(fp_id):
    get_optional_json_body()
    with store.lock:
        fp = get_or_404("family_programs", fp_id, errors.ERR_FAMILY_PROGRAM_NOT_FOUND)
        fp["status"] = "WAIVED"
        touch(fp)
        return success(serialize(fp), status=200)


# --------------------------- discharge plans ---------------------------
@bp.route("/edt/discharge-plans", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def create_discharge_plan():
    body = get_json_body()
    admission_id = require_field(body, "admission_id")
    facility_id = require_field(body, "facility_id")
    aftercare_level_of_care = validate_enum(
        require_field(body, "aftercare_level_of_care"),
        "aftercare_level_of_care",
        {"PHP", "IOP", "OP", "NONE"},
    )
    relapse_warning_signs = validate_non_empty_string(
        require_field(body, "relapse_warning_signs"), "relapse_warning_signs"
    )
    relapse_plan_complete = validate_bool(
        require_field(body, "relapse_plan_complete"), "relapse_plan_complete"
    )
    with store.lock:
        check_fk("admission_id", admission_id)
        check_fk("facility_id", facility_id)
        rec = base_record()
        rec.update({
            "admission_id": admission_id,
            "facility_id": facility_id,
            "aftercare_level_of_care": aftercare_level_of_care,
            "relapse_warning_signs": relapse_warning_signs,
            "relapse_plan_complete": relapse_plan_complete,
            "status": "DRAFT",
        })
        store.discharge_plans[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/discharge-plans", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_discharge_plans():
    page, limit, offset, total = list_collection(
        "discharge_plans", filters={"admission_id": "admission_id", "facility_id": "facility_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/discharge-plans/<dp_id>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_discharge_plan(dp_id):
    rec = get_or_404("discharge_plans", dp_id, errors.ERR_DISCHARGE_PLAN_NOT_FOUND)
    return success(serialize(rec), status=200)


@bp.route("/edt/discharge-plans/<dp_id>/finalize", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def finalize_discharge_plan(dp_id):
    get_optional_json_body()
    with store.lock:
        dp = get_or_404("discharge_plans", dp_id, errors.ERR_DISCHARGE_PLAN_NOT_FOUND)
        # legal only from DRAFT (PRD §3.10).
        if dp["status"] != "DRAFT":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Discharge plan is not DRAFT.")
        # requires relapse_plan_complete true.
        if not dp["relapse_plan_complete"]:
            raise ApiError(errors.ERR_RELAPSE_PLAN_INCOMPLETE, 409, "Relapse plan not complete.")
        dp["status"] = "FINALIZED"
        touch(dp)
        return success(serialize(dp), status=200)
