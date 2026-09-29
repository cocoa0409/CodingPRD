"""Rounding-discipline depth: the two compensation variants, the per-line
rounding boundary on a fee-schedule transition, and the weighted quality score
at its escalation threshold."""

import pytest

from test_helpers import (
    FINANCE,
    ApiErrorId,
    api_client,
    build_clinical_director,
    build_closed_deal,
    build_closed_deal_two_doctors,
    build_priced_contract,
    close_quality_review,
    create_clinical_quality_review,
    harmonize_compensation,
    monthly_collections_series,
    read_quality_review,
    validate_error,
    validate_paginated,
    validate_success,
)

SIX_WEAK_SIX_STRONG = [5_000_000] * 6 + [7_500_000] * 6

FEE_LINES = [
    {
        "procedure_code": "D0120",
        "legacy_allowed_cents": 5503,
        "dso_allowed_cents": 4900,
        "annual_volume": 1210,
    },
    {
        "procedure_code": "D2740",
        "legacy_allowed_cents": 108_000,
        "dso_allowed_cents": 99_503,
        "annual_volume": 130,
    },
    {
        "procedure_code": "D4341",
        "legacy_allowed_cents": 21_000,
        "dso_allowed_cents": 22_750,
        "annual_volume": 380,
    },
]


@pytest.fixture
def two_comp_models():
    """One practice, two active doctors, one on each compensation variant."""
    return build_closed_deal_two_doctors(
        second_doctor={
            "full_name": "Beto Alvarez",
            "npi": "1710000002",
            "license_number": "IL-DDS-5521",
            "license_state": "IL",
        },
        second_employment={"comp_model": "ANNUAL_TRUE_UP"},
        accept_second=True,
    )


def test_monthly_min_guarantee_tops_up_every_month_below_the_floor(two_comp_models):
    """PRD §3.4: "For each of the twelve months in turn, the doctor's percentage share for that month is the month's collections multiplied by `collections_pct_bps` and divided by ten thousand, rounded half up to whole cents; that month's pay is the greater of `base_salary_monthly_cents` and that rounded share; and `harmonized_annual_comp_cents` is the sum of the twelve monthly pay figures."

    Design: Difficulty/dual_variant_calc/doctor_comp_monthly_guarantee_vs_annual_true_up
    """
    harmonized = harmonize_compensation(
        two_comp_models["employment_id"],
        monthly_collections_series(*SIX_WEAK_SIX_STRONG),
    )
    assert harmonized["comp_model"] == "MONTHLY_MIN_GUARANTEE"
    assert harmonized["harmonized_annual_comp_cents"] == 24_300_000
    assert harmonized["harmonization_delta_cents"] == 300_000
    assert harmonized["is_harmonized"] is True


def test_annual_true_up_lets_strong_months_absorb_the_weak_ones(two_comp_models):
    """PRD §3.4: "The twelve monthly collections are summed first, exactly and without rounding; the doctor's percentage share is that annual total multiplied by `collections_pct_bps` and divided by ten thousand, rounded half up to whole cents exactly once; and `harmonized_annual_comp_cents` is the greater of that single rounded share and `base_salary_monthly_cents` multiplied by twelve."

    Design: Difficulty/dual_variant_calc/doctor_comp_monthly_guarantee_vs_annual_true_up
    """
    harmonized = harmonize_compensation(
        two_comp_models["second_employment_id"],
        monthly_collections_series(*SIX_WEAK_SIX_STRONG),
    )
    assert harmonized["comp_model"] == "ANNUAL_TRUE_UP"
    assert harmonized["harmonized_annual_comp_cents"] == 22_500_000
    assert harmonized["harmonization_delta_cents"] == -1_500_000
    assert harmonized["is_harmonized"] is True


def test_monthly_variant_pays_strictly_more_than_the_annual_variant(two_comp_models):
    """PRD §3.4: "The monthly variant is therefore always greater than or equal to the annual variant on identical inputs, and strictly greater whenever any month falls below the guarantee while the annual percentage still clears twelve times the base."
    PRD §3.4: "Both contractual variants consume that identical series together with the identical `base_salary_monthly_cents` and `collections_pct_bps`, and they generally disagree because they aggregate at different granularities."

    Design: Difficulty/dual_variant_calc/doctor_comp_monthly_guarantee_vs_annual_true_up
    """
    series = monthly_collections_series(*SIX_WEAK_SIX_STRONG)
    monthly = harmonize_compensation(two_comp_models["employment_id"], series)
    annual = harmonize_compensation(two_comp_models["second_employment_id"], series)

    assert (
        monthly["base_salary_monthly_cents"] == annual["base_salary_monthly_cents"]
    ), "the two rows carry the identical guarantee"
    assert monthly["collections_pct_bps"] == annual["collections_pct_bps"]
    assert (
        monthly["harmonized_annual_comp_cents"]
        > annual["harmonized_annual_comp_cents"]
    )
    assert (
        monthly["harmonized_annual_comp_cents"]
        - annual["harmonized_annual_comp_cents"]
        == 1_800_000
    )


def test_each_priced_line_is_rounded_before_the_contract_sums_them():
    """PRD §3.6: "That raw figure is rounded half up to whole cents and stored as that line's `line_impact_cents`."
    PRD §3.6: "each line's raw impact is the difference between its `dso_allowed_cents` and its `legacy_allowed_cents`, multiplied by its `annual_volume`, multiplied by the utilization blend factor of 6,500 basis points — sixty-five percent — and divided by ten thousand."

    Design: Difficulty/combinatorial_formula/fee_schedule_round_per_line_then_sum
    """
    ctx = build_closed_deal()
    contract = build_priced_contract(ctx["practice_id"], lines=FEE_LINES)

    lines, meta = validate_paginated(
        api_client.list_fee_schedule_items(contract["id"], FINANCE)
    )
    by_code = {line["procedure_code"]: line for line in lines}
    assert by_code["D0120"]["line_impact_cents"] == -474_260
    assert by_code["D2740"]["line_impact_cents"] == -717_997
    assert by_code["D4341"]["line_impact_cents"] == 432_250
    assert meta["total_count"] == 3


def test_contract_impact_is_the_plain_sum_of_the_stored_line_figures():
    """PRD §3.6: "The contract's `blended_impact_cents` is then the plain sum of the stored line figures, with no further rounding at the contract level."
    PRD §3.6: "Each line's own `line_impact_cents` is stored on the line, and the contract's `blended_impact_cents` is recomputed and the contract's `version` incremented, alongside `fee_schedule_item_count`."

    Design: Difficulty/combinatorial_formula/fee_schedule_round_per_line_then_sum
    """
    ctx = build_closed_deal()
    contract = build_priced_contract(ctx["practice_id"], lines=FEE_LINES)

    assert contract["fee_schedule_item_count"] == 3
    assert contract["blended_impact_cents"] == -760_007


def test_rounding_the_raw_sum_once_produces_a_different_contract_figure():
    """PRD §3.6: "The order of operations is pinned: round each line, then sum."
    PRD §3.6: "Summing raw values and rounding once at the end produces a different number whenever two or more lines carry a fractional half of the same sign, and the contract figure is required to reconcile exactly with the persisted line figures."

    Design: Difficulty/combinatorial_formula/fee_schedule_round_per_line_then_sum
    """
    ctx = build_closed_deal()
    contract = build_priced_contract(ctx["practice_id"], lines=FEE_LINES)

    assert contract["blended_impact_cents"] == -760_007
    assert contract["blended_impact_cents"] != -760_006, (
        "rounding the summed raw impacts once would yield -760006"
    )


def test_score_at_exactly_the_escalation_threshold_closes_with_a_plan():
    """PRD §3.8: "`CLOSED_WITH_PLAN` is permitted only when `score_bps` is at least the escalation threshold of 8,000 basis points, so a score of exactly 8,000 may close with a corrective plan while 7,999 may not."

    Design: Difficulty/boundary_precision_check/clinical_quality_score_at_escalation_threshold
    """
    ctx = build_closed_deal()
    director, _ = build_clinical_director()

    review = create_clinical_quality_review(
        ctx["employment_id"],
        director["id"],
        period_label="QR-2026-Q4-A",
        charts_sampled=21,
        charts_with_findings=3,
        treatment_plan_overrides=6,
    )
    assert review["finding_rate_bps"] == 1429
    assert review["override_rate_bps"] == 2857
    assert review["score_bps"] == 8000

    closed = validate_success(
        close_quality_review(
            review["id"],
            "CLOSED_WITH_PLAN",
            director["id"],
            outcome_note="documentation coaching plan agreed",
        )
    )
    assert closed["status"] == "CLOSED_WITH_PLAN"
    assert closed["closed_by_doctor_id"] == director["id"]


def test_score_one_basis_point_short_refuses_a_corrective_plan():
    """PRD §3.8: "An outcome inconsistent with the score is refused with `ERR_QUALITY_OUTCOME_MISMATCH`."
    PRD §3.8: "`CLOSED_WITH_PLAN` is permitted only when `score_bps` is at least the escalation threshold of 8,000 basis points, so a score of exactly 8,000 may close with a corrective plan while 7,999 may not."

    Design: Difficulty/boundary_precision_check/clinical_quality_score_at_escalation_threshold
    """
    ctx = build_closed_deal()
    director, _ = build_clinical_director()

    review = create_clinical_quality_review(
        ctx["employment_id"],
        director["id"],
        period_label="QR-2026-Q4-B",
        charts_sampled=21,
        charts_with_findings=5,
        treatment_plan_overrides=3,
    )
    assert review["finding_rate_bps"] == 2381
    assert review["override_rate_bps"] == 1429
    assert review["score_bps"] == 7999

    validate_error(
        close_quality_review(review["id"], "CLOSED_WITH_PLAN", director["id"]),
        ApiErrorId.ERR_QUALITY_OUTCOME_MISMATCH.value,
    )
    still_open = read_quality_review(review["id"], director["id"])
    assert still_open["status"] == "OPEN"


def test_escalation_is_always_available_below_the_threshold():
    """PRD §3.8: "`ESCALATED` is always permitted, and it is mandatory whenever `score_bps` falls below 8,000."
    PRD §3.8: "The score is stamped at creation and re-stamped when the review is closed, and it is built from four independent roundings rather than one combined expression."

    Design: Difficulty/boundary_precision_check/clinical_quality_score_at_escalation_threshold
    """
    ctx = build_closed_deal()
    director, _ = build_clinical_director()

    review = create_clinical_quality_review(
        ctx["employment_id"],
        director["id"],
        period_label="QR-2026-Q4-B",
        charts_sampled=21,
        charts_with_findings=5,
        treatment_plan_overrides=3,
    )
    escalated = validate_success(
        close_quality_review(review["id"], "ESCALATED", director["id"])
    )
    assert escalated["status"] == "ESCALATED"
    assert escalated["score_bps"] == 7999
    assert escalated["score_bps"] < 8000
