"""Referral filing, the admission gauntlet, and eligibility assessments
(PRD 3.1)."""

from flask import Blueprint

import calc
import envelope
import errors
import ladder
import serializers
import store
from errors import fail
from routes.common import endpoint
from routes.patients import DIAGNOSIS_CODES
from store import DB

bp = Blueprint("referrals", __name__)

ORIGINS = ("ED", "INPATIENT_WARD", "CLINIC", "SNF")
ACUITIES = ("STANDARD", "HIGH")
SAFETY_OUTCOMES = ("PASS", "CONDITIONAL", "FAIL")
BROADBAND_OUTCOMES = ("PASS", "FAIL")


def referral_assessments(referral_id):
    rows = [a for a in DB.assessments.values() if a["referral_id"] == referral_id]
    return store.ordered(rows)


def latest_assessment(referral_id):
    rows = referral_assessments(referral_id)
    return rows[-1] if rows else None


@endpoint(bp, "/referrals", ["POST"], ["AdmittingPhysician"])
def create_referral(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, [
        "patient_id", "origin", "qualifying_condition_code", "acuity",
        "referring_physician_user_id",
    ])
    # rung 4b
    ladder.check_enum(body, "origin", ORIGINS)
    ladder.check_enum(body, "qualifying_condition_code", DIAGNOSIS_CODES)
    ladder.check_enum(body, "acuity", ACUITIES)
    # rung 4c
    ladder.check_string(body, "patient_id")
    ladder.check_string(body, "referring_physician_user_id")
    # rung 5
    ladder.body_patient(body)

    row = store.make_row("referrals", {
        "patient_id": body["patient_id"],
        "origin": body["origin"],
        "qualifying_condition_code": body["qualifying_condition_code"],
        "acuity": body["acuity"],
        "referring_physician_user_id": body["referring_physician_user_id"],
        "status": "SUBMITTED",
        "first_failed_gauntlet_rung": None,
    })
    return envelope.ObjResult(row, serializers.referral, 201)


@endpoint(bp, "/referrals/<referral_id>", ["GET"],
          ["ProgramAdmin", "AdmittingPhysician", "FieldNurse"])
def get_referral(caller, referral_id):
    row = ladder.path_row("referrals", referral_id)
    return envelope.ObjResult(row, serializers.referral, 200)


@endpoint(bp, "/referrals/<referral_id>/mark-eligible", ["POST"], ["AdmittingPhysician"])
def mark_eligible(caller, referral_id):
    # rung 3
    referral = ladder.path_row("referrals", referral_id)
    # rung 7
    ladder.require_state(referral["status"] == "SCREENING")
    assessment = latest_assessment(referral_id)
    ladder.require_state(assessment is not None)
    patient = DB.patients.get(referral["patient_id"])

    # rung 9: seven ordered gauntlet rules, stopping at the first failure.
    failure = None
    if referral["origin"] not in calc.ELIGIBLE_REFERRAL_ORIGINS:
        failure = errors.ERR_REFERRAL_ORIGIN_INELIGIBLE
    elif referral["qualifying_condition_code"] not in calc.QUALIFYING_CONDITION_CODES:
        failure = errors.ERR_CONDITION_NOT_QUALIFYING
    elif calc.to_decimal(patient["home_distance_km"]) > calc.SERVICE_RADIUS_KM:
        failure = errors.ERR_OUTSIDE_SERVICE_RADIUS
    elif assessment["home_safety_outcome"] != "PASS":
        failure = errors.ERR_HOME_SAFETY_FAILED
    elif assessment["broadband_check"] != "PASS":
        failure = errors.ERR_CONNECTIVITY_INSUFFICIENT
    elif referral["acuity"] == "HIGH" and not (
            patient["caregiver_present"] and assessment["caregiver_present_confirmed"]):
        failure = errors.ERR_CAREGIVER_REQUIRED
    elif not assessment["consent_signed"]:
        failure = errors.ERR_CONSENT_MISSING

    if failure is not None:
        # The referral stays in SCREENING; the winning error id is recorded so
        # the rejection remains observable. That bookkeeping write is a
        # mutation like any other (PRD 3.1).
        referral["first_failed_gauntlet_rung"] = failure
        store.touch(referral)
        store.flush()
        fail(failure)

    referral["status"] = "ELIGIBLE"
    referral["first_failed_gauntlet_rung"] = None
    store.touch(referral)
    return envelope.ObjResult(referral, serializers.referral, 200)


@endpoint(bp, "/eligibility-assessments", ["POST"], ["AdmittingPhysician", "FieldNurse"])
def create_assessment(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, [
        "referral_id", "in_person_eval_at", "home_safety_outcome", "broadband_check",
        "caregiver_present_confirmed", "consent_signed", "assessor_user_id",
    ])
    # rung 4b
    ladder.check_enum(body, "home_safety_outcome", SAFETY_OUTCOMES)
    ladder.check_enum(body, "broadband_check", BROADBAND_OUTCOMES)
    # rung 4c
    ladder.check_datetime(body, "in_person_eval_at")
    ladder.check_boolean(body, "caregiver_present_confirmed")
    ladder.check_boolean(body, "consent_signed")
    ladder.check_string(body, "assessor_user_id")
    # rung 5
    referral = ladder.body_referral(body)

    row = store.make_row("assessments", {
        "referral_id": body["referral_id"],
        "in_person_eval_at": body["in_person_eval_at"],
        "home_safety_outcome": body["home_safety_outcome"],
        "broadband_check": body["broadband_check"],
        "caregiver_present_confirmed": body["caregiver_present_confirmed"],
        "consent_signed": body["consent_signed"],
        "assessor_user_id": body["assessor_user_id"],
    })
    # The FIRST assessment drives the referral SUBMITTED -> SCREENING.
    if referral["status"] == "SUBMITTED":
        referral["status"] = "SCREENING"
        store.touch(referral)
    return envelope.ObjResult(row, serializers.assessment, 201)


@endpoint(bp, "/referrals/<referral_id>/eligibility-assessments", ["GET"],
          ["ProgramAdmin", "AdmittingPhysician", "FieldNurse"])
def list_assessments(caller, referral_id):
    # rung 3
    ladder.path_row("referrals", referral_id)
    # rung 4c
    limit, offset = ladder.pagination_params()
    return envelope.ListResult(
        referral_assessments(referral_id), serializers.assessment, limit, offset
    )
