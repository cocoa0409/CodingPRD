"""Routes: allergy assessments, culture reports, susceptibility results,
culture-driven recommendation selector."""

from flask import Blueprint

import db
from errors import (
    err_allergy_high_risk,
    err_allergy_not_schedulable,
    err_allergy_not_testing,
    err_allergy_terminal,
    err_cross_facility,
    err_future_specimen,
    err_insufficient_permissions,
    err_invalid_request,
    err_not_found,
    err_patient_discharged,
    err_rechallenge_too_early,
    err_severe_allergy_blocked,
)
from middleware import ALL_ROLES, auth_context, require_role
from response import success_object
from services import core
from services.core import (
    ALLERGY_BLOCKING_STATUSES,
    ALLERGY_TERMINAL_STATUSES,
    CLASS_BREADTH_RANK,
    SPECIMEN_EXCLUSIONS,
    UNKNOWN_CLASS_RANK,
)
from services.listing import list_response
from services.serializers import serialize, serialize_many
from util import (
    body_json,
    new_id,
    parse_iso,
    require_enum,
    require_fields,
    require_int,
    require_number,
    require_string,
)

bp = Blueprint("allergy_culture", __name__)

SEVERITIES = {"MILD", "MODERATE", "SEVERE"}
INTERPRETATIONS = {"S", "I", "R"}
TEST_RESULTS = {"NEGATIVE", "POSITIVE", "INDETERMINATE"}


def get_assessment_or_404(aid):
    a = db.allergy_assessments.get(aid)
    if a is None:
        raise err_not_found("AllergyAssessment not found")
    return a


def get_culture_or_404(cid):
    c = db.culture_reports.get(cid)
    if c is None:
        raise err_not_found("CultureReport not found")
    return c


def _patient_of_assessment(a):
    return db.patient_cases.get(a["patient_case_id"])


def _patient_of_culture(c):
    return db.patient_cases.get(c["patient_case_id"])


def _require_patient_admitted(patient):
    if patient is not None and patient["status"] != "ADMITTED":
        raise err_patient_discharged()


# --- Allergy assessments ---------------------------------------------------------


@bp.route("/stewardship/allergy-assessments", methods=["POST"])
def create_assessment():
    _, role = auth_context()
    require_role(role, {"IDPharmacist", "AttendingPhysician"})
    payload = body_json()
    require_fields(
        payload, ["patient_case_id", "reported_reaction", "reaction_severity", "years_since_reaction"]
    )
    patient = db.patient_cases.get(payload["patient_case_id"])
    if patient is None:
        raise err_not_found("PatientCase not found")
    _require_patient_admitted(patient)
    assessment = {
        "id": new_id(),
        "patient_case_id": patient["id"],
        "reported_reaction": require_string(payload, "reported_reaction"),
        "reaction_severity": require_enum(payload, "reaction_severity", SEVERITIES),
        "years_since_reaction": require_int(payload, "years_since_reaction", minimum=0),
        "status": "SUSPECTED",
        "test_result": "NULL",
    }
    core.stamp_new(assessment)
    score, eligible = core.compute_allergy_risk(assessment, patient)
    assessment["risk_score"] = score
    assessment["delabel_eligible"] = eligible
    db.allergy_assessments[assessment["id"]] = assessment
    return success_object(serialize(assessment), status=201)


@bp.route("/stewardship/allergy-assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_assessment_or_404(aid)))


@bp.route("/stewardship/allergy-assessments", methods=["GET"])
def list_assessments():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(db.allergy_assessments.values(), ["patient_case_id", "status"])


@bp.route("/stewardship/allergy-assessments/<aid>/schedule-test", methods=["POST"])
def schedule_test(aid):
    _, role = auth_context()
    require_role(role, {"IDPharmacist", "StewardshipDirector"})
    assessment = get_assessment_or_404(aid)
    patient = _patient_of_assessment(assessment)
    _require_patient_admitted(patient)
    if assessment["status"] in ALLERGY_TERMINAL_STATUSES:
        raise err_allergy_terminal()
    if assessment["status"] not in ("SUSPECTED", "CONFIRMED"):
        raise err_allergy_not_schedulable()
    # Origin-dependent actor: SUSPECTED -> IDPharmacist; CONFIRMED -> StewardshipDirector.
    if assessment["status"] == "SUSPECTED" and role != "IDPharmacist":
        raise err_insufficient_permissions("Scheduling from SUSPECTED is an IDPharmacist action")
    if assessment["status"] == "CONFIRMED" and role != "StewardshipDirector":
        raise err_insufficient_permissions("Rechallenge from CONFIRMED is a StewardshipDirector action")
    if assessment["reaction_severity"] == "SEVERE":
        raise err_severe_allergy_blocked()
    if assessment["status"] == "SUSPECTED":
        if not assessment["delabel_eligible"]:
            raise err_allergy_high_risk()
    if assessment["status"] == "CONFIRMED":
        if assessment["years_since_reaction"] < 5:
            raise err_rechallenge_too_early()
    hospital = db.hospitals.get(patient["hospital_id"])
    # verified_baseline recompute at schedule time (PRD 3.6).
    core.recompute_assessment_verified_baseline(assessment, patient, hospital)
    assessment["status"] = "TESTING_SCHEDULED"
    core.touch(assessment)
    return success_object(serialize(assessment))


@bp.route("/stewardship/allergy-assessments/<aid>/record-result", methods=["POST"])
def record_result(aid):
    _, role = auth_context()
    require_role(role, {"IDPharmacist"})
    assessment = get_assessment_or_404(aid)
    patient = _patient_of_assessment(assessment)
    _require_patient_admitted(patient)
    if assessment["status"] in ALLERGY_TERMINAL_STATUSES:
        raise err_allergy_terminal()
    if assessment["status"] != "TESTING_SCHEDULED":
        raise err_allergy_not_testing()
    payload = body_json()
    require_fields(payload, ["test_result"])
    result = payload["test_result"]
    if result not in TEST_RESULTS:
        raise err_invalid_request("test_result must be NEGATIVE, POSITIVE, or INDETERMINATE")
    assessment["test_result"] = result
    if result == "NEGATIVE":
        assessment["status"] = "DELABELED"
    elif result == "POSITIVE":
        assessment["status"] = "CONFIRMED"
    else:
        assessment["status"] = "TESTING_SCHEDULED"
    core.touch(assessment)
    return success_object(serialize(assessment))


@bp.route("/stewardship/allergy-assessments/<aid>/withdraw", methods=["POST"])
def withdraw_assessment(aid):
    _, role = auth_context()
    require_role(role, {"IDPharmacist", "StewardshipDirector"})
    assessment = get_assessment_or_404(aid)
    patient = _patient_of_assessment(assessment)
    _require_patient_admitted(patient)
    if assessment["status"] in ALLERGY_TERMINAL_STATUSES:
        raise err_allergy_terminal()
    assessment["status"] = "WITHDRAWN"
    core.touch(assessment)
    return success_object(serialize(assessment))


# --- Culture reports ---------------------------------------------------------------


@bp.route("/stewardship/culture-reports", methods=["POST"])
def create_culture():
    _, role = auth_context()
    require_role(role, {"Microbiologist"})
    payload = body_json()
    require_fields(payload, ["patient_case_id", "specimen_source", "collected_at", "organism"])
    patient = db.patient_cases.get(payload["patient_case_id"])
    if patient is None:
        raise err_not_found("PatientCase not found")
    _require_patient_admitted(patient)
    hospital = db.hospitals.get(patient["hospital_id"])
    collected = parse_iso(payload["collected_at"], "collected_at")
    if collected > core.hospital_clock(hospital):
        raise err_future_specimen()
    culture = {
        "id": new_id(),
        "patient_case_id": patient["id"],
        "specimen_source": require_string(payload, "specimen_source"),
        "collected_at": payload["collected_at"],
        "organism": require_string(payload, "organism"),
        "resulted_at": None,
        "status": "PRELIMINARY",
        "_hospital_id": patient["hospital_id"],
    }
    core.stamp_new(culture)
    culture["is_first_isolate"] = _compute_is_first_isolate(culture, collected)
    db.culture_reports[culture["id"]] = culture
    return success_object(serialize(culture), status=201)


def _compute_is_first_isolate(culture, collected):
    """True when no prior same-patient (organism, specimen_source) culture has
    collected_at within the rolling 365-day window ending at collected_at."""
    from datetime import timedelta

    window_start = collected - timedelta(days=365)
    for other in db.culture_reports.values():
        if other["id"] == culture["id"]:
            continue
        if other["patient_case_id"] != culture["patient_case_id"]:
            continue
        if other["organism"] != culture["organism"]:
            continue
        if other["specimen_source"] != culture["specimen_source"]:
            continue
        other_collected = parse_iso(other["collected_at"])
        if window_start <= other_collected <= collected:
            return False
    return True


@bp.route("/stewardship/culture-reports/<cid>", methods=["GET"])
def get_culture(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_culture_or_404(cid)))


@bp.route("/stewardship/culture-reports", methods=["GET"])
def list_cultures():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(db.culture_reports.values(), ["patient_case_id", "status", "organism"])


@bp.route("/stewardship/culture-reports/<cid>/finalize", methods=["POST"])
def finalize_culture(cid):
    _, role = auth_context()
    require_role(role, {"Microbiologist"})
    culture = get_culture_or_404(cid)
    patient = _patient_of_culture(culture)
    _require_patient_admitted(patient)
    hospital = db.hospitals.get(culture["_hospital_id"])
    culture["status"] = "FINAL"
    culture["resulted_at"] = core.clock_iso(hospital)
    core.touch(culture)
    return success_object(serialize(culture))


@bp.route("/stewardship/culture-reports/<cid>/susceptibility-results", methods=["POST"])
def add_susceptibility(cid):
    _, role = auth_context()
    require_role(role, {"Microbiologist"})
    culture = get_culture_or_404(cid)
    patient = _patient_of_culture(culture)
    _require_patient_admitted(patient)
    payload = body_json()
    require_fields(payload, ["antimicrobial_id", "interpretation", "mic_value"])
    drug = db.antimicrobials.get(payload["antimicrobial_id"])
    if drug is None:
        raise err_not_found("Antimicrobial not found")
    if drug["hospital_id"] != culture["_hospital_id"]:
        raise err_cross_facility()
    row = {
        "id": new_id(),
        "culture_report_id": culture["id"],
        "antimicrobial_id": drug["id"],
        "interpretation": require_enum(payload, "interpretation", INTERPRETATIONS),
        "mic_value": require_number(payload, "mic_value", exclusive_minimum=0),
    }
    core.stamp_new(row)
    db.susceptibility_results[row["id"]] = row
    return success_object(serialize(row), status=201)


@bp.route("/stewardship/culture-reports/<cid>/susceptibility-results", methods=["GET"])
def list_susceptibility_of_culture(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_culture_or_404(cid)
    rows = [r for r in db.susceptibility_results.values() if r["culture_report_id"] == cid]
    return list_response(rows, [])


@bp.route("/stewardship/susceptibility-results", methods=["GET"])
def list_susceptibility():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(
        db.susceptibility_results.values(),
        ["culture_report_id", "antimicrobial_id", "interpretation"],
    )


@bp.route("/stewardship/susceptibility-results/<sid>", methods=["GET"])
def get_susceptibility(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    row = db.susceptibility_results.get(sid)
    if row is None:
        raise err_not_found("SusceptibilityResult not found")
    return success_object(serialize(row))


# --- Culture-driven recommendation selector -----------------------------------------


@bp.route("/stewardship/culture-reports/<cid>/recommend", methods=["POST"])
def recommend(cid):
    _, role = auth_context()
    require_role(role, {"IDPharmacist", "AttendingPhysician", "StewardshipDirector"})
    culture = get_culture_or_404(cid)
    patient = _patient_of_culture(culture)
    if culture["status"] not in ("FINAL", "AMENDED"):
        # PRELIMINARY reports cannot drive recommendations; treated as an
        # empty-pool outcome (200 with null recommendation, not an error).
        return success_object(
            {
                "recommended_antimicrobial_id": None,
                "pool_size": 0,
                "reason": "culture_not_final",
            }
        )
    blocked_by_allergy = False
    if patient is not None:
        for a in db.allergy_assessments.values():
            if a["patient_case_id"] == patient["id"] and a["status"] in ALLERGY_BLOCKING_STATUSES:
                blocked_by_allergy = True
                break
    candidates = []
    for row in db.susceptibility_results.values():
        if row["culture_report_id"] != culture["id"]:
            continue
        if row["interpretation"] != "S":
            continue
        drug = db.antimicrobials.get(row["antimicrobial_id"])
        if drug is None:
            continue
        if drug["formulary_status"] != "ACTIVE":
            continue
        excluded_classes = SPECIMEN_EXCLUSIONS.get(culture["specimen_source"], set())
        if drug["drug_class"] in excluded_classes:
            continue
        if blocked_by_allergy and drug["is_penicillin_class"]:
            continue
        candidates.append((row, drug))

    def rank_key(pair):
        row, drug = pair
        return (
            CLASS_BREADTH_RANK.get(drug["drug_class"], UNKNOWN_CLASS_RANK),
            0 if drug["has_po_form"] else 1,
            float(row["mic_value"]),
            drug["created_at"],
        )

    candidates.sort(key=rank_key)
    if not candidates:
        return success_object(
            {
                "recommended_antimicrobial_id": None,
                "pool_size": 0,
                "reason": "empty_pool",
            }
        )
    chosen = candidates[0][1]
    return success_object(
        {
            "recommended_antimicrobial_id": chosen["id"],
            "pool_size": len(candidates),
            "reason": "selected",
        }
    )
