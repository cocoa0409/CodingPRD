"""Difficulty queue A — dual_variant_calc instances."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork,
    create_allegation_payload, create_subject_payload,
    create_collection_scope_payload, create_evidence_item_payload,
    create_interview_payload, create_calibrate_payload,
    create_recommendation_payload, add_acknowledged_notice,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]


def _setup_dv1_scenario(api):
    """Case FINDINGS with: allegation LINKED, subject EMP-100, scope COLLECTED
    holding evidence e1 still UNDER_REVIEW, interview UPJOHN_DELIVERED (not
    completed), notice ACKNOWLEDGED."""
    bundle = create_case_in_fieldwork(
        title="Case DV-1", allegation_category="FRAUD", severity="HIGH",
        department="Finance",
    )
    case = bundle["case"]
    alg = get_success_data(api.create_allegation(
        case["id"],
        create_allegation_payload(
            reporter_channel="HOTLINE", is_anonymous=False,
            reporter_ref="rep-1", narrative="Expense fraud",
        ),
        IC,
    ))
    get_success_data(api.transition_allegation(alg["id"], {"to_status": "TRIAGED"}, IC))
    alg = get_success_data(api.transition_allegation(alg["id"], {"to_status": "LINKED"}, IC))
    subj = get_success_data(api.create_subject(
        case["id"], create_subject_payload(employee_ref="EMP-100"), INV
    ))
    notice = add_acknowledged_notice(case["id"], custodian_ref="EMP-100")
    scope = get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-05T00:00:00Z", planned_end="2026-05-10T00:00:00Z",
            preservation_notice_id=notice["id"],
        ),
        INV,
    ))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "APPROVED"}, mgr))
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "IN_PROGRESS"}, inv1))
    ev = get_success_data(api.create_evidence_item(
        scope["id"],
        create_evidence_item_payload(
            custodian_ref="EMP-100", hash_value="h1", size_bytes=2_000_000,
            captured_at="2026-05-06T00:00:00Z",
        ),
        INV,
    ))
    get_success_data(api.transition_evidence_item(ev["id"], {"to_status": "UNDER_REVIEW"}, inv1))
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "COLLECTED"}, inv1))
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-08T14:00:00Z",
            scheduled_end="2026-05-08T15:00:00Z",
        ),
        INV,
    ))
    get_success_data(api.transition_interview(interview["id"], {"to_status": "UPJOHN_DELIVERED"}, inv1))
    case = get_success_data(api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1))
    return {
        "case": case, "allegation": alg, "subject": subj, "scope": scope,
        "evidence": ev, "interview": interview,
    }


def test_substantiation_provisional_vs_final_input_sets_provisional(api):
    """PRD §3.7: "The provisional variant, computed at creation, defines E
    as the number of evidence ids in the finding's `evidence_item_ids` whose
    item status is `UNDER_REVIEW` or `ADMITTED`, W as the number of
    `WitnessInterview` rows of the case with `is_subject_interview` false and
    status `UPJOHN_DELIVERED` or `COMPLETED`, C fixed at 0.15 (the MEDIUM
    consistency value), and A fixed at 0."

    With E=1 (UNDER_REVIEW), W=1 (UPJOHN_DELIVERED), C=0.15, A=0:
    score = 0.25 + 0.15 + 0.15 + 0 = 0.55.

    Design: Difficulty/dual_variant_calc/substantiation_provisional_vs_final_input_sets
    """
    reset_clock()
    bundle = _setup_dv1_scenario(api)
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    finding = get_success_data(api.create_finding(
        bundle["case"]["id"],
        {"allegation_id": bundle["allegation"]["id"],
         "subject_id": bundle["subject"]["id"],
         "evidence_item_ids": [bundle["evidence"]["id"]]},
        inv1,
    ))
    assert finding["substantiation_score_provisional"] == pytest.approx(0.55, abs=0.001)


def test_substantiation_provisional_vs_final_input_sets_final(api):
    """PRD §3.7: "The final variant, computed at calibration and
    recalibration, narrows both input sets: E counts only evidence in
    `ADMITTED`, W counts only interviews in `COMPLETED` (still restricted to
    `is_subject_interview` false), and C and A come from the calibrate
    payload..."

    Same underlying data (evidence UNDER_REVIEW, interview UPJOHN_DELIVERED)
    yields E=0, W=0 in the final variant; with C=0.15 (MEDIUM) and A=0 the
    final score is 0.15.

    Design: Difficulty/dual_variant_calc/substantiation_provisional_vs_final_input_sets
    """
    reset_clock()
    bundle = _setup_dv1_scenario(api)
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    finding = get_success_data(api.create_finding(
        bundle["case"]["id"],
        {"allegation_id": bundle["allegation"]["id"],
         "subject_id": bundle["subject"]["id"],
         "evidence_item_ids": [bundle["evidence"]["id"]]},
        inv1,
    ))
    provisional = finding["substantiation_score_provisional"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    finding_after = get_success_data(api.transition_finding(
        finding["id"],
        create_calibrate_payload(
            consistency_level="MEDIUM", subject_admission=False,
            finding_type="INCONCLUSIVE",
        ),
        hr1,
    ))
    assert finding_after["substantiation_score_final"] == pytest.approx(0.15, abs=0.001)
    assert provisional == pytest.approx(0.55, abs=0.001)
    assert finding_after["substantiation_score_final"] != provisional


def test_discipline_matrix_vs_calibrated_adjustments_matrix(api):
    """PRD §3.8: "The base is 10 times the severity weight, where `LOW`
    weighs 1, `MEDIUM` 2, `HIGH` 3, and `CRITICAL` 4. The prior-history
    multiplier is 1 plus 0.25 times the smaller of `prior_history_count` and
    3. The `index_policy_matrix` is the product of the base and the
    multiplier, rounded half-up to an integer, and it ignores mitigation and
    aggravation entirely."

    HIGH severity (base 30) with prior_history_count=0 gives
    index_policy_matrix = round_half_up(30 * 1.0, 0) = 30.

    Design: Difficulty/dual_variant_calc/discipline_matrix_vs_calibrated_adjustments
    """
    reset_clock()
    from test_helpers import setup_final_substantiated_finding
    bundle = setup_final_substantiated_finding(severity="HIGH", subject_emp="EMP-DV2")
    finding = bundle["finding"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rec = get_success_data(api.create_disciplinary_recommendation(
        finding["id"],
        create_recommendation_payload(
            mitigation_count=0, aggravation_count=2,
            recommended_action="WARNING",
            justification="HR disagrees with calibrated tier",
        ),
        hr1,
    ))
    assert rec["index_policy_matrix"] == 30
    assert rec["prior_history_count"] == 0


def test_discipline_matrix_vs_calibrated_adjustments_calibrated(api):
    """PRD §3.8: "The `index_calibrated` is `index_policy_matrix` plus 5
    times the smaller of `aggravation_count` and 2, minus 5 times the smaller
    of `mitigation_count` and 2."
    PRD §3.8: "The tier mapping is shared by both variants: an index strictly
    below 20 maps to `COACHING`; an index of at least 20 and at most 39 maps
    to `WARNING`; an index of at least 40 and at most 59 maps to
    `SUSPENSION`; an index of at least 60 maps to `TERMINATION`. The
    `suggested_action` stored on the recommendation is the tier of
    `index_calibrated`..."

    index_calibrated = 30 + 5*2 - 5*0 = 40 => SUSPENSION; matrix tier of 30
    is WARNING — variants diverge on the same inputs.

    Design: Difficulty/dual_variant_calc/discipline_matrix_vs_calibrated_adjustments
    """
    reset_clock()
    from test_helpers import setup_final_substantiated_finding
    bundle = setup_final_substantiated_finding(severity="HIGH", subject_emp="EMP-DV2B")
    finding = bundle["finding"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rec = get_success_data(api.create_disciplinary_recommendation(
        finding["id"],
        create_recommendation_payload(
            mitigation_count=0, aggravation_count=2,
            recommended_action="WARNING",
            justification="HR disagrees with calibrated tier",
        ),
        hr1,
    ))
    assert rec["index_calibrated"] == 40
    assert rec["suggested_action"] == "SUSPENSION"
    assert rec["index_policy_matrix"] == 30
