"""Means test calculation — PRD §3.3.

Verifies the six-month average, annualization, state-median lookup,
presumption boundary, disposable-income clamp, required_plan_months
selection, and minimum_plan_total computation.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    REQUIRED_PLAN_MONTHS_WITHOUT_PRESUMPTION,
    REQUIRED_PLAN_MONTHS_WITH_PRESUMPTION,
    assert_means_test_result,
    create_case,
    create_debtor,
    income_line,
    run_means_test,
    submit_all_other_schedules,
    submit_schedule_i,
    submit_schedule_j,
    setup_draft_case_filing_ready,
    validate_error,
    validate_success,
)


# ===========================================================================
# Six-month average and annualization — PRD §3.3
# ===========================================================================
class TestSixMonthAverage:
    """PRD §3.3: 'the system takes the income line items and sums the
    amount_cents over the most recent six months of those line items to
    obtain a raw six-month sum. The current_monthly_income_cents is the
    raw six-month sum divided by 6 and rounded half-up to the nearest
    whole cent — this is the only rounding step in the entire
    calculation. The cmi_annualized_cents is the
    current_monthly_income_cents multiplied by 12.'"""

    def test_six_equal_months_no_rounding(self, api):
        """PRD §3.3: "The current_monthly_income_cents is the raw
        six-month sum divided by 6 and rounded half-up to the nearest
        whole cent — this is the only rounding step in the entire
        calculation. The cmi_annualized_cents is the
        current_monthly_income_cents multiplied by 12."

        Claim: six equal monthly amounts produce CMI equal to the
        per-month amount and annualized = CMI * 12.
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            income_amounts_cents=[500_000] * 6,
            monthly_expenses_cents=100_000,
        )
        assert_means_test_result(mtr)
        assert mtr["current_monthly_income_cents"] == 500_000
        assert mtr["cmi_annualized_cents"] == 6_000_000

    def test_half_up_rounding_on_cmi_division(self, api):
        """# difficulty: combinatorial_formula/means_test_multistep_with_conditional_branch

        PRD §3.3: "The current_monthly_income_cents is the raw
        six-month sum divided by 6 and rounded half-up to the nearest
        whole cent — this is the only rounding step in the entire
        calculation. The cmi_annualized_cents is the
        current_monthly_income_cents multiplied by 12."

        Claim: with six months [500000, 500000, 500000, 500000,
        500000, 500005] (sum=3000005; 3000005/6=500000.833... ->
        round_half_up=500001; annualized=500001*12=6000012, NOT
        6000010 which is what you'd get by dividing after multiplying
        by 12). Ordering matters: round AT the division step, then
        multiply by 12.
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="CA", household_size=1,
            income_amounts_cents=[500_000, 500_000, 500_000,
                                  500_000, 500_000, 500_005],
            monthly_expenses_cents=350_000,
        )
        assert mtr["current_monthly_income_cents"] == 500_001
        assert mtr["cmi_annualized_cents"] == 6_000_012


# ===========================================================================
# State-median lookup — PRD §3.3
# ===========================================================================
class TestStateMedianLookup:
    """PRD §3.3: 'for California a single-person household has a median
    of 6,500,000 cents (sixty-five thousand dollars) and a two-person
    household 8,500,000 cents (eighty-five thousand dollars), for
    Texas a single-person household has a median of 6,000,000 cents
    (sixty thousand dollars) and a two-person household 8,000,000
    cents (eighty thousand dollars), and for any combination of
    state_code and household_size not enumerated the fallback is
    6,000,000 cents for a single-person household and 8,000,000 cents
    for a two-person household.'"""

    @pytest.mark.parametrize(
        "state,size,expected_median_cents",
        [
            ("CA", 1, 6_500_000),
            ("CA", 2, 8_500_000),
            ("TX", 1, 6_000_000),
            ("TX", 2, 8_000_000),
            # Unenumerated fallback — PRD §3.3 explicitly defines.
            ("NY", 1, 6_000_000),
            ("NY", 2, 8_000_000),
        ],
    )
    def test_state_median_table(self, api, state, size,
                                 expected_median_cents):
        """PRD §3.3: "for California a single-person household has a
        median of 6,500,000 cents (sixty-five thousand dollars) and a
        two-person household 8,500,000 cents (eighty-five thousand
        dollars), for Texas a single-person household has a median of
        6,000,000 cents (sixty thousand dollars) and a two-person
        household 8,000,000 cents (eighty thousand dollars), and for
        any combination of state_code and household_size not
        enumerated the fallback is 6,000,000 cents for a
        single-person household and 8,000,000 cents for a two-person
        household."

        Claim: state_median_annual_cents matches the PRD-pinned table.
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code=state, household_size=size,
            monthly_income_cents=200_000,
            monthly_expenses_cents=100_000,
        )
        assert mtr["state_median_annual_cents"] == expected_median_cents


# ===========================================================================
# Presumption-of-abuse boundary — PRD §3.3 (BOUNDARY)
# ===========================================================================
class TestPresumptionBoundary:
    """PRD §3.3: 'The presumption-of-abuse flag presumption_of_abuse is
    true exactly when cmi_annualized_cents is strictly greater than
    state_median_annual_cents — the boundary case where the two are
    equal evaluates to false.'"""

    def test_cmi_equals_median_presumption_false(self, api):
        """PRD §3.3: "The presumption-of-abuse flag presumption_of_abuse
        is true exactly when cmi_annualized_cents is strictly greater
        than state_median_annual_cents — the boundary case where the
        two are equal evaluates to false."

        Claim: at CMI annualized == state median (boundary),
        presumption_of_abuse=false.
        # difficulty: boundary_precision_check/presumption_of_abuse_strict_greater_than
        """
        # TX single-person median is 6,000,000. 500,000/month × 12 =
        # 6,000,000 — exact match.
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            income_amounts_cents=[500_000] * 6,
            monthly_expenses_cents=100_000,
        )
        assert mtr["state_median_annual_cents"] == 6_000_000
        assert mtr["cmi_annualized_cents"] == 6_000_000
        assert mtr["presumption_of_abuse"] is False

    def test_cmi_one_cent_above_median_presumption_true(self, api):
        """PRD §3.3: "The presumption-of-abuse flag presumption_of_abuse
        is true exactly when cmi_annualized_cents is strictly greater
        than state_median_annual_cents".

        Claim: CMI exactly one above median (boundary + 1) ->
        presumption_of_abuse=true.
        # difficulty: boundary_precision_check/presumption_of_abuse_strict_greater_than
        """
        # TX household=1 median 6,000,000. Need annualized = 6,000,012.
        # That's CMI 500,001 * 12. To get CMI=500,001 via round_half_up,
        # sum=3,000,001..3,000,008 (any sum > 3,000,000 with /6 result
        # rounding up).
        # Use 500001*6 = 3_000_006 -> CMI=500001 exact; annualized=6_000_012.
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            income_amounts_cents=[500_001] * 6,
            monthly_expenses_cents=100_000,
        )
        assert mtr["cmi_annualized_cents"] == 6_000_012
        assert mtr["state_median_annual_cents"] == 6_000_000
        assert mtr["presumption_of_abuse"] is True

    def test_cmi_one_cent_below_median_presumption_false(self, api):
        """PRD §3.3: "true exactly when cmi_annualized_cents is
        strictly greater than state_median_annual_cents".

        Claim: CMI strictly below median -> presumption_of_abuse=false.
        """
        # 499_999 * 12 = 5,999,988 below 6,000,000.
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            income_amounts_cents=[499_999] * 6,
            monthly_expenses_cents=100_000,
        )
        assert mtr["cmi_annualized_cents"] == 5_999_988
        assert mtr["presumption_of_abuse"] is False


# ===========================================================================
# Disposable income clamp — PRD §3.3
# ===========================================================================
class TestDisposableIncomeClamp:
    """PRD §3.3: 'The disposable_monthly_income_cents is then the
    larger of zero and the result of subtracting
    allowed_monthly_expenses_cents from current_monthly_income_cents —
    when expenses exceed income, the disposable figure is clamped to
    zero rather than allowed to go negative.'"""

    def test_disposable_positive(self, api):
        """PRD §3.3: "The disposable_monthly_income_cents is then the
        larger of zero and the result of subtracting
        allowed_monthly_expenses_cents from
        current_monthly_income_cents".

        Claim: income - expenses > 0 yields positive disposable.
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            monthly_income_cents=500_000,
            monthly_expenses_cents=300_000,
        )
        assert mtr["current_monthly_income_cents"] == 500_000
        assert mtr["allowed_monthly_expenses_cents"] == 300_000
        assert mtr["disposable_monthly_income_cents"] == 200_000

    def test_disposable_clamped_to_zero_when_expenses_exceed_income(self, api):
        """PRD §3.3: "when expenses exceed income, the disposable
        figure is clamped to zero rather than allowed to go negative."

        Claim: expenses > income -> disposable_monthly_income_cents=0.
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            monthly_income_cents=200_000,
            monthly_expenses_cents=900_000,
        )
        assert mtr["disposable_monthly_income_cents"] == 0


# ===========================================================================
# Required plan months & minimum plan total — PRD §3.3
# ===========================================================================
class TestPlanFloor:
    """PRD §3.3: 'The required_plan_months is 36 when
    presumption_of_abuse is false and 60 when presumption_of_abuse is
    true. The minimum_plan_total_cents is the product of
    disposable_monthly_income_cents and required_plan_months and
    represents the floor a Chapter 13 plan must clear at
    confirmation.'"""

    def test_required_months_36_when_presumption_false(self, api):
        """PRD §3.3: "The required_plan_months is 36 when
        presumption_of_abuse is false and 60 when presumption_of_abuse
        is true."

        Claim: presumption_of_abuse=false -> required_plan_months=36.
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            monthly_income_cents=300_000,  # well below median
            monthly_expenses_cents=100_000,
        )
        assert mtr["presumption_of_abuse"] is False
        assert mtr["required_plan_months"] == REQUIRED_PLAN_MONTHS_WITHOUT_PRESUMPTION
        assert mtr["required_plan_months"] == 36

    def test_required_months_60_when_presumption_true(self, api):
        """PRD §3.3: "The required_plan_months is 36 when
        presumption_of_abuse is false and 60 when presumption_of_abuse
        is true."

        Claim: presumption_of_abuse=true -> required_plan_months=60.
        """
        # TX household=1 median=6,000,000. Use CMI annualized=7,200,000
        # (600,000/month) — above median.
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            monthly_income_cents=600_000,
            monthly_expenses_cents=100_000,
        )
        assert mtr["presumption_of_abuse"] is True
        assert mtr["required_plan_months"] == REQUIRED_PLAN_MONTHS_WITH_PRESUMPTION
        assert mtr["required_plan_months"] == 60

    def test_minimum_plan_total_equals_disposable_times_months(self, api):
        """PRD §3.3: "The minimum_plan_total_cents is the product of
        disposable_monthly_income_cents and required_plan_months and
        represents the floor a Chapter 13 plan must clear at
        confirmation."

        Claim: minimum_plan_total_cents = disposable * required_months.
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            monthly_income_cents=300_000,
            monthly_expenses_cents=100_000,
        )
        # disposable=200_000, required=36, min_total=7_200_000
        assert mtr["disposable_monthly_income_cents"] == 200_000
        assert mtr["required_plan_months"] == 36
        assert mtr["minimum_plan_total_cents"] == 200_000 * 36


# ===========================================================================
# MeansTestResult lean shape — PRD §2.4
# ===========================================================================
class TestMeansTestResultShape:
    """PRD §2.4: 'MeansTestResult rows are immutable computation
    snapshots and likewise carry only id and created_at.'"""

    def test_means_test_result_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "MeansTestResult rows are immutable computation
        snapshots and likewise carry only id and created_at."

        Claim: MeansTestResult response omits version and updated_at.
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready()
        assert "version" not in mtr, (
            "PRD §2.4 says MeansTestResult has no version; "
            f"got {mtr.get('version')!r}"
        )
        assert "updated_at" not in mtr, (
            "PRD §2.4 says MeansTestResult has no updated_at; "
            f"got {mtr.get('updated_at')!r}"
        )
