"""Paired calculations that must diverge over one identical data set."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    assert_coverage,
    assert_metrics,
    assert_pct,
    assert_unit_image_ledger,
    create_ma_policy,
    document_repeat,
    open_cycle,
    read_unit,
    recommend_order,
    record_outcome,
    setup_core,
    validate_success,
)


@pytest.fixture
def audit_world():
    """One radiologist with three screening reads: a recalled malignancy, a
    negative read, and a BI-RADS 4 biopsy that was never a recall."""
    core = setup_core()
    exam_a = acquire_and_interpret(
        core,
        birads=0,
        density="C",
        patient_ref="PT-1001",
        performed_at="2026-02-10T00:00:00Z",
    )
    record_outcome(core, exam_a["id"], True, "MALIGNANT")
    acquire_and_interpret(
        core,
        birads=1,
        density="B",
        patient_ref="PT-1002",
        performed_at="2026-03-01T00:00:00Z",
    )
    exam_c = acquire_and_interpret(
        core,
        birads=4,
        density="C",
        patient_ref="PT-1003",
        performed_at="2026-04-01T00:00:00Z",
    )
    record_outcome(core, exam_c["id"], True, "BENIGN")
    cycle = open_cycle(
        core,
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-15T00:00:00Z",
        followup_window_days=365,
    )
    core["cycle_id"] = cycle["id"]
    return core


def test_ppv1_screening_scores_only_the_recalled_biopsy(api, audit_world, qa_headers):
    """PPV1 admits one candidate out of the two biopsied exams, so its yield is 100.00.

    PRD: "Under `PPV1_SCREENING` — the MQSA and BCSC screening measure — the
    candidate set is the in-scope exams that were **both** recalled
    (`recall_flag` true) **and** have `biopsy_performed` true, and a candidate is
    scored only when its `pathology_result` is `BENIGN` or `MALIGNANT` **and**
    its `outcome_recorded_at` is strictly earlier than its `performed_at` plus
    the cycle's `followup_window_days`."

    Design: Difficulty/dual_variant_calc/ppv1_versus_ppv3_variant_divergence_on_radiologist_audit_cycle
    """
    response = api.get_audit_cycle_metrics(
        audit_world["cycle_id"], qa_headers, {"variant": "PPV1_SCREENING"}
    )
    metrics = validate_success(response)
    assert_metrics(
        metrics,
        variant="PPV1_SCREENING",
        screening_exam_count=3,
        recall_count=1,
        biopsy_count=1,
        cancer_count=1,
        excluded_exam_count=0,
        ppv_pct=100.00,
        recall_rate_pct=33.33,
        abnormal_interpretation_flag=True,
    )


def test_ppv3_biopsy_all_scores_every_biopsy_and_halves_the_yield(api, audit_world, qa_headers):
    """PPV3 admits both biopsies over the identical exam set, so its yield is 50.00.

    PRD: "Under `PPV3_BIOPSY_ALL` — the ACR biopsy-yield measure — the candidate
    set is every in-scope exam with `biopsy_performed` true regardless of
    `recall_flag`, and a candidate is scored purely on its `pathology_result`
    being `BENIGN` or `MALIGNANT`; the `followup_window_days` window is
    deliberately not applied."

    Design: Difficulty/dual_variant_calc/ppv1_versus_ppv3_variant_divergence_on_radiologist_audit_cycle
    """
    ppv1 = validate_success(
        api.get_audit_cycle_metrics(
            audit_world["cycle_id"], qa_headers, {"variant": "PPV1_SCREENING"}
        )
    )
    ppv3 = validate_success(
        api.get_audit_cycle_metrics(
            audit_world["cycle_id"], qa_headers, {"variant": "PPV3_BIOPSY_ALL"}
        )
    )
    assert_metrics(
        ppv3,
        variant="PPV3_BIOPSY_ALL",
        screening_exam_count=3,
        recall_count=1,
        biopsy_count=2,
        cancer_count=1,
        excluded_exam_count=0,
        ppv_pct=50.00,
        recall_rate_pct=33.33,
        abnormal_interpretation_flag=True,
    )
    assert ppv3["ppv_pct"] != ppv1["ppv_pct"], (
        "The two variants must diverge over the identical exam set: "
        f"PPV1 {ppv1['ppv_pct']} vs PPV3 {ppv3['ppv_pct']}"
    )
    assert ppv3["recall_count"] == ppv1["recall_count"]
    assert_pct(ppv3["recall_rate_pct"], ppv1["recall_rate_pct"], "recall_rate_pct")


@pytest.fixture
def repeat_world():
    """Three four-image screening exams on one unit, with a single two-image repeat."""
    core = setup_core()
    first = acquire_and_interpret(
        core, patient_ref="PT-2001", performed_at="2026-07-01T00:00:00Z"
    )
    acquire_and_interpret(core, patient_ref="PT-2002", performed_at="2026-07-02T00:00:00Z")
    acquire_and_interpret(core, patient_ref="PT-2003", performed_at="2026-07-03T00:00:00Z")
    document_repeat(core, first["id"], "POSITIONING", 2)
    return core


def test_image_based_repeat_rate_pools_images_over_the_whole_unit(api, repeat_world):
    """Two repeats against fourteen total images round once to 14.29 percent.

    PRD: "The image-based rate, `image_based_repeat_rate_pct`, is 100 multiplied
    by `repeat_images_acquired`, divided by `total_images_acquired`, rounded half
    up to two decimal places — and it is null when `total_images_acquired` is 0."

    Design: Difficulty/dual_variant_calc/image_based_versus_patient_based_repeat_rate_divergence_on_unit
    """
    unit = read_unit(repeat_world["unit_id"])
    assert_unit_image_ledger(
        unit,
        total_images_acquired=14,
        repeat_images_acquired=2,
        image_based_repeat_rate_pct=14.29,
    )


def test_patient_based_repeat_rate_counts_exams_and_only_the_image_rate_flags(api, repeat_world):
    """One repeated exam out of three is 33.33 percent, and 14.29 is what flags the unit.

    PRD: "The patient-based rate, `patient_based_repeat_rate_pct`, is 100
    multiplied by the number of the unit's exams that have at least one
    non-retracted repeat, divided by the total number of the unit's exams,
    rounded half up to two decimal places — and it is null when the unit has no
    exams at all."

    Design: Difficulty/dual_variant_calc/image_based_versus_patient_based_repeat_rate_divergence_on_unit
    """
    unit = read_unit(repeat_world["unit_id"])
    assert_unit_image_ledger(
        unit,
        image_based_repeat_rate_pct=14.29,
        patient_based_repeat_rate_pct=33.33,
        repeat_rate_flag=True,
    )
    assert unit["image_based_repeat_rate_pct"] != unit["patient_based_repeat_rate_pct"], (
        "The two variants must diverge over the identical exam and repeat set"
    )


@pytest.fixture
def coverage_world():
    """One CT-resident and one MA-resident dense screening exam, each with an
    ULTRASOUND order still in `RECOMMENDED`."""
    core = setup_core()
    create_ma_policy()
    ct_exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-3001",
        patient_state_code="CT",
        performed_at="2026-07-20T00:00:00Z",
    )
    ma_exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-3002",
        patient_state_code="MA",
        performed_at="2026-07-21T00:00:00Z",
    )
    core["ct_order_id"] = recommend_order(
        core,
        ct_exam["id"],
        "ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense breasts, supplemental US",
    )["id"]
    core["ma_order_id"] = recommend_order(
        core,
        ma_exam["id"],
        "ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense breasts, supplemental US",
    )["id"]
    return core


def test_no_cost_sharing_mandate_covers_the_whole_allowed_amount(api, coverage_world, coordinator_headers):
    """The CT patient owes nothing, yet the order still records the tier it never billed.

    PRD: "Step eight branches on the mandate for the no-cost-sharing case: when
    the policy's `supplemental_coverage_mandate` is `COVERAGE_NO_COST_SHARING`,
    the `coverage_outcome` is `COVERED_NO_COST_SHARE`, `covered_amount_cents`
    equals the whole `allowed_amount_cents`, `patient_responsibility_cents` is 0,
    and the `coverage_tier` selected in step six is still recorded on the row
    even though its rate was not billed."

    Design: Difficulty/dual_variant_calc/coverage_mandate_variant_divergence_on_supplemental_order
    """
    order = validate_success(
        api.determine_coverage(coverage_world["ct_order_id"], coordinator_headers)
    )
    assert_coverage(
        order,
        governing_state_code="CT",
        allowed_amount_cents=31500,
        coverage_tier="TIER_1",
        covered_amount_cents=31500,
        patient_responsibility_cents=0,
        coverage_outcome="COVERED_NO_COST_SHARE",
    )


def test_cost_sharing_mandate_bills_the_tier_rate_on_the_same_allowed_amount(api, coverage_world, coordinator_headers):
    """The MA patient's identical 31500-cent study bills 19373 and leaves 12127.

    PRD: "Step ten is the ordinary cost-sharing result: the residual share
    survives only when it strictly exceeds the waiver threshold, in which case
    the `coverage_outcome` is `COVERED_WITH_COST_SHARE`, `covered_amount_cents`
    is the tier-rated figure from step seven, and `patient_responsibility_cents`
    is the residual."

    Design: Difficulty/dual_variant_calc/coverage_mandate_variant_divergence_on_supplemental_order
    """
    ct_order = validate_success(
        api.determine_coverage(coverage_world["ct_order_id"], coordinator_headers)
    )
    ma_order = validate_success(
        api.determine_coverage(coverage_world["ma_order_id"], coordinator_headers)
    )
    assert_coverage(
        ma_order,
        governing_state_code="MA",
        allowed_amount_cents=31500,
        coverage_tier="TIER_1",
        covered_amount_cents=19373,
        patient_responsibility_cents=12127,
        coverage_outcome="COVERED_WITH_COST_SHARE",
    )
    assert ct_order["allowed_amount_cents"] == ma_order["allowed_amount_cents"]
    assert ct_order["coverage_tier"] == ma_order["coverage_tier"] == "TIER_1"
    assert ct_order["coverage_outcome"] != ma_order["coverage_outcome"]
