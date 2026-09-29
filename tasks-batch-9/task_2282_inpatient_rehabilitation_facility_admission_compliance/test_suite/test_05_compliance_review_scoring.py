"""Compliance review methods, threshold boundaries and assessment gating."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_admission_dimensions,
    assert_facility_cohort,
    complete_assessment,
    discharge,
    evaluate_week,
    grant_week_exception,
    open_and_compute_review,
    open_assessment,
    open_therapy_week,
    read_admission,
    read_assessment,
    read_facility,
    read_therapy_week,
    record_conference,
    set_clock,
    setup_admitted_cohort,
    setup_discharged_cohort,
    setup_facility_with_staff,
    setup_stay,
    sign_plan_of_care,
    validate_error,
)

PRESUMPTIVE_PATIENT = {"comorbidity_tier": "TIER_2"}
NON_PRESUMPTIVE_PATIENT = {
    "full_name": "Bo Whitaker",
    "impairment_group_code": "0950",
    "etiologic_diagnosis_code": "M17.11",
}


def test_presumptive_review_scores_from_the_patient_clinical_descriptors():
    """One of two stays carries a presumptive impairment group code.

    PRD §3.9: "Under `PRESUMPTIVE`, an admission qualifies when its patient's
    `impairment_group_code` is one of `0008`, `0110`, `0704`, or `1101`; or when
    its patient's `etiologic_diagnosis_code` is one of `I63.9` or `S72.001A`
    **and** that patient's `comorbidity_tier` is `TIER_1` or `TIER_2`."

    Design: Difficulty/dual_variant_calc/presumptive_vs_medical_review_compliance_variant_divergence
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"),
                                    compliance_threshold_pct=50.00)
    setup_discharged_cohort(
        env,
        [{"mrn": "MRN-A", "patient_overrides": PRESUMPTIVE_PATIENT},
         {"mrn": "MRN-B", "patient_overrides": NON_PRESUMPTIVE_PATIENT}],
        admitted_at="2026-08-04T12:00:00Z",
        discharged_at="2026-08-06T12:00:00Z",
    )

    presumptive = open_and_compute_review(env, method="PRESUMPTIVE")
    open_and_compute_review(env, method="MEDICAL_REVIEW")

    assert presumptive["total_cases"] == 2
    assert presumptive["qualifying_cases"] == 1
    assert float(presumptive["compliance_pct"]) == 50.00
    assert presumptive["outcome"] == "PASS"
    assert presumptive["status"] == "COMPUTED"


def test_medical_review_scores_the_same_cohort_from_documentation_verdicts():
    """Neither undocumented stay qualifies under medical review.

    PRD §3.9: "Under `MEDICAL_REVIEW`, an admission qualifies exactly when its
    `compliance_class` is `QUALIFYING` — that is, when all four documentation
    tests of §3.8 passed."

    Design: Difficulty/dual_variant_calc/presumptive_vs_medical_review_compliance_variant_divergence
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"),
                                    compliance_threshold_pct=50.00)
    stays = setup_discharged_cohort(
        env,
        [{"mrn": "MRN-A", "patient_overrides": PRESUMPTIVE_PATIENT},
         {"mrn": "MRN-B", "patient_overrides": NON_PRESUMPTIVE_PATIENT}],
        admitted_at="2026-08-04T12:00:00Z",
        discharged_at="2026-08-06T12:00:00Z",
    )

    open_and_compute_review(env, method="PRESUMPTIVE")
    medical = open_and_compute_review(env, method="MEDICAL_REVIEW")

    assert medical["total_cases"] == 2
    assert medical["qualifying_cases"] == 0
    assert float(medical["compliance_pct"]) == 0.00
    assert medical["outcome"] == "FAIL"
    for stay in stays:
        assert_admission_dimensions(read_admission(stay["admission"]["id"]),
                                    compliance_class="NON_QUALIFYING")


def test_provisional_percentage_exactly_at_the_threshold_leaves_posture_open():
    """A cohort of two with one qualifying stay sits exactly on 50.00 percent.

    PRD §2.8: "Because both percentage comparisons are strict, a provisional
    percentage exactly equal to the threshold leaves the posture `OPEN`."

    Design: Difficulty/boundary_precision_check/compliance_percentage_exactly_at_threshold_passes
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"),
                                    compliance_threshold_pct=50.00)
    stays = setup_admitted_cohort(
        env,
        [{"mrn": "MRN-A"},
         {"mrn": "MRN-B", "patient_overrides": {"full_name": "Bo Whitaker"}}],
    )
    admission_a = stays[0]["admission"]["id"]
    admission_b = stays[1]["admission"]["id"]
    sign_plan_of_care(env, admission_a, three_hour_rule_mode="DAILY_3HR",
                      disciplines=["PT"])
    week_a = open_therapy_week(env, admission_a, week_start_date="2026-08-04")
    evaluate_week(env, week_a["id"])
    grant_week_exception(
        env, week_a["id"],
        exception_reason="Acute medical instability documented by the attending "
                         "physician",
    )
    set_clock("2026-08-06T15:00:00Z")
    conference = record_conference(env, admission_a, week_a["id"],
                                   "2026-08-06T15:00:00Z")

    set_clock("2026-08-08T12:00:00Z")
    discharge(env, admission_a, "2026-08-08T12:00:00Z", advance_clock=False)
    discharge(env, admission_b, "2026-08-08T12:00:00Z", advance_clock=False)

    assert conference["status"] == "RECORDED"
    assert read_therapy_week(week_a["id"])["status"] == "EXCEPTION_GRANTED"
    qualifying = read_admission(admission_a)
    assert qualifying["therapy_weeks_satisfied"] is True
    assert qualifying["conference_compliant"] is True
    assert_admission_dimensions(qualifying, compliance_class="QUALIFYING")
    assert_admission_dimensions(read_admission(admission_b),
                                compliance_class="NON_QUALIFYING")
    assert_facility_cohort(read_facility(env["facility_id"]),
                           cohort_total_count=2, cohort_qualifying_count=1,
                           provisional_compliance_pct=50.00, posture="OPEN")


def test_review_percentage_exactly_at_the_threshold_passes():
    """The inclusive pass test lets 50.00 percent against a 50.00 threshold pass.

    PRD §3.9: "The `outcome` is `PASS` when `compliance_pct` is greater than or
    equal to the facility's `compliance_threshold_pct`, and `FAIL` otherwise —
    the pass test is inclusive, so a percentage exactly equal to the threshold
    passes."

    Design: Difficulty/boundary_precision_check/compliance_percentage_exactly_at_threshold_passes
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"),
                                    compliance_threshold_pct=50.00)
    stays = setup_admitted_cohort(
        env,
        [{"mrn": "MRN-A"},
         {"mrn": "MRN-B", "patient_overrides": {"full_name": "Bo Whitaker"}}],
    )
    admission_a = stays[0]["admission"]["id"]
    admission_b = stays[1]["admission"]["id"]
    sign_plan_of_care(env, admission_a, three_hour_rule_mode="DAILY_3HR",
                      disciplines=["PT"])
    week_a = open_therapy_week(env, admission_a, week_start_date="2026-08-04")
    evaluate_week(env, week_a["id"])
    grant_week_exception(
        env, week_a["id"],
        exception_reason="Acute medical instability documented by the attending "
                         "physician",
    )
    set_clock("2026-08-06T15:00:00Z")
    record_conference(env, admission_a, week_a["id"], "2026-08-06T15:00:00Z")
    set_clock("2026-08-08T12:00:00Z")
    discharge(env, admission_a, "2026-08-08T12:00:00Z", advance_clock=False)
    discharge(env, admission_b, "2026-08-08T12:00:00Z", advance_clock=False)

    review = open_and_compute_review(env, method="MEDICAL_REVIEW")

    assert review["total_cases"] == 2
    assert review["qualifying_cases"] == 1
    assert float(review["compliance_pct"]) == 50.00
    assert review["outcome"] == "PASS"


def test_transmission_is_refused_while_the_stay_is_not_discharged():
    """A completed instrument cannot be transmitted from an occupied bed.

    PRD §3.9: "In both branches the admission must be `DISCHARGED`
    (`ERR_ADMISSION_NOT_DISCHARGED`) and the transmitting coder must differ from
    `coder_clinician_id` (§2.9)."

    Design: Difficulty/cross_entity_state_dependency/assessment_transmit_blocked_until_admission_discharged
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "coder",
                                           "coder2"))
    stay = setup_stay(env, plan_overrides={"three_hour_rule_mode": "DAILY_3HR",
                                           "disciplines": ["PT"]})
    assessment = open_assessment(env, stay["admission"]["id"],
                                 assessment_type="ADMISSION", coder_key="coder")
    set_clock("2026-08-05T09:00:00Z")
    complete_assessment(env, assessment["id"], coder_key="coder")

    response = api_client.transmit_assessment(assessment["id"],
                                              env["coder2_headers"])

    validate_error(response, ApiErrorId.ERR_ADMISSION_NOT_DISCHARGED)
    blocked = read_assessment(assessment["id"])
    assert blocked["status"] == "COMPLETED"
    assert blocked["transmitted_at"] is None
    assert blocked["transmitted_by_clinician_id"] is None


def test_refused_transmission_leaves_deadlines_and_documentation_intact():
    """The derived deadlines and the stay's documentation status do not move.

    PRD §3.9: "The `transmission_deadline_at` is midnight on the completion
    deadline's date plus a further 17 days."

    Design: Difficulty/cross_entity_state_dependency/assessment_transmit_blocked_until_admission_discharged
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "coder",
                                           "coder2"))
    stay = setup_stay(env, plan_overrides={"three_hour_rule_mode": "DAILY_3HR",
                                           "disciplines": ["PT"]})
    assessment = open_assessment(env, stay["admission"]["id"],
                                 assessment_type="ADMISSION", coder_key="coder")
    set_clock("2026-08-05T09:00:00Z")
    complete_assessment(env, assessment["id"], coder_key="coder")

    api_client.transmit_assessment(assessment["id"], env["coder2_headers"])

    blocked = read_assessment(assessment["id"])
    assert blocked["completion_late"] is False
    assert blocked["transmission_deadline_at"].startswith("2026-08-28T00:00:00")
    assert_admission_dimensions(read_admission(stay["admission"]["id"]),
                                documentation_status="POC_SIGNED")
