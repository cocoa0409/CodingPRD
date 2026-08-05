"""Fall-risk scoring: screening vs clinical dual variant, the tiered composite,
and the HIGH-tier threshold boundary."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_clinician_headers,
    register_patient, register_referral, register_clinician,
    reset_clock,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


def _draft_assessment(api, **measures):
    reset_clock(api)
    patient = register_patient(api)
    referral = register_referral(api, patient["id"])
    clinician = register_clinician(api)
    ch = make_clinician_headers(clinician["id"])
    payload = {
        "patient_id": patient["id"], "referral_id": referral["id"],
        "clinician_id": clinician["id"],
    }
    payload.update(measures)
    assessment = get_success_data(api.create_assessment(payload, ch))
    return assessment, ch


# --- A1: dual_variant_calc / fall_risk_screening_vs_clinical_on_assessment ----

def test_screening_score_at_create_ignores_measured_fields(api):
    """PRD §3.2: "The moment an assessment is created, the system computes a
    provisional screening_score from self-report inputs alone. It is ten points
    for each self-reported fall - that is, self_report_fall_count multiplied by
    ten - plus a flat fifteen points when the patient is on four or more
    medications". PRD §3.2: "fall_risk_tier stays null while the assessment is in
    DRAFT."

    Design: Difficulty/dual_variant_calc/fall_risk_screening_vs_clinical_on_assessment
    """
    assessment, _ = _draft_assessment(
        api, gait_speed_m_s=0.55, tug_seconds=14.0, berg_balance_score=18,
        medication_count=5, self_report_fall_count=2,
    )
    assert assessment["screening_score"] == 35
    assert assessment["status"] == "DRAFT"
    assert assessment["fall_risk_tier"] is None


def test_clinical_score_at_finalize_differs_from_screening(api):
    """PRD §3.2: "The resulting clinical_score ranges from 0 to 110. From it the
    system derives fall_risk_tier: HIGH when the score is at least 50, otherwise
    MODERATE when the score is at least 25, otherwise LOW."

    Design: Difficulty/dual_variant_calc/fall_risk_screening_vs_clinical_on_assessment
    """
    assessment, ch = _draft_assessment(
        api, gait_speed_m_s=0.55, tug_seconds=14.0, berg_balance_score=18,
        medication_count=5, self_report_fall_count=2,
    )
    finalized = validate_success(api.finalize_assessment(assessment["id"], ch), 200)
    assert finalized["clinical_score"] == 110
    assert finalized["fall_risk_tier"] == "HIGH"
    assert finalized["screening_score"] != finalized["clinical_score"]


# --- A3: combinatorial_formula / clinical_score_tiered_composite_mode_a --------

def test_clinical_score_mixed_tier_composite_is_40(api):
    """PRD §3.2: "Gait points: thirty when gait_speed_m_s is below 0.60; otherwise
    twenty when it is below 0.80; otherwise ten when it is below 1.00; otherwise
    zero." PRD §3.2: "History points: ten when self_report_fall_count is at least
    two; otherwise five when it is exactly one; otherwise zero."

    Design: Difficulty/combinatorial_formula/clinical_score_tiered_composite_mode_a
    """
    assessment, ch = _draft_assessment(
        api, gait_speed_m_s=0.90, tug_seconds=11.0, berg_balance_score=30,
        medication_count=2, self_report_fall_count=1,
    )
    finalized = validate_success(api.finalize_assessment(assessment["id"], ch), 200)
    assert finalized["clinical_score"] == 40


def test_clinical_score_40_yields_moderate_tier(api):
    """PRD §3.2: "From it the system derives fall_risk_tier: HIGH when the score is
    at least 50, otherwise MODERATE when the score is at least 25, otherwise LOW."

    Design: Difficulty/combinatorial_formula/clinical_score_tiered_composite_mode_a
    """
    assessment, ch = _draft_assessment(
        api, gait_speed_m_s=0.90, tug_seconds=11.0, berg_balance_score=30,
        medication_count=2, self_report_fall_count=1,
    )
    finalized = validate_success(api.finalize_assessment(assessment["id"], ch), 200)
    assert finalized["fall_risk_tier"] == "MODERATE"


# --- A12: boundary_precision_check / fall_risk_high_threshold_on_assessment_finalize

def test_clinical_score_exactly_50_is_high(api):
    """PRD §3.2: "From it the system derives fall_risk_tier: HIGH when the score is
    at least 50, otherwise MODERATE when the score is at least 25, otherwise LOW."

    Design: Difficulty/boundary_precision_check/fall_risk_high_threshold_on_assessment_finalize
    """
    # gait 0.70 -> 20, tug 13.5 -> 30, berg 50 -> 0, meds 0 -> 0, falls 0 -> 0 = 50
    assessment, ch = _draft_assessment(
        api, gait_speed_m_s=0.70, tug_seconds=13.5, berg_balance_score=50,
        medication_count=0, self_report_fall_count=0,
    )
    finalized = validate_success(api.finalize_assessment(assessment["id"], ch), 200)
    assert finalized["clinical_score"] == 50
    assert finalized["fall_risk_tier"] == "HIGH"


def test_clinical_score_below_threshold_is_moderate(api):
    """PRD §3.2: "From it the system derives fall_risk_tier: HIGH when the score is
    at least 50, otherwise MODERATE when the score is at least 25, otherwise LOW."

    Design: Difficulty/boundary_precision_check/fall_risk_high_threshold_on_assessment_finalize
    """
    # gait 0.70 -> 20, tug 12.0 -> 20, berg 50 -> 0, meds 0 -> 0, falls 1 -> 5 = 45 (< 50)
    assessment, ch = _draft_assessment(
        api, gait_speed_m_s=0.70, tug_seconds=12.0, berg_balance_score=50,
        medication_count=0, self_report_fall_count=1,
    )
    finalized = validate_success(api.finalize_assessment(assessment["id"], ch), 200)
    assert finalized["clinical_score"] == 45
    assert finalized["fall_risk_tier"] == "MODERATE"
