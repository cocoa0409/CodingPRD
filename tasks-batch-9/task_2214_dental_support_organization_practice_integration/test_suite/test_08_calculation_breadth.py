"""Calculation breadth: the qualifying set behind consolidation leakage, the
half-up rounding of the chart error rate, the unequal quality weights at the
sample floor, the pinned posture precedence and the two roll-ups whose empty
and terminal cases are easy to get wrong."""

import pytest

from test_helpers import (
    LEAD,
    assert_batch_record_ledger,
    assert_clinical_quality_review,
    assert_practice,
    assert_vendor_consolidation,
    build_clinical_director,
    build_closed_deal,
    build_scheduled_batch,
    close_quality_review,
    create_clinical_quality_review,
    create_payer_contract,
    create_payer_enrollment,
    create_supply_preference_exception,
    create_vendor_consolidation,
    decide_supply_exception,
    finalize_consolidation,
    read_affiliation,
    read_conversion_vendor,
    read_employment,
    read_migration_batch,
    read_payer_contract,
    read_payer_enrollment,
    read_practice,
    read_supply_preference_exception,
    reconcile_batch,
    separate_employment,
    set_clock,
    stage_batch,
    schedule_batch,
    submit_enrollment,
    validate_batch,
    validate_success,
)

WINDOW = ("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")
ENROLLMENT_EFFECTIVE = "2027-02-13T00:00:00Z"

APPROVED_SUPPLY_EXCEPTION = {
    "vendor_category": "SUPPLY",
    "item_code": "IMP-4110",
    "annual_qty": 340,
    "formulary_unit_cents": 1275,
    "preferred_unit_cents": 1899,
    "clinical_rationale": "titanium implant platform matched to existing prosthetic library",
}
REQUESTED_SUPPLY_EXCEPTION = {
    "vendor_category": "SUPPLY",
    "item_code": "BUR-2201",
    "annual_qty": 100,
    "formulary_unit_cents": 1000,
    "preferred_unit_cents": 1500,
    "clinical_rationale": "preferred bur geometry",
}
APPROVED_LAB_EXCEPTION = {
    "vendor_category": "LAB",
    "item_code": "LAB-CROWN-9",
    "annual_qty": 200,
    "formulary_unit_cents": 500,
    "preferred_unit_cents": 900,
    "clinical_rationale": "incumbent ceramist shade matching",
}


@pytest.fixture
def consolidation_with_three_exceptions():
    """One SUPPLY plan facing an approved, a pending and an off-category exception."""
    ctx = build_closed_deal()
    director, _ = build_clinical_director()
    ctx["director_id"] = director["id"]
    ctx["plan"] = create_vendor_consolidation(
        ctx["practice_id"],
        vendor_category="SUPPLY",
        baseline_annual_spend_cents=4_800_000,
        formulary_annual_spend_cents=3_900_000,
    )
    approved = create_supply_preference_exception(
        ctx["employment_id"], ctx["doctor_id"], **APPROVED_SUPPLY_EXCEPTION
    )
    ctx["approved_supply"] = decide_supply_exception(
        approved["id"], "APPROVE", director["id"], decision_note="clinically justified"
    )
    ctx["pending_supply"] = create_supply_preference_exception(
        ctx["employment_id"], ctx["doctor_id"], **REQUESTED_SUPPLY_EXCEPTION
    )
    off_category = create_supply_preference_exception(
        ctx["employment_id"], ctx["doctor_id"], **APPROVED_LAB_EXCEPTION
    )
    ctx["approved_lab"] = decide_supply_exception(
        off_category["id"], "APPROVE", director["id"]
    )
    return ctx


def test_only_the_approved_same_category_exception_leaks(
    consolidation_with_three_exceptions
):
    """PRD §3.7: "An exception qualifies only when its status is `APPROVED`, only when its employment sits at the same practice as the consolidation, and only when its `vendor_category` matches the consolidation's; `REQUESTED` and `DENIED` exceptions contribute nothing, and an approved exception in the other category or at another practice is excluded."
    PRD §3.7: "First, gross savings: the difference between `baseline_annual_spend_cents` and `formulary_annual_spend_cents` is multiplied by the realization factor of 8,500 basis points — eighty-five percent, since not every modelled saving is actually captured — divided by ten thousand and rounded half up to whole cents, and stored as `gross_savings_cents`."

    Design: Corner/calculations/vendor_savings_counts_only_approved_same_category_exceptions
    """
    ctx = consolidation_with_three_exceptions
    finalized = finalize_consolidation(ctx["plan"]["id"])

    assert_vendor_consolidation(finalized)
    assert finalized["status"] == "FINALIZED"
    assert finalized["gross_savings_cents"] == 765_000
    assert finalized["exception_leakage_cents"] == 212_160
    assert finalized["exception_count_applied"] == 1
    assert finalized["projected_savings_cents"] == 552_840

    assert ctx["approved_supply"]["status"] == "APPROVED"
    assert ctx["approved_supply"]["incremental_cost_cents"] == 212_160

    pending = read_supply_preference_exception(ctx["pending_supply"]["id"])
    assert pending["status"] == "REQUESTED"
    assert pending["incremental_cost_cents"] is None

    lab = read_supply_preference_exception(ctx["approved_lab"]["id"])
    assert lab["status"] == "APPROVED"
    assert lab["incremental_cost_cents"] == 80_000
    assert lab["vendor_category"] == "LAB"


def test_an_exact_half_basis_point_error_rate_rounds_up():
    """PRD §3.5: "The rate is then `validation_error_rate_bps`, computed as `quarantined_count` multiplied by ten thousand and divided by `records_total`, rounded half up to whole basis points."
    PRD §3.5: "Tolerance is two percent, that is 200 basis points: a rate exactly equal to 200 validates, and 201 quarantines the entire batch."

    Design: Corner/calculations/chart_validation_error_rate_rounds_half_up
    """
    ctx = build_closed_deal(practice={"charts_total_expected": 8000})
    batch = build_scheduled_batch(
        ctx["practice_id"], *WINDOW, batch_label="CHART-WAVE-1", records_total=8000
    )
    set_clock(WINDOW[0])
    validated = validate_batch(batch["id"], 2)

    assert validated["validation_error_rate_bps"] == 3
    assert validated["status"] == "VALIDATED"
    assert validated["records_validated"] == 7998
    assert validated["records_quarantined"] == 2
    assert validated["records_pending"] == 0
    assert_batch_record_ledger(validated)

    practice = read_practice(ctx["practice_id"])
    assert practice["charts_migrated_count"] == 7998
    assert practice["integration_posture"] == "STABILIZING"
    assert read_conversion_vendor(ctx["vendor_id"])["active_window_count"] == 0


def test_equal_rates_carry_unequal_weight_at_the_sample_floor():
    """PRD §3.8: "The finding penalty is `finding_rate_bps` multiplied by the finding weight of 6,000 basis points — sixty percent of the total penalty weight — divided by ten thousand and rounded half up."
    PRD §3.8: "The sample must clear a statistical floor of 20 charts, where exactly 20 is acceptable and 19 is refused with `ERR_SAMPLE_SIZE_TOO_SMALL`, and neither `charts_with_findings` nor `treatment_plan_overrides` may exceed `charts_sampled`, a violation of which is a payload failure reported as `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/quality_score_applies_declared_weights_at_minimum_sample
    """
    ctx = build_closed_deal()
    director, _ = build_clinical_director()

    review = create_clinical_quality_review(
        ctx["employment_id"],
        director["id"],
        period_label="QR-2026-Q4",
        charts_sampled=20,
        charts_with_findings=5,
        treatment_plan_overrides=5,
    )
    assert_clinical_quality_review(review)
    assert review["charts_sampled"] == 20
    assert review["finding_rate_bps"] == 2500
    assert review["override_rate_bps"] == 2500
    assert review["score_bps"] == 7500
    assert review["status"] == "OPEN"

    closed = validate_success(
        close_quality_review(
            review["id"],
            "ESCALATED",
            director["id"],
            outcome_note="override pattern requires oversight",
        )
    )
    assert closed["status"] == "ESCALATED"
    assert closed["closed_by_doctor_id"] == director["id"]
    assert closed["score_bps"] == 7500


def test_the_freeze_clause_outranks_the_quarantine_clause():
    """PRD §2.6: "Clause two dominates clauses three and four: a practice with no active doctor is `FROZEN` even when it simultaneously holds quarantined batches and denied enrollments."
    PRD §2.6: "Alongside the posture, the boolean `clinical_coverage_gap` is set to true exactly when the derived posture is `FROZEN`, and to false otherwise."

    Design: Corner/calculations/posture_frozen_clause_dominates_quarantine_clause
    """
    ctx = build_closed_deal()
    batch = build_scheduled_batch(
        ctx["practice_id"], *WINDOW, batch_label="CHART-WAVE-1", records_total=5000
    )
    set_clock(WINDOW[0])
    quarantined = validate_batch(batch["id"], 300)
    assert quarantined["validation_error_rate_bps"] == 600
    assert quarantined["status"] == "QUARANTINED"

    before = read_practice(ctx["practice_id"])
    assert before["quarantined_batch_count"] == 1
    assert before["integration_posture"] == "RESTRICTED"

    separate_employment(ctx["employment_id"])

    after = read_practice(ctx["practice_id"])
    assert_practice(after)
    assert after["active_doctor_count"] == 0
    assert after["integration_posture"] == "FROZEN"
    assert after["quarantined_batch_count"] == 1
    assert after["charts_migrated_count"] == 0
    assert after["clinical_coverage_gap"] is True

    affiliation = read_affiliation(ctx["affiliation_id"])
    assert affiliation["earnout_measurement_state"] == "SUSPENDED"


def test_the_rollup_is_pending_for_an_empty_set_and_again_for_a_suspended_one():
    """PRD §3.4: "The precedence ladder is: if the employment has no enrollments at all, the rollup is `PENDING`; otherwise, if any one enrollment is `DENIED`, the rollup is `DENIED`; otherwise, if every enrollment is `APPROVED`, the rollup is `APPROVED`; otherwise, if any enrollment is `SUBMITTED`, the rollup is `SUBMITTED`; otherwise the rollup is `PENDING`."
    PRD §3.4: "A `SUSPENDED` enrollment counts as neither approved nor submitted, so freezing a practice pulls the rollup back to `PENDING`."

    Design: Corner/calculations/credentialing_rollup_pending_for_empty_and_suspended_sets
    """
    ctx = build_closed_deal()
    assert read_employment(ctx["employment_id"])["credentialing_status"] == "PENDING"

    contract = create_payer_contract(ctx["practice_id"])
    enrollment = create_payer_enrollment(
        contract["id"], ctx["employment_id"], ENROLLMENT_EFFECTIVE
    )
    submit_enrollment(enrollment["id"])
    assert read_employment(ctx["employment_id"])["credentialing_status"] == "SUBMITTED"
    assert read_practice(ctx["practice_id"])["pending_credentialing_count"] == 1

    separate_employment(ctx["employment_id"])

    assert read_payer_enrollment(enrollment["id"])["status"] == "SUSPENDED"
    employment = read_employment(ctx["employment_id"])
    assert employment["credentialing_status"] == "PENDING"
    assert employment["employment_status"] == "SEPARATED"

    practice = read_practice(ctx["practice_id"])
    assert practice["pending_credentialing_count"] == 0
    reread_contract = read_payer_contract(contract["id"])
    assert reread_contract["enrollment_open_count"] == 0
    assert reread_contract["transition_state"] == "LEGACY"


def test_a_staged_batch_contributes_nothing_and_a_reconciled_one_still_counts():
    """PRD §2.8: "The practice-level invariant is that `charts_migrated_count` equals the sum of `records_validated` over that practice's batches whose status is `VALIDATED` or `RECONCILED`."
    PRD §3.5: "The batch moves `VALIDATED → RECONCILED`, its `version` increments by one, and the practice's `charts_migrated_count` keeps counting that batch's `records_validated`, since reconciled batches remain inside the practice-level roll-up."

    Design: Corner/calculations/chart_ledger_keeps_reconciled_batches_in_the_rollup
    """
    ctx = build_closed_deal()
    staged = stage_batch(
        ctx["practice_id"], batch_label="CHART-WAVE-1", records_total=5000
    )
    assert staged["records_pending"] == 5000
    assert staged["records_validated"] == 0
    assert staged["records_quarantined"] == 0
    assert_batch_record_ledger(staged)
    assert read_practice(ctx["practice_id"])["charts_migrated_count"] == 0

    schedule_batch(staged["id"], *WINDOW)
    set_clock(WINDOW[0])
    validated = validate_batch(staged["id"], 100)
    assert validated["status"] == "VALIDATED"
    assert validated["records_validated"] == 4900
    assert validated["records_quarantined"] == 100
    assert validated["records_pending"] == 0
    assert_batch_record_ledger(validated)
    assert read_practice(ctx["practice_id"])["charts_migrated_count"] == 4900

    reconciled = reconcile_batch(staged["id"])
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["records_validated"] == 4900
    assert read_migration_batch(staged["id"])["status"] == "RECONCILED"

    practice = read_practice(ctx["practice_id"], LEAD)
    assert practice["charts_migrated_count"] == 4900
    assert practice["integration_posture"] == "STABILIZING"
    assert practice["quarantined_batch_count"] == 0
