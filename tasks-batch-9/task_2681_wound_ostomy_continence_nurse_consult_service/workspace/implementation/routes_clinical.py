"""SkinAssessment and PressureInjuryCase (11 endpoints).

This module owns the deep transitive cascade: filing an assessment supersedes
the prior one for the same (patient_id, anatomic_location) and reclassifies its
case, while validating one runs hops 1 -> 1b -> 2 -> 3 -> 4 -> 5.
"""

import calc
import services
from core import (
    POA_WINDOW_HOURS,
    READ_ROLES,
    ROLE_DIRECTOR,
    ROLE_WOC_NURSE,
    F,
    add_hours,
    apply_filters,
    authorize,
    bad_request,
    bump,
    check_patient_version,
    chrono,
    fail,
    filters,
    insert,
    must,
    new_row,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    parse_input,
    public,
    public_list,
    rows_of,
    store,
)
from flask import Blueprint

bp = Blueprint("clinical", __name__)

ANATOMIC_LOCATIONS = ("SACRUM", "HEEL_LEFT", "HEEL_RIGHT", "ISCHIUM",
                      "TROCHANTER", "OTHER")
OBSERVED_STAGES = ("MUCOSAL", "STAGE_1", "STAGE_2", "STAGE_3", "STAGE_4",
                   "DTI", "UNSTAGEABLE")
VALIDATION_STATUSES = ("PENDING_VALIDATION", "VALIDATED", "DISPUTED", "SUPERSEDED")
CASE_STATUSES = ("OPEN", "CLASSIFIED_POA", "CLASSIFIED_HAPI", "RCA_REQUIRED",
                 "RCA_IN_PROGRESS", "RCA_COMPLETE", "CLOSED", "RECLASSIFIED")
CASE_CLASSIFICATIONS = ("UNDETERMINED", "POA", "HAPI")
ROOT_CAUSE_CATEGORIES = ("REPOSITIONING", "SUPPORT_SURFACE", "NUTRITION",
                         "DEVICE", "MOISTURE", "DOCUMENTATION")


# ---------------------------------------------------------------------------
# SkinAssessment
# ---------------------------------------------------------------------------
@bp.post("/skin-assessments")
def create_assessment():
    user_id, _role = authorize(ROLE_WOC_NURSE)
    body = parse_input([
        F("consult_request_id", "id", required=True),
        F("patient_id", "id", required=True),
        F("anatomic_location", "enum", required=True, enum=ANATOMIC_LOCATIONS),
        F("observed_stage", "enum", required=True, enum=OBSERVED_STAGES),
        F("measured_area_cm2", "number", required=True, minimum=0, maximum=500),
        F("observed_at", "datetime", required=True),
        F("expected_patient_version", "int", required=True, minimum=0),
        F("present_on_admission_claimed", "bool"),
        F("staged_by_nurse_id", "id"),
    ])
    consult = must("consult_requests", body["consult_request_id"])
    patient = must("patients", body["patient_id"])
    if body["patient_id"] != consult.get("patient_id"):
        fail("ERR_ENTITY_LINK_MISMATCH",
             "patient_id must equal the consult's patient_id.")
    if consult.get("status") not in ("ASSIGNED", "ASSESSED"):
        fail("ERR_CONSULT_INVALID_STATE")
    if patient.get("status") != "ADMITTED":
        fail("ERR_PATIENT_DISCHARGED")
    check_patient_version(patient, body["expected_patient_version"])
    if body["observed_at"] < patient.get("admitted_at"):
        bad_request("observed_at must be at or after the patient's admitted_at.")
    if body["observed_at"] > now():
        bad_request("observed_at must be at or before the current logical clock.")

    assessment = new_row(
        "assess",
        consult_request_id=body["consult_request_id"],
        patient_id=body["patient_id"],
        # staged_by_nurse_id is a system field: any client-supplied value is
        # ignored in favour of the authenticated caller.
        staged_by_nurse_id=user_id,
        anatomic_location=body["anatomic_location"],
        observed_stage=body["observed_stage"],
        measured_area_cm2=body["measured_area_cm2"],
        observed_at=body["observed_at"],
        present_on_admission_claimed=bool(
            body.get("present_on_admission_claimed", False)),
        poa_determination=None,
        validation_status="PENDING_VALIDATION",
        confirmed_stage=None,
        validated_by_user_id=None,
        dispute_reason=None,
        restage_count=0,
    )
    insert("skin_assessments", assessment)

    predecessor_case_id = services.supersede_prior_assessments(assessment, patient)
    services.create_case(assessment, patient, predecessor_case_id)

    # ASSIGNED -> ASSESSED, or the ASSESSED self-transition on re-assessment.
    consult["status"] = "ASSESSED"
    services.apply_acuity(consult, patient, assessment["observed_stage"],
                          calc.VARIANT_ASSESSED, assessment["measured_area_cm2"])
    bump(consult)
    bump(patient)
    return ok(public(assessment), 201)


@bp.get("/skin-assessments")
def list_assessments():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({
        "consult_request_id": None,
        "patient_id": None,
        "staged_by_nurse_id": None,
        "validation_status": VALIDATION_STATUSES,
    })
    rows = chrono(apply_filters(rows_of("skin_assessments"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/skin-assessments/<assessment_id>")
def get_assessment(assessment_id):
    authorize(*READ_ROLES)
    return ok(public(must("skin_assessments", assessment_id)))


@bp.post("/skin-assessments/<assessment_id>/validate")
def validate_assessment(assessment_id):
    user_id, role = authorize(ROLE_WOC_NURSE, ROLE_DIRECTOR)
    body = parse_input([
        F("confirmed_stage", "enum", required=True, enum=OBSERVED_STAGES),
        F("present_on_admission_confirmed", "bool", required=True),
    ])
    assessment = must("skin_assessments", assessment_id)
    if assessment.get("validation_status") != "PENDING_VALIDATION":
        fail("ERR_ASSESSMENT_INVALID_STATE")
    # Rung 30 — the nurse who staged an assessment may not validate it.
    if role == ROLE_WOC_NURSE and user_id == assessment.get("staged_by_nurse_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The staging nurse may not validate their own assessment.")
    patient = store("patients").get(assessment["patient_id"])
    if body["present_on_admission_confirmed"] is True:
        window_end = add_hours(patient.get("admitted_at"), POA_WINDOW_HOURS)
        if window_end is not None and assessment.get("observed_at") > window_end:
            fail("ERR_POA_WINDOW_CLOSED")
    consult = store("consult_requests").get(assessment.get("consult_request_id"))
    services.validate_cascade(assessment, patient, consult,
                              body["confirmed_stage"],
                              body["present_on_admission_confirmed"],
                              user_id)
    return ok(public(assessment))


@bp.post("/skin-assessments/<assessment_id>/dispute")
def dispute_assessment(assessment_id):
    authorize(ROLE_DIRECTOR)
    body = parse_input([
        F("dispute_reason", "string", required=True, min_len=1, max_len=2000),
    ])
    assessment = must("skin_assessments", assessment_id)
    if assessment.get("validation_status") != "PENDING_VALIDATION":
        fail("ERR_ASSESSMENT_INVALID_STATE")
    assessment["validation_status"] = "DISPUTED"
    assessment["dispute_reason"] = body["dispute_reason"]
    # poa_determination and confirmed_stage deliberately stay null.
    bump(assessment)
    consult = store("consult_requests").get(assessment.get("consult_request_id"))
    if consult is not None:
        consult["protocol_hold"] = True
        bump(consult)
    patient = store("patients").get(assessment.get("patient_id"))
    if patient is not None:
        unit = store("units").get(patient.get("unit_id"))
        if unit is not None:
            unit["disputed_staging_count"] = int(unit.get("disputed_staging_count") or 0) + 1
            bump(unit)
    return ok(public(assessment))


@bp.post("/skin-assessments/<assessment_id>/restage")
def restage_assessment(assessment_id):
    user_id, _role = authorize(ROLE_WOC_NURSE)
    body = parse_input([
        F("observed_stage", "enum", required=True, enum=OBSERVED_STAGES),
        F("measured_area_cm2", "number", required=True, minimum=0, maximum=500),
    ])
    assessment = must("skin_assessments", assessment_id)
    if assessment.get("validation_status") != "DISPUTED":
        fail("ERR_ASSESSMENT_INVALID_STATE")
    if user_id != assessment.get("staged_by_nurse_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "Only the original staging nurse may re-stage this assessment.")
    assessment["observed_stage"] = body["observed_stage"]
    assessment["measured_area_cm2"] = body["measured_area_cm2"]
    assessment["restage_count"] = int(assessment.get("restage_count") or 0) + 1
    assessment["dispute_reason"] = None
    assessment["validation_status"] = "PENDING_VALIDATION"
    bump(assessment)
    consult = store("consult_requests").get(assessment.get("consult_request_id"))
    if consult is not None:
        consult["protocol_hold"] = False
        bump(consult)
    return ok(public(assessment))


# ---------------------------------------------------------------------------
# PressureInjuryCase
# ---------------------------------------------------------------------------
@bp.get("/pressure-injury-cases")
def list_cases():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({
        "patient_id": None,
        "unit_id": None,
        "skin_assessment_id": None,
        "predecessor_case_id": None,
        "rca_lead_nurse_id": None,
        "status": CASE_STATUSES,
        "classification": CASE_CLASSIFICATIONS,
    })
    rows = chrono(apply_filters(rows_of("pressure_injury_cases"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/pressure-injury-cases/<case_id>")
def get_case(case_id):
    authorize(*READ_ROLES)
    return ok(public(must("pressure_injury_cases", case_id)))


@bp.post("/pressure-injury-cases/<case_id>/rca-start")
def rca_start(case_id):
    authorize(ROLE_WOC_NURSE, ROLE_DIRECTOR)
    body = parse_input([F("rca_lead_nurse_id", "id", required=True)])
    case = must("pressure_injury_cases", case_id)
    lead = must("woc_nurses", body["rca_lead_nurse_id"])
    if case.get("status") != "RCA_REQUIRED":
        fail("ERR_CASE_INVALID_STATE")
    origin = store("skin_assessments").get(case.get("skin_assessment_id"))
    if origin is not None and lead["id"] == origin.get("staged_by_nurse_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The staging nurse may not lead the RCA for their own assessment.")
    if lead.get("certification_status") != "CERTIFIED":
        fail("ERR_NURSE_NOT_CERTIFIED")
    case["rca_lead_nurse_id"] = lead["id"]
    case["status"] = "RCA_IN_PROGRESS"
    bump(case)
    return ok(public(case))


@bp.post("/pressure-injury-cases/<case_id>/rca-complete")
def rca_complete(case_id):
    user_id, _role = authorize(ROLE_WOC_NURSE)
    body = parse_input([
        F("root_cause_category", "enum", required=True, enum=ROOT_CAUSE_CATEGORIES),
        F("contributing_factors", "str_list", required=True, min_items=1,
          max_len=120),
    ])
    if len(body["contributing_factors"]) > 6:
        bad_request("contributing_factors accepts at most 6 entries.")
    case = must("pressure_injury_cases", case_id)
    if case.get("status") != "RCA_IN_PROGRESS":
        fail("ERR_CASE_INVALID_STATE")
    if user_id != case.get("rca_lead_nurse_id"):
        fail("ERR_UNAUTHORIZED",
             "Only the assigned RCA lead may complete this analysis.")
    case["root_cause_category"] = body["root_cause_category"]
    case["contributing_factors"] = body["contributing_factors"]
    case["status"] = "RCA_COMPLETE"
    bump(case)
    return ok(public(case))


@bp.post("/pressure-injury-cases/<case_id>/close")
def close_case(case_id):
    authorize(ROLE_DIRECTOR)
    parse_input([F("closure_note", "string", required=True, min_len=1, max_len=2000)])
    case = must("pressure_injury_cases", case_id)
    status = case.get("status")
    if status not in ("RCA_COMPLETE", "CLASSIFIED_POA"):
        fail("ERR_CASE_INVALID_STATE")
    if status == "RCA_COMPLETE":
        # Reverses validate-cascade hops 4 and 5 exactly.
        services.close_hapi_case(case)
    else:
        # A POA case never incremented open_hapi_rca_count.
        case["closed_at"] = now()
        case["status"] = "CLOSED"
        bump(case)
    return ok(public(case))
