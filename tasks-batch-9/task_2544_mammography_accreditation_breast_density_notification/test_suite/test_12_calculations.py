"""Calculations: rule selection, variant choice, input-set filtering, declared
constants, precision and the ordered coverage ladder."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    acquire_exam,
    add_second_radiologist,
    assert_coverage,
    assert_compliance_run,
    assert_instant_equals,
    assert_pct,
    assert_personnel_state,
    create_ma_policy,
    create_nv_policy,
    create_ri_policy,
    cycle_metrics,
    determine_coverage,
    generate_letter,
    interpret,
    list_total_count,
    open_cycle,
    read_cycle,
    read_exam,
    read_facility,
    read_order,
    read_personnel,
    read_unit,
    recommend_order,
    run_compliance,
    run_qualification_review,
    post_ce_credit,
    post_volume_credit,
    set_clock,
    survey_payload,
    validate_error,
    validate_success,
)


def test_patient_state_policy_outranks_the_facility_home_state_policy(api, core, coordinator_headers):
    """Two letters off the same unit are composed under two different policies.

    PRD: "For any exam-scoped decision the service first looks for the
    `StatePolicy` whose `state_code` equals the exam's `patient_state_code`;
    `state_code` is globally unique, so at most one row can match."

    Design: Corner/calculations/patient_state_policy_outranks_the_facility_home_state_policy
    """
    create_ma_policy()

    ma_exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-MA-1",
        patient_state_code="MA",
        performed_at="2026-07-20T00:00:00Z",
    )
    ct_exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-CT-1",
        patient_state_code="CT",
        performed_at="2026-07-20T00:00:00Z",
    )

    ma_letter = generate_letter(core, ma_exam["id"], dispatch_channel="MAIL")
    ct_letter = generate_letter(core, ct_exam["id"], dispatch_channel="MAIL")

    assert ma_letter["governing_state_code"] == "MA"
    assert ma_letter["reading_grade_level"] == 6
    assert_instant_equals(ma_letter["deadline_at"], "2026-08-15T00:00:00Z", "deadline_at")
    assert ma_letter["letter_type"] == "COMBINED"
    assert ma_letter["density_statement_code"] == "FDA_DENSE"
    assert ma_letter["required_notice_codes"] == [
        "FDA-LAY-SUMMARY",
        "FDA-DENSE",
        "MA-DENSE-NOTICE",
    ]

    assert ct_letter["governing_state_code"] == "CT"
    assert ct_letter["reading_grade_level"] == 8
    assert_instant_equals(ct_letter["deadline_at"], "2026-08-22T00:00:00Z", "deadline_at")
    assert ct_letter["letter_type"] == "COMBINED"
    assert ct_letter["required_notice_codes"] == [
        "FDA-LAY-SUMMARY",
        "FDA-DENSE",
        "CT-DENS-1",
        "CT-SUPP-2",
    ]

    assert_instant_equals(
        read_exam(ma_exam["id"])["notification_deadline_at"],
        "2026-08-15T00:00:00Z",
        "notification_deadline_at",
    )
    assert_instant_equals(
        read_exam(ct_exam["id"])["notification_deadline_at"],
        "2026-08-22T00:00:00Z",
        "notification_deadline_at",
    )


def test_metrics_preview_defaults_to_ppv1_and_does_not_lock_the_cycle(api, core, qa_headers):
    """The preview answers under `PPV1_SCREENING` and writes nothing onto the cycle.

    PRD: "A read-only preview of these metrics is available on the cycle without
    mutating anything. It accepts an optional `variant` query parameter, defaults to
    `PPV1_SCREENING` when omitted, and returns the nine-field shape `variant`,
    `screening_exam_count`, `recall_count`, `biopsy_count`, `cancer_count`,
    `excluded_exam_count`, `recall_rate_pct`, `ppv_pct` and
    `abnormal_interpretation_flag`. Reading the preview never changes the cycle's
    `status`, `locked_at`, `variant_at_close` or `version`, so the same cycle can be
    previewed under both variants before a decision is made."

    Design: Corner/calculations/metrics_preview_defaults_to_ppv1_and_does_not_lock_the_cycle
    """
    exam = acquire_and_interpret(
        core,
        birads=0,
        density="C",
        patient_ref="PT-VS-1",
        performed_at="2026-03-10T00:00:00Z",
    )
    validate_success(
        api.record_exam_outcome(
            exam["id"], {"biopsy_performed": True, "pathology_result": "MALIGNANT"}, qa_headers
        )
    )
    cycle = open_cycle(core)

    metrics = cycle_metrics(core, cycle["id"])
    assert metrics["variant"] == "PPV1_SCREENING"
    assert metrics["screening_exam_count"] == 1
    assert metrics["recall_count"] == 1
    assert_pct(metrics["recall_rate_pct"], 100.00, "recall_rate_pct")
    assert metrics["biopsy_count"] == 1
    assert metrics["cancer_count"] == 1
    assert metrics["excluded_exam_count"] == 0
    assert_pct(metrics["ppv_pct"], 100.00, "ppv_pct")
    assert metrics["abnormal_interpretation_flag"] is True

    stored = read_cycle(cycle["id"], qa_headers)
    assert stored["status"] == "OPEN"
    assert stored["variant_at_close"] is None
    assert stored["locked_at"] is None
    assert stored["screening_exam_count"] is None
    assert stored["recall_rate_pct"] is None
    assert stored["ppv_pct"] is None
    assert stored["followup_window_days"] == 365


def test_audit_metrics_exclude_diagnostic_unread_and_period_end_exams(api, core, qa_headers):
    """Four out-of-scope exams keep the pooled recall rate at 1/2, not 1/3 or 2/4.

    PRD: "`DIAGNOSTIC` exams, exams still `AWAITING_INTERPRETATION` or `DELAYED`,
    exams read by another radiologist, and exams performed exactly at
    `period_end` are all outside the set."

    Design: Corner/calculations/audit_metrics_exclude_diagnostic_unread_and_period_end_exams
    """
    add_second_radiologist(core)

    in_scope_recalled = acquire_and_interpret(
        core, birads=0, density="C", patient_ref="PT-IS-A", performed_at="2026-03-10T00:00:00Z"
    )
    validate_success(
        api.record_exam_outcome(
            in_scope_recalled["id"],
            {"biopsy_performed": True, "pathology_result": "MALIGNANT"},
            qa_headers,
        )
    )
    acquire_and_interpret(
        core, birads=1, density="B", patient_ref="PT-IS-B", performed_at="2026-05-01T00:00:00Z"
    )
    diagnostic = acquire_and_interpret(
        core,
        birads=0,
        density=None,
        patient_ref="PT-IS-C",
        exam_type="DIAGNOSTIC",
        performed_at="2026-04-01T00:00:00Z",
        original_image_count=6,
    )
    validate_success(
        api.record_exam_outcome(
            diagnostic["id"],
            {"biopsy_performed": True, "pathology_result": "MALIGNANT"},
            qa_headers,
        )
    )
    on_period_end = acquire_and_interpret(
        core, birads=0, density="C", patient_ref="PT-IS-D", performed_at="2026-07-01T00:00:00Z"
    )
    never_read = acquire_exam(
        core, patient_ref="PT-IS-E", performed_at="2026-06-01T00:00:00Z"
    )
    other_reader = acquire_exam(
        core, patient_ref="PT-IS-F", performed_at="2026-04-15T00:00:00Z"
    )
    interpret(core, other_reader["id"], birads=0, density="C", headers=core["rad2_headers"])

    cycle = open_cycle(core)
    metrics = cycle_metrics(core, cycle["id"], variant="PPV1_SCREENING")

    assert metrics["screening_exam_count"] == 2
    assert metrics["recall_count"] == 1
    assert_pct(metrics["recall_rate_pct"], 50.00, "recall_rate_pct")
    assert metrics["biopsy_count"] == 1
    assert metrics["cancer_count"] == 1
    assert_pct(metrics["ppv_pct"], 100.00, "ppv_pct")
    assert metrics["excluded_exam_count"] == 0
    assert metrics["abnormal_interpretation_flag"] is True

    unread = read_exam(never_read["id"])
    assert unread["report_status"] == "AWAITING_INTERPRETATION"
    assert unread["interpreting_physician_id"] is None
    assert read_exam(on_period_end["id"])["recall_flag"] is True
    excluded_diagnostic = read_exam(diagnostic["id"])
    assert excluded_diagnostic["recall_flag"] is False
    assert excluded_diagnostic["pathology_result"] == "MALIGNANT"


def test_survey_window_length_constant_rejects_397_days_and_accepts_396(api, core, coordinator_headers):
    """396 days is the exact declared ceiling, and the rejected call persists nothing.

    PRD: "First the window must be well formed: `effective_end` strictly after
    `effective_start`, and the span between them at most 396 days, or the create
    is refused with `ERR_SURVEY_WINDOW_INVALID`."

    Design: Corner/calculations/survey_window_length_constant_rejects_397_days_and_accepts_396
    """
    validate_error(
        api.create_physicist_survey(
            core["unit_id"],
            survey_payload(
                effective_start="2026-07-01T00:00:00Z", effective_end="2027-08-02T00:00:00Z"
            ),
            core["phys_headers"],
        ),
        "ERR_SURVEY_WINDOW_INVALID",
        expected_status=422,
    )

    survey = validate_success(
        api.create_physicist_survey(
            core["unit_id"],
            survey_payload(
                effective_start="2026-07-01T00:00:00Z", effective_end="2027-08-01T00:00:00Z"
            ),
            core["phys_headers"],
        ),
        expected_status=201,
    )
    assert survey["status"] == "DRAFT"
    assert_instant_equals(survey["effective_start"], "2026-07-01T00:00:00Z", "effective_start")
    assert_instant_equals(survey["effective_end"], "2027-08-01T00:00:00Z", "effective_end")
    assert (
        list_total_count(api.list_unit_physicist_surveys(core["unit_id"], coordinator_headers)) == 1
    )
    assert read_unit(core["unit_id"])["survey_compliance"] == "OVERDUE"


def test_ce_hours_sum_at_two_decimals_before_the_threshold_comparison(api, core, coordinator_headers):
    """7.50 + 7.75 sums to 15.25 and only then meets the 15-hour threshold.

    PRD: "`ce_hours_36mo` is the sum of `ce_hours` across the person's
    `CATEGORY_1_CE` credits whose `awarded_on` falls in the window that begins
    1095 days before the clock and ends at the clock, with both edges included."

    Design: Corner/calculations/ce_hours_sum_at_two_decimals_before_the_threshold_comparison
    """
    post_ce_credit(
        core, core["tech_id"], 7.50, awarded_on="2025-01-15T00:00:00Z", source_note="Regional QC course"
    )
    post_ce_credit(
        core, core["tech_id"], 7.75, awarded_on="2026-02-20T00:00:00Z", source_note="Positioning workshop"
    )
    post_volume_credit(
        core,
        core["tech_id"],
        200,
        awarded_on="2025-06-01T00:00:00Z",
        modality="DBT_3D",
        source_note="Annual volume attestation",
    )

    reviewed = run_qualification_review(
        core,
        core["tech_id"],
        review_note="Continuing-education review with fractional credit hours",
    )
    assert reviewed["ce_hours_36mo"] == pytest.approx(15.25, abs=0.01)
    assert_personnel_state(
        reviewed,
        qualification_status="QUALIFIED",
        ce_status="COMPLIANT",
        volume_credit_24mo=200,
        ce_deadline_at=None,
    )
    assert_instant_equals(
        reviewed["last_qualification_review_at"],
        "2026-08-01T00:00:00Z",
        "last_qualification_review_at",
    )
    assert (
        list_total_count(api.list_personnel_credits(core["tech_id"], coordinator_headers)) == 3
    )


def test_waiver_threshold_alone_decides_between_a_waived_and_a_billed_share(api, core):
    """Identical arithmetic diverges only at the de-minimis waiver comparison.

    PRD: "Step nine handles the de-minimis waiver under
    `COVERAGE_WITH_COST_SHARING`: when the residual patient share computed in
    step seven is at or below the policy's
    `supplemental_cost_share_waiver_threshold_cents`, the facility absorbs it — the
    `coverage_outcome` is `COVERED_NO_COST_SHARE`, `covered_amount_cents` becomes the
    whole `allowed_amount_cents`, `patient_responsibility_cents` is 0, and the tier
    is retained."

    Design: Corner/calculations/waiver_threshold_alone_decides_between_a_waived_and_a_billed_share
    """
    create_ma_policy()
    create_ri_policy()

    ma_exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-WV-MA",
        patient_state_code="MA",
        performed_at="2026-07-20T00:00:00Z",
    )
    ma_order = recommend_order(
        core,
        ma_exam["id"],
        modality="ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue, MA patient",
    )
    ri_exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-WV-RI",
        patient_state_code="RI",
        performed_at="2026-07-20T00:00:00Z",
    )
    ri_order = recommend_order(
        core,
        ri_exam["id"],
        modality="ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue, RI patient",
    )

    ma_determined = determine_coverage(core, ma_order["id"])
    ri_determined = determine_coverage(core, ri_order["id"])

    assert_coverage(
        ma_determined,
        coverage_outcome="COVERED_WITH_COST_SHARE",
        allowed_amount_cents=31500,
        covered_amount_cents=19373,
        patient_responsibility_cents=12127,
        coverage_tier="TIER_1",
        governing_state_code="MA",
    )
    assert_coverage(
        ri_determined,
        coverage_outcome="COVERED_NO_COST_SHARE",
        allowed_amount_cents=31500,
        covered_amount_cents=31500,
        patient_responsibility_cents=0,
        coverage_tier="TIER_1",
        governing_state_code="RI",
    )
    assert ma_determined["allowed_amount_cents"] == 28500 + 3000
    assert ma_determined["covered_amount_cents"] != 19372
    assert ma_determined["status"] == "COVERAGE_DETERMINED"
    assert ri_determined["status"] == "COVERAGE_DETERMINED"
    assert ma_order["version"] == 1
    assert ma_determined["version"] == 2
    assert ri_determined["version"] == 2


def test_non_dense_and_no_mandate_determinations_skip_the_admin_fee_and_the_tier(api, core):
    """Both early exits return the bare fee-schedule amount with a null tier.

    PRD: "Step three short-circuits on mandate: when the policy's
    `supplemental_coverage_mandate` is `NONE`, the `allowed_amount_cents` is the
    bare fee-schedule amount for the ordered modality with no administration fee
    added, the `coverage_outcome` is `PATIENT_RESPONSIBILITY`,
    `covered_amount_cents` is 0, `patient_responsibility_cents` equals the
    allowed amount, and `coverage_tier` stays null."

    Design: Corner/calculations/non_dense_and_no_mandate_determinations_skip_the_admin_fee_and_the_tier
    """
    create_nv_policy()

    ct_exam = acquire_and_interpret(
        core,
        birads=1,
        density="B",
        patient_ref="PT-ND-CT",
        patient_state_code="CT",
        performed_at="2026-07-20T00:00:00Z",
    )
    ct_order = recommend_order(
        core,
        ct_exam["id"],
        modality="ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Patient requested despite a scattered-density read",
    )
    nv_exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-ND-NV",
        patient_state_code="NV",
        performed_at="2026-07-20T00:00:00Z",
    )
    nv_order = recommend_order(
        core,
        nv_exam["id"],
        modality="MRI",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue, NV patient",
    )

    nv_determined = determine_coverage(core, nv_order["id"])
    ct_determined = determine_coverage(core, ct_order["id"])

    assert_coverage(
        nv_determined,
        coverage_outcome="PATIENT_RESPONSIBILITY",
        allowed_amount_cents=120000,
        covered_amount_cents=0,
        patient_responsibility_cents=120000,
        coverage_tier=None,
        governing_state_code="NV",
    )
    assert read_exam(nv_exam["id"])["density_category"] == "C"

    assert_coverage(
        ct_determined,
        coverage_outcome="DENIED",
        allowed_amount_cents=28500,
        covered_amount_cents=0,
        patient_responsibility_cents=28500,
        coverage_tier=None,
        governing_state_code="CT",
    )
    assert nv_determined["status"] == "COVERAGE_DETERMINED"
    assert ct_determined["status"] == "COVERAGE_DETERMINED"
    assert nv_determined["allowed_amount_cents"] != 123000
    assert ct_determined["allowed_amount_cents"] != 31500


def test_compliance_run_sweeps_are_order_insensitive_and_respect_the_due_date_edge(
    api, core, qa_headers
):
    """Both overdue exams are swept regardless of insertion order; the future one is not.

    PRD: "Sweep two handles delayed reports. Every exam of the facility still in
    `report_status` `AWAITING_INTERPRETATION` whose `report_due_at` is strictly
    before the clock moves to `DELAYED`. These are processed in ascending
    `performed_at` with ascending `created_at` as the tie-break, never by `id`."

    Design: Corner/calculations/compliance_run_sweeps_are_order_insensitive_and_respect_the_due_date_edge
    """
    later_performed = acquire_exam(
        core, patient_ref="PT-CR-P", performed_at="2026-07-01T00:00:00Z"
    )
    earlier_performed = acquire_exam(
        core, patient_ref="PT-CR-Q", performed_at="2026-06-01T00:00:00Z"
    )
    followed_up = acquire_and_interpret(
        core, birads=1, density="C", patient_ref="PT-CR-R", performed_at="2026-05-10T00:00:00Z"
    )
    order = recommend_order(
        core,
        followed_up["id"],
        modality="ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue",
    )
    order = determine_coverage(core, order["id"])

    set_clock("2026-10-05T00:00:00Z")
    future_due = acquire_exam(
        core, patient_ref="PT-CR-S", performed_at="2026-10-01T00:00:00Z"
    )

    assert_instant_equals(
        read_exam(later_performed["id"])["report_due_at"], "2026-07-31T00:00:00Z", "report_due_at"
    )
    assert_instant_equals(
        read_exam(earlier_performed["id"])["report_due_at"], "2026-07-01T00:00:00Z", "report_due_at"
    )
    assert_instant_equals(
        read_exam(future_due["id"])["report_due_at"], "2026-10-31T00:00:00Z", "report_due_at"
    )
    assert_instant_equals(order["recommended_at"], "2026-08-01T00:00:00Z", "recommended_at")
    assert_instant_equals(order["followup_due_at"], "2026-09-30T00:00:00Z", "followup_due_at")

    result = run_compliance(core, headers=qa_headers)
    assert_compliance_run(
        result,
        ran_at="2026-10-05T00:00:00Z",
        units_marked_reaccreditation_due=0,
        # `units_survey_overdue` is deliberately not pinned: PRD names the field
        # ("`units_marked_reaccreditation_due` and `units_survey_overdue` from
        # sweep one") but never says whether it counts units that *moved* into
        # `OVERDUE` on this sweep or censuses the units sitting in `OVERDUE`
        # afterwards.  The two readings diverge for a unit that was already
        # `OVERDUE` at creation, and the replay sentence ("reports zeros across
        # all seven counters") supports the movement reading, so no single value
        # is derivable from PRD here.
        exams_marked_delayed=2,
        letters_marked_delivered=0,
        orders_marked_lost=1,
        personnel_moved_to_grace=3,
        personnel_moved_to_deficient=0,
        compliance_posture="CONDITIONAL",
    )

    assert read_exam(later_performed["id"])["report_status"] == "DELAYED"
    assert read_exam(earlier_performed["id"])["report_status"] == "DELAYED"
    assert read_exam(future_due["id"])["report_status"] == "AWAITING_INTERPRETATION"
    assert read_order(order["id"])["status"] == "LOST_TO_FOLLOW_UP"
    assert read_exam(followed_up["id"])["follow_up_status"] == "LOST_TO_FOLLOW_UP"

    technologist = read_personnel(core["tech_id"])
    assert_personnel_state(technologist, qualification_status="QUALIFIED", ce_status="GRACE")
    assert_instant_equals(
        technologist["ce_deadline_at"], "2027-01-03T00:00:00Z", "ce_deadline_at"
    )
    assert_instant_equals(
        read_facility(core["facility_id"])["last_compliance_run_at"],
        "2026-10-05T00:00:00Z",
        "last_compliance_run_at",
    )
