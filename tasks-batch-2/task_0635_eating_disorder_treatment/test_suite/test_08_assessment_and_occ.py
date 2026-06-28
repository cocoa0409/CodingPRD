"""Assessment composite scoring, finalize seeding, and the two optimistic-
concurrency checks (assessment finalize against patient.version, treatment-plan
revise against admission.version).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    CLINICIAN,
    INTAKE,
    fixtures as fx,
)


def test_assessment_composite_and_recommended_loc_at_boundary(api):
    """PRD §3.2: "The `recommended_level_of_care` reads off the clamped composite
    against three inclusive thresholds: `RESIDENTIAL` when the composite is at
    least 70".

    Design: Corner/entities/assessment_composite_score_and_recommended_loc_computed
    """
    # med=10,beh=10,psy=5,mot=10: 0.40*100+0.30*100+0.20*50-0.10*100 = 70.0.
    facility = fx.create_facility()
    patient = fx.create_patient(facility["id"], bmi=19.0, full_name="Pat R")
    resp = api.create_assessment(
        {"patient_id": patient["id"], "facility_id": facility["id"],
         "medical_severity": 10, "behavioral_severity": 10,
         "psychiatric_severity": 5, "motivation_level": 10},
        CLINICIAN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["composite_score"] == 70.0, (
        f"expected 70.0, got {data['composite_score']}"
    )
    assert data["recommended_level_of_care"] == "RESIDENTIAL", (
        f"expected RESIDENTIAL at the 70 boundary, got "
        f"{data['recommended_level_of_care']}"
    )


def test_occ_correct_patient_version_finalize_succeeds(api):
    """PRD §2.5: "The request must include `expected_patient_version`, carrying the
    `version` of the patient that the client last observed."
    PRD §3.3: "the patient's `active_assessment_id` is re-pointed to the
    assessment just finalized. ... and the patient's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_patient_version_finalize_succeeds
    """
    facility = fx.create_facility()
    patient = fx.create_patient(facility["id"])
    assert patient["version"] == 1
    assessment = validate_success(
        api.create_assessment(
            {"patient_id": patient["id"], "facility_id": facility["id"],
             "medical_severity": 5, "behavioral_severity": 5,
             "psychiatric_severity": 4, "motivation_level": 6},
            CLINICIAN,
        ),
        expected_status=201,
    )
    finalized = validate_success(
        api.finalize_assessment(
            assessment["id"], {"expected_patient_version": 1}, CLINICIAN
        )
    )
    assert finalized["status"] == "FINALIZED", (
        f"expected FINALIZED, got {finalized['status']}"
    )
    patient_after = validate_success(api.get_patient(patient["id"], INTAKE))
    assert patient_after["version"] == 2, (
        f"expected version 2, got {patient_after['version']}"
    )
    assert patient_after["active_assessment_id"] == assessment["id"], (
        "active_assessment_id must point at the finalized assessment"
    )


def test_occ_stale_patient_version_finalize_rejected(api):
    """PRD §2.5: "if another finalize has already superseded the governing
    assessment and advanced the patient's version since the client read it, the
    values differ and the finalize is rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_patient_version_finalize_rejected
    """
    facility = fx.create_facility()
    patient = fx.create_patient(facility["id"])  # version 1
    a1 = validate_success(
        api.create_assessment(
            {"patient_id": patient["id"], "facility_id": facility["id"],
             "medical_severity": 5, "behavioral_severity": 5,
             "psychiatric_severity": 4, "motivation_level": 6},
            CLINICIAN,
        ),
        expected_status=201,
    )
    # First finalize advances patient.version to 2.
    validate_success(
        api.finalize_assessment(a1["id"], {"expected_patient_version": 1}, CLINICIAN)
    )
    a2 = validate_success(
        api.create_assessment(
            {"patient_id": patient["id"], "facility_id": facility["id"],
             "medical_severity": 6, "behavioral_severity": 6,
             "psychiatric_severity": 5, "motivation_level": 5},
            CLINICIAN,
        ),
        expected_status=201,
    )
    # Second finalize carries the stale version (1).
    resp = api.finalize_assessment(a2["id"], {"expected_patient_version": 1}, CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    data = validate_success(api.get_assessment(a2["id"], CLINICIAN))
    assert data["status"] == "DRAFT", f"a2 must stay DRAFT, got {data['status']}"


def test_occ_treatment_plan_revise_stale_admission_rejected(api):
    """PRD §2.5: "The platform compares it to the admission's current `version`;
    if a clinical change — a step-down or a treatment-plan revision — has already
    advanced the admission since the client read it, the values differ and the
    revise is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_treatment_plan_revise_stale_admission_rejected
    """
    ctx = fx.setup_admitted_admission()
    tp = fx.create_active_treatment_plan(
        ctx["admission"]["id"], ctx["facility"]["id"], goals_total=3
    )
    admission = validate_success(api.get_admission(ctx["admission"]["id"], INTAKE))
    stale_version = admission["version"] - 1
    resp = api.revise_treatment_plan(
        tp["id"], {"expected_admission_version": stale_version}, CLINICIAN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    data = validate_success(api.get_treatment_plan(tp["id"], CLINICIAN))
    assert data["status"] == "ACTIVE", f"plan must stay ACTIVE, got {data['status']}"
