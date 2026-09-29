"""Formulas whose nesting, rounding order and step order are all observable."""

import pytest

from test_helpers import (
    CLOCK_START_UTC,
    acquire_and_interpret,
    add_second_unit,
    assert_coverage,
    assert_instant_equals,
    assert_letter_notice_codes,
    assert_pct,
    close_cycle,
    create_ma_policy,
    generate_letter,
    open_cycle,
    read_cycle,
    read_exam,
    recommend_order,
    setup_core,
    validate_success,
)


@pytest.fixture
def urgent_dense_exam(core):
    """A screening read at BI-RADS 0 with density C is both dense and urgent."""
    exam = acquire_and_interpret(
        core,
        birads=0,
        density="C",
        patient_ref="PT-4001",
        performed_at="2026-07-25T00:00:00Z",
    )
    core["exam"] = exam
    core["exam_id"] = exam["id"]
    return core


def test_reading_grade_takes_the_lower_of_the_state_and_federal_ceilings(api, urgent_dense_exam):
    """A state ceiling of grade 10 still yields grade 8, and the state notice is layered on.

    PRD: "The letter's `reading_grade_level` is the lower of the policy's
    `lay_summary_max_reading_grade` and the federal ceiling of grade 8 — a state
    declaring grade 12 still yields grade 8, while a state declaring grade 6
    yields grade 6."

    Design: Difficulty/combinatorial_formula/notification_nested_min_of_state_federal_and_urgent_ceilings
    """
    core = urgent_dense_exam
    letter = generate_letter(core, core["exam_id"], dispatch_channel="MAIL")
    assert letter["reading_grade_level"] == 8
    assert letter["letter_type"] == "COMBINED"
    assert letter["density_statement_code"] == "FDA_DENSE"
    assert letter["governing_state_code"] == "CT"
    assert letter["status"] == "QUEUED"
    assert letter["supersedes_letter_id"] is None
    assert_letter_notice_codes(
        letter,
        [
            "FDA-LAY-SUMMARY",
            "FDA-DENSE",
            "FDA-URGENT-FINDING",
            "CT-DENS-1",
            "CT-SUPP-2",
        ],
    )


def test_urgent_finding_overrides_both_the_state_and_the_federal_deadline(api, urgent_dense_exam):
    """min(21, 30) is 21, and the urgent floor cuts it again to seven days.

    PRD: "The deadline in days is the lower of the policy's
    `lay_summary_deadline_days` and the federal ceiling of 30 days; and then, when
    the exam is urgent, that result is lowered again to at most 7 days."

    Design: Difficulty/combinatorial_formula/notification_nested_min_of_state_federal_and_urgent_ceilings
    """
    core = urgent_dense_exam
    letter = generate_letter(core, core["exam_id"], dispatch_channel="MAIL")
    assert_instant_equals(letter["deadline_at"], "2026-08-08T00:00:00Z", "deadline_at")
    exam = read_exam(core["exam_id"])
    assert_instant_equals(
        exam["notification_deadline_at"], "2026-08-08T00:00:00Z", "notification_deadline_at"
    )
    assert exam["notification_status"] == "GENERATED"


@pytest.fixture
def pooled_recall_world():
    """One recall on the DBT_3D unit and two negative reads on the DM_2D unit."""
    core = setup_core()
    unit2 = add_second_unit(
        core["facility_id"],
        manufacturer="GE",
        model_serial="PRI-2200",
        modality="DM_2D",
        accreditation_expires_on="2027-09-30T00:00:00Z",
    )
    acquire_and_interpret(
        core,
        birads=0,
        density="C",
        patient_ref="PT-5001",
        performed_at="2026-02-01T00:00:00Z",
    )
    acquire_and_interpret(
        core,
        birads=1,
        density="B",
        patient_ref="PT-5002",
        performed_at="2026-03-01T00:00:00Z",
        unit_id=unit2["id"],
    )
    acquire_and_interpret(
        core,
        birads=2,
        density="B",
        patient_ref="PT-5003",
        performed_at="2026-04-01T00:00:00Z",
        unit_id=unit2["id"],
    )
    cycle = open_cycle(
        core,
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-15T00:00:00Z",
        followup_window_days=365,
    )
    core["cycle_id"] = cycle["id"]
    return core


def test_recall_rate_is_pooled_once_rather_than_averaged_per_unit(api, pooled_recall_world):
    """One recall out of three exams is 33.33 percent, never the 50.00 an average gives.

    PRD: "It is never the mean of per-unit or per-modality rates: one recall out
    of one `DM_2D` exam together with zero recalls out of two `DBT_3D` exams pools
    to 33.33, whereas averaging the two sub-rates would wrongly give 50.00."

    Design: Difficulty/combinatorial_formula/recall_rate_pooled_across_units_then_rounded_once
    """
    core = pooled_recall_world
    cycle = close_cycle(core, core["cycle_id"], "PPV3_BIOPSY_ALL")
    assert cycle["screening_exam_count"] == 3
    assert cycle["recall_count"] == 1
    assert_pct(cycle["recall_rate_pct"], 33.33, "recall_rate_pct")
    assert cycle["recall_rate_pct"] != 50.00
    assert cycle["abnormal_interpretation_flag"] is True


def test_closing_freezes_the_variant_and_leaves_an_unscored_yield_null(api, pooled_recall_world):
    """With no biopsies at all the yield is null while the recall rate still stands.

    PRD: "On success the metrics run under the requested variant, every metric
    field plus `variant_at_close` is frozen onto the row, the `status` becomes
    `LOCKED`, `locked_at` is stamped at the logical clock, and the `version`
    advances."

    Design: Difficulty/combinatorial_formula/recall_rate_pooled_across_units_then_rounded_once
    """
    core = pooled_recall_world
    close_cycle(core, core["cycle_id"], "PPV3_BIOPSY_ALL")
    cycle = read_cycle(core["cycle_id"])
    assert cycle["status"] == "LOCKED"
    assert cycle["variant_at_close"] == "PPV3_BIOPSY_ALL"
    assert cycle["biopsy_count"] == 0
    assert cycle["cancer_count"] == 0
    assert cycle["ppv_pct"] is None
    assert_instant_equals(cycle["locked_at"], CLOCK_START_UTC, "locked_at")


@pytest.fixture
def cem_order(core):
    """A contrast-enhanced study ordered for an MA-resident dense patient."""
    create_ma_policy()
    exam = acquire_and_interpret(
        core,
        birads=1,
        density="C",
        patient_ref="PT-6001",
        patient_state_code="MA",
        performed_at="2026-07-22T00:00:00Z",
    )
    order = recommend_order(
        core,
        exam["id"],
        "CEM",
        headers=core["rad_headers"],
        recommendation_note="Contrast enhanced mammography for dense breasts",
    )
    core["order_id"] = order["id"]
    return core


def test_admin_fee_is_folded_in_before_the_tier_ceilings_are_compared(api, cem_order, coordinator_headers):
    """60000 plus the 3000-cent admin fee lands exactly on the inclusive TIER_2 ceiling.

    PRD: "So an ultrasound at 28500 plus 3000 lands at 31500 cents and is exactly
    on the `TIER_1` ceiling; a contrast-enhanced study at 60000 plus 3000 lands at
    63000 and is exactly on the `TIER_2` ceiling; an MRI at 120000 plus 3000 lands
    in `TIER_3`."

    Design: Difficulty/combinatorial_formula/coverage_admin_fee_enters_tier_selection_before_the_rate_is_billed
    """
    order = validate_success(
        api.determine_coverage(cem_order["order_id"], coordinator_headers)
    )
    assert_coverage(
        order,
        allowed_amount_cents=63000,
        coverage_tier="TIER_2",
        coverage_outcome="COVERED_WITH_COST_SHARE",
    )
    assert order["status"] == "COVERAGE_DETERMINED"


def test_tier_rate_bills_the_fee_inclusive_amount_not_the_bare_fee_schedule(api, cem_order, coordinator_headers):
    """The 0.775 TIER_2 rate applies to 63000, giving 48825 and not 46500.

    PRD: "Step seven prices it: the payer's share is the allowed amount
    multiplied by the tier rate — 0.615 for `TIER_1`, 0.775 for `TIER_2`, 0.90 for
    `TIER_3` — rounded half up to whole cents, and the residual patient share is
    the allowed amount minus that covered figure, so the two always sum back to
    the allowed amount exactly."

    Design: Difficulty/combinatorial_formula/coverage_admin_fee_enters_tier_selection_before_the_rate_is_billed
    """
    order = validate_success(
        api.determine_coverage(cem_order["order_id"], coordinator_headers)
    )
    assert_coverage(
        order,
        allowed_amount_cents=63000,
        covered_amount_cents=48825,
        patient_responsibility_cents=14175,
    )
    assert order["covered_amount_cents"] != 46500, (
        "The admin fee is inside the amount the tier rate is applied to"
    )
