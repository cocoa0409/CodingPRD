"""Patient registration, revision and referral listing (PRD 3.1)."""

from flask import Blueprint

import envelope
import ladder
import serializers
import store
from routes.common import apply_filter, endpoint
from store import DB

bp = Blueprint("patients", __name__)

DIAGNOSIS_CODES = (
    "CHF_EXAC", "COPD_EXAC", "CAP_PNEUMONIA", "CELLULITIS",
    "UTI_COMPLICATED", "COVID_MODERATE", "OTHER",
)
DIET_CODES = ("NONE", "LOW_SODIUM", "RENAL", "CARB_CONTROLLED", "PUREED")

READ_ROLES = [
    "ProgramAdmin", "AdmittingPhysician", "FieldNurse", "CommunityParamedic",
    "LogisticsCoordinator", "BillingAnalyst", "Patient",
]


@endpoint(bp, "/patients", ["POST"], ["ProgramAdmin", "AdmittingPhysician"])
def create_patient(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["mrn", "full_name", "home_distance_km", "primary_diagnosis_code"])
    # rung 4b
    ladder.check_enum(body, "primary_diagnosis_code", DIAGNOSIS_CODES)
    ladder.check_enum(body, "diet_restriction", DIET_CODES)
    # rung 4c
    ladder.check_non_empty_string(body, "mrn")
    ladder.check_non_empty_string(body, "full_name")
    ladder.check_number_min(body, "home_distance_km", 0)
    ladder.check_boolean(body, "broadband_verified")
    ladder.check_boolean(body, "caregiver_present")
    ladder.check_unique("patients", "mrn", body["mrn"])

    row = store.make_row("patients", {
        "mrn": body["mrn"],
        "full_name": body["full_name"],
        "home_distance_km": body["home_distance_km"],
        "primary_diagnosis_code": body["primary_diagnosis_code"],
        "diet_restriction": body.get("diet_restriction") or "NONE",
        "broadband_verified": body.get("broadband_verified", False) or False,
        "caregiver_present": body.get("caregiver_present", False) or False,
        "status": "REGISTERED",
    })
    return envelope.ObjResult(row, serializers.patient, 201)


@endpoint(bp, "/patients/<patient_id>", ["GET"], READ_ROLES)
def get_patient(caller, patient_id):
    row = ladder.path_row("patients", patient_id)
    return envelope.ObjResult(row, serializers.patient, 200)


@endpoint(bp, "/patients/<patient_id>", ["PATCH"], ["ProgramAdmin", "AdmittingPhysician"])
def update_patient(caller, patient_id):
    # rung 3
    row = ladder.path_row("patients", patient_id)
    body = ladder.json_body()
    # rung 4b
    ladder.check_enum(body, "diet_restriction", DIET_CODES)
    # rung 4c
    ladder.check_number_min(body, "home_distance_km", 0)
    ladder.check_boolean(body, "broadband_verified")
    ladder.check_boolean(body, "caregiver_present")

    for field in ("home_distance_km", "diet_restriction", "broadband_verified", "caregiver_present"):
        if field in body and body[field] is not None:
            row[field] = body[field]
    store.touch(row)
    return envelope.ObjResult(row, serializers.patient, 200)


@endpoint(bp, "/patients/<patient_id>/referrals", ["GET"],
          ["ProgramAdmin", "AdmittingPhysician", "Patient"])
def list_patient_referrals(caller, patient_id):
    # rung 3
    ladder.path_row("patients", patient_id)
    # rung 4c
    limit, offset = ladder.pagination_params()
    rows = [r for r in DB.referrals.values() if r["patient_id"] == patient_id]
    rows = apply_filter(rows, "status")
    return envelope.ListResult(store.ordered(rows), serializers.referral, limit, offset)
