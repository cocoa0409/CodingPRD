"""Patients (PRD §3.2)."""
from flask import Blueprint

import errors
from db import store
from middleware import require_auth_and_roles
from response import success, list_response
from services.common import (
    base_record,
    check_fk,
    get_json_body,
    get_or_404,
    list_collection,
    require_field,
    serialize,
    validate_enum,
    validate_number,
    validate_non_empty_string,
)

bp = Blueprint("patients", __name__)

ALL_READ_ROLES = ["Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"]
AGE_BANDS = {"ADOLESCENT", "ADULT"}


@bp.route("/edt/patients", methods=["POST"])
@require_auth_and_roles(["Intake", "Admin"])
def create_patient():
    body = get_json_body()
    facility_id = require_field(body, "facility_id")
    full_name = validate_non_empty_string(require_field(body, "full_name"), "full_name")
    age_band = validate_enum(require_field(body, "age_band"), "age_band", AGE_BANDS)
    # bmi: a positive number (PRD §3.2).
    bmi = validate_number(require_field(body, "bmi"), "bmi", exclusive_min=0)
    with store.lock:
        check_fk("facility_id", facility_id)
        rec = base_record()
        # Fresh patient starts STABLE, version 1, both nutritional figures 0,
        # active_assessment_id null (PRD §3.2).
        rec.update({
            "facility_id": facility_id,
            "full_name": full_name,
            "age_band": age_band,
            "bmi": bmi,
            "medical_stability_posture": "STABLE",
            "nutritional_risk_score": 0,
            "provisional_nutritional_risk_score": 0,
            "active_assessment_id": None,
        })
        store.patients[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/patients", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_patients():
    page, limit, offset, total = list_collection("patients", filters={"facility_id": "facility_id"})
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/patients/<pid>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_patient(pid):
    rec = get_or_404("patients", pid, errors.ERR_PATIENT_NOT_FOUND)
    return success(serialize(rec), status=200)
