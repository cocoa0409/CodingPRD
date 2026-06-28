"""Assessments and finalize (PRD §3.2, §3.3, §2.5)."""
from flask import Blueprint

import errors
from db import store
from errors import ApiError
from middleware import require_auth_and_roles
from response import success, list_response
from services import calc
from services.common import (
    base_record,
    check_fk,
    get_json_body,
    get_or_404,
    list_collection,
    require_field,
    serialize,
    touch,
    validate_int,
)
from services.domain import recompute_patient_posture, set_patient_number

bp = Blueprint("assessments", __name__)

ALL_READ_ROLES = ["Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"]


@bp.route("/edt/assessments", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def create_assessment():
    body = get_json_body()
    patient_id = require_field(body, "patient_id")
    facility_id = require_field(body, "facility_id")
    medical = validate_int(require_field(body, "medical_severity"), "medical_severity", 0, 10)
    behavioral = validate_int(require_field(body, "behavioral_severity"), "behavioral_severity", 0, 10)
    psychiatric = validate_int(require_field(body, "psychiatric_severity"), "psychiatric_severity", 0, 10)
    motivation = validate_int(require_field(body, "motivation_level"), "motivation_level", 0, 10)
    with store.lock:
        check_fk("patient_id", patient_id)
        check_fk("facility_id", facility_id)
        comp = calc.composite_score(medical, behavioral, psychiatric, motivation)
        rec = base_record()
        rec.update({
            "patient_id": patient_id,
            "facility_id": facility_id,
            "medical_severity": medical,
            "behavioral_severity": behavioral,
            "psychiatric_severity": psychiatric,
            "motivation_level": motivation,
            "composite_score": calc._to_number(comp),
            "recommended_level_of_care": calc.recommended_loc(comp),
            "status": "DRAFT",
        })
        store.assessments[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/assessments", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_assessments():
    page, limit, offset, total = list_collection(
        "assessments", filters={"patient_id": "patient_id", "facility_id": "facility_id"}
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/assessments/<asid>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_assessment(asid):
    rec = get_or_404("assessments", asid, errors.ERR_ASSESSMENT_NOT_FOUND)
    return success(serialize(rec), status=200)


@bp.route("/edt/assessments/<asid>/finalize", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def finalize_assessment(asid):
    body = get_json_body()
    # expected_patient_version is mandatory (PRD §2.5).
    expected_version = require_field(body, "expected_patient_version")
    with store.lock:
        assessment = get_or_404("assessments", asid, errors.ERR_ASSESSMENT_NOT_FOUND)
        patient = store.patients.get(assessment["patient_id"])
        # The patient referenced by the assessment always exists (created via FK).

        # Priority 5: OCC check before any state/business logic (PRD §2.5, §2.6).
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_patient_version must be an integer.")
        if expected_version != patient["version"]:
            raise ApiError(errors.ERR_STALE_VERSION, 412, "Stale patient version.")

        # Priority 6: legal-state check. Finalize is legal only from DRAFT.
        if assessment["status"] != "DRAFT":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Assessment is not DRAFT.")

        # Supersede the prior governing assessment, if any.
        prior_id = patient.get("active_assessment_id")
        if prior_id and prior_id in store.assessments:
            prior = store.assessments[prior_id]
            prior["status"] = "SUPERSEDED"
            touch(prior)

        assessment["status"] = "FINALIZED"
        touch(assessment)

        patient["active_assessment_id"] = assessment["id"]

        # Seed provisional risk from composite + bmi bonus; both figures set.
        prov = calc.provisional_risk(assessment["composite_score"], patient["bmi"])
        set_patient_number(patient, "provisional_nutritional_risk_score", prov)
        set_patient_number(patient, "nutritional_risk_score", prov)
        recompute_patient_posture(patient)

        # increments Patient.version by 1 (touch bumps version + updated_at).
        touch(patient)

        return success(serialize(assessment), status=200)
