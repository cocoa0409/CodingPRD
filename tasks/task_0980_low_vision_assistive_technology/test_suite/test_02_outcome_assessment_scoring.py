"""Outcome assessments: dual-composite scoring (provisional vs clinician final)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client, create_outcome_assessment_payload,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["vision_specialist_headers"]


def test_outcome_provisional_uses_self_report_weights(api):
    """PRD §3.10: "At creation the **provisional** composite is computed and
    stored in `provisional_composite`: one half of `task_score` plus one half of
    `satisfaction_score`, rounded half-up to an integer."

    Design: Difficulty/dual_variant_calc/dvc_outcome_provisional_vs_final
    """
    c = create_client(full_name="Bob Vance", date_of_birth="1970-01-15", copay_tier="STANDARD")
    oa = get_success_data(api.create_outcome_assessment(create_outcome_assessment_payload(
        c["id"], kind="FOLLOW_UP", task_score=80, satisfaction_score=70), SPECIALIST))
    assert oa["provisional_composite"] == 75, (
        f"round_half_up(0.5*80 + 0.5*70) = 75, got {oa['provisional_composite']}")
    assert oa["status"] == "DRAFT"


def test_outcome_final_uses_clinician_weights_and_diverges(api):
    """PRD §3.10: "On finalize the clinician variant computes `final_composite`
    as three tenths of `acuity_delta` plus four tenths of `task_score` plus three
    tenths of `satisfaction_score`, rounded half-up to an integer, and stores it."
    PRD §3.10: "Because the weightings differ, identical inputs generally yield a
    different final composite than the provisional one".

    Design: Difficulty/dual_variant_calc/dvc_outcome_provisional_vs_final
    """
    c = create_client(full_name="Bob Vance", date_of_birth="1970-01-15", copay_tier="STANDARD")
    oa = get_success_data(api.create_outcome_assessment(create_outcome_assessment_payload(
        c["id"], kind="FOLLOW_UP", task_score=80, satisfaction_score=70), SPECIALIST))
    fin = get_success_data(api.finalize_outcome_assessment(oa["id"], {"acuity_delta": 50}, SPECIALIST))
    assert fin["final_composite"] == 68, (
        f"round_half_up(0.3*50 + 0.4*80 + 0.3*70) = 68, got {fin['final_composite']}")
    assert fin["final_composite"] != fin["provisional_composite"]
    assert fin["status"] == "SCORED"


def test_outcome_finalize_without_acuity_delta_rejected(api):
    """PRD §3.10: "requires `acuity_delta` to be non-null, whether supplied at
    creation or at finalize; otherwise the call is rejected with
    `ERR_ASSESSMENT_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/val_assessment_incomplete_outcome_finalize
    """
    c = create_client(full_name="OA Incomplete")
    oa = get_success_data(api.create_outcome_assessment(create_outcome_assessment_payload(
        c["id"], kind="BASELINE", task_score=50, satisfaction_score=50), SPECIALIST))
    resp = api.finalize_outcome_assessment(oa["id"], {}, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INCOMPLETE)
