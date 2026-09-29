"""Allocation-basis arithmetic: the dollar ratio, the base-unit ratio and the
three decayed presumptive pools."""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers.fixtures import build_priced_assessment, create_assessment
from test_helpers.test_users import FUND_ADMINISTRATOR_HEADERS
from test_helpers.types import AllocationMethod

# A rate profile that falls from 2000 to 500 cents per base unit, so the
# employer's share of plan-wide dollars and its share of plan-wide base units
# are deliberately different numbers.
DECLINING_RATE_HISTORY = (
    {
        "plan_year_start": 2021,
        "plan_year_end": 2021,
        "contribution_base_units": 20_000,
        "contribution_amount_cents": 40_000_000,
        "contribution_rate_cents_per_cbu": 2_000,
    },
    {
        "plan_year_start": 2022,
        "plan_year_end": 2022,
        "contribution_base_units": 30_000,
        "contribution_amount_cents": 30_000_000,
        "contribution_rate_cents_per_cbu": 1_000,
    },
    {
        "plan_year_start": 2023,
        "plan_year_end": 2023,
        "contribution_base_units": 40_000,
        "contribution_amount_cents": 20_000_000,
        "contribution_rate_cents_per_cbu": 500,
    },
    {
        "plan_year_start": 2024,
        "plan_year_end": 2024,
        "contribution_base_units": 50_000,
        "contribution_amount_cents": 25_000_000,
        "contribution_rate_cents_per_cbu": 500,
    },
    {
        "plan_year_start": 2025,
        "plan_year_end": 2025,
        "contribution_base_units": 60_000,
        "contribution_amount_cents": 30_000_000,
        "contribution_rate_cents_per_cbu": 500,
    },
)


def _declining_rate_scenario(api):
    """A determined complete withdrawal priced under MODIFIED_PRESUMPTIVE."""
    return build_priced_assessment(
        api,
        plan_overrides={"allocation_method": AllocationMethod.MODIFIED_PRESUMPTIVE.value},
        employer_overrides={"obligation_start_year": 2021, "cba_count": 1},
        contribution_entries=DECLINING_RATE_HISTORY,
    )


def _presumptive_scenario(api):
    """A PRESUMPTIVE plan whose three annual pools are sized to expose rounding order."""
    return build_priced_assessment(
        api,
        plan_overrides={"allocation_method": AllocationMethod.PRESUMPTIVE.value},
        employer_overrides={"obligation_start_year": 2021, "cba_count": 1},
        valuation_overrides={
            "uvb_total_cents": 20_000_000_000,
            "uvb_pool_cents": 1_000_000_000,
            "all_employer_contributions_cents": 3_000_000_000,
            "all_employer_cbu": 3_000_000,
        },
        per_year_valuation_overrides={
            2023: {"uvb_pool_cents": 1_200_000_012},
            2024: {"uvb_pool_cents": 1_200_000_012},
            2025: {"uvb_pool_cents": 1_200_000_011},
        },
        contribution_entries=[
            {
                "plan_year_start": 2021,
                "plan_year_end": 2025,
                "contribution_base_units": 1_500_000,
                "contribution_amount_cents": 500_000_000,
                "contribution_rate_cents_per_cbu": 1_000,
            }
        ],
        withdrawal_overrides={"cessation_date": "2026-04-01T00:00:00Z"},
    )


class TestAllocationBasisDivergence:
    def test_modified_presumptive_allocates_on_the_contribution_dollar_ratio(self, api):
        """The dollar-basis ratio 145000000/10000000000 against a 10000000000-cent anchor
        pool allocates 145000000 cents, and the pool breakdown stays empty.

        PRD 3.5: "Under `MODIFIED_PRESUMPTIVE`, the server sums the employer's
        contribution dollars over the five plan years from five years before the
        withdrawal plan year through the year immediately preceding it, sums the
        plan-wide contribution dollars over the same five years, and multiplies the
        anchor valuation's `uvb_total_cents` by the first sum divided by the second."

        Design: Difficulty/dual_variant_calc/allocation_method_dollar_basis_versus_cbu_basis_divergence
        """
        scenario = _declining_rate_scenario(api)
        assessment = scenario["assessment"]

        assert assessment["allocation_method_applied"] == "MODIFIED_PRESUMPTIVE"
        assert assessment["gross_allocated_cents"] == 145_000_000
        assert assessment["de_minimis_reduction_cents"] == 0
        assert assessment["net_assessed_cents"] == 145_000_000
        assert assessment["pool_term_breakdown"] == []
        assert assessment["valuation_id"] == scenario["valuations"][2025]["id"]

    def test_rolling_five_allocates_on_the_base_unit_ratio_of_the_same_history(self, api):
        """The identical certified history reallocated on base units yields 200000000
        cents, 55000000 more than the dollar basis produced.

        PRD 3.5: "Under `ROLLING_5`, the arithmetic is structurally identical to
        `MODIFIED_PRESUMPTIVE` and uses the same single pool — the anchor valuation's
        `uvb_total_cents` — and the same five-year window, but the ratio is built from
        **contribution base units** rather than dollars: the employer's base units over
        the five years divided by the plan-wide base units over the same five years."

        Design: Difficulty/dual_variant_calc/allocation_method_dollar_basis_versus_cbu_basis_divergence
        """
        scenario = _declining_rate_scenario(api)
        dollar_basis = scenario["assessment"]

        validate_success(
            api.update_plan(
                scenario["plan"]["id"],
                {"allocation_method": AllocationMethod.ROLLING_5.value},
                FUND_ADMINISTRATOR_HEADERS,
            ),
            200,
        )
        base_unit_basis = create_assessment(api, scenario["event"]["id"])

        assert base_unit_basis["allocation_method_applied"] == "ROLLING_5"
        assert base_unit_basis["gross_allocated_cents"] == 200_000_000
        assert base_unit_basis["net_assessed_cents"] == 200_000_000
        assert (
            base_unit_basis["gross_allocated_cents"] - dollar_basis["gross_allocated_cents"]
            == 55_000_000
        )

    def test_level_annual_payment_is_identical_under_both_allocation_bases(self, api):
        """The quarterly cheque comes from contribution history alone, so both bases
        report 100000000 cents with the same tie-break audit fields.

        PRD 3.5: "**The level annual payment** is derived purely from contribution
        history and never from the assessed amount, which is why a large reduction on
        review does not lengthen or shorten the quarterly cheque."

        Design: Difficulty/dual_variant_calc/allocation_method_dollar_basis_versus_cbu_basis_divergence
        """
        scenario = _declining_rate_scenario(api)
        dollar_basis = scenario["assessment"]

        assert dollar_basis["annual_payment_cents"] == 100_000_000
        assert dollar_basis["high_3yr_window_start_year"] == 2023
        assert dollar_basis["peak_rate_plan_year"] == 2021

        validate_success(
            api.update_plan(
                scenario["plan"]["id"],
                {"allocation_method": AllocationMethod.ROLLING_5.value},
                FUND_ADMINISTRATOR_HEADERS,
            ),
            200,
        )
        base_unit_basis = create_assessment(api, scenario["event"]["id"])

        assert base_unit_basis["annual_payment_cents"] == 100_000_000


class TestPresumptivePoolRounding:
    def test_each_pool_term_is_rounded_before_the_three_are_added(self, api):
        """Rounding each of 36000000.36, 38000000.38 and 40000000.3666 first gives
        114000000; summing them unrounded and rounding once would give 114000001.

        PRD 3.5: "The rounding order is pinned: each pool term is rounded to whole
        cents **first** and the rounded terms are then added. Summing the three
        unrounded terms and rounding once is a different answer and is wrong."

        Design: Difficulty/combinatorial_formula/presumptive_pool_terms_rounded_before_summing_mode_b
        """
        scenario = _presumptive_scenario(api)
        assessment = scenario["assessment"]
        breakdown = assessment["pool_term_breakdown"]

        assert assessment["allocation_method_applied"] == "PRESUMPTIVE"
        assert assessment["gross_allocated_cents"] == 114_000_000
        assert assessment["gross_allocated_cents"] != 114_000_001
        assert sum(element["term_cents"] for element in breakdown) == 114_000_000
        assert assessment["de_minimis_reduction_cents"] == 0
        assert assessment["net_assessed_cents"] == 114_000_000
        assert assessment["annual_payment_cents"] == 300_000_000

    def test_pool_breakdown_carries_three_ascending_years_with_their_decay_factors(self, api):
        """The three annual pools appear in ascending plan-year order decaying 0.90,
        0.95 and 1.00, each with its own rounded term.

        PRD 3.5: "It computes a decay factor as one minus five hundredths of the number of
        years by which that pool year precedes the year immediately before the withdrawal
        plan year, floored at zero — so the most recent pool year decays not at all, the
        year before it decays to 0.95, and the year before that to 0.90."

        Design: Difficulty/combinatorial_formula/presumptive_pool_terms_rounded_before_summing_mode_b
        """
        scenario = _presumptive_scenario(api)
        breakdown = scenario["assessment"]["pool_term_breakdown"]

        assert len(breakdown) == 3
        expected = (
            (2023, 0.90, 36_000_000),
            (2024, 0.95, 38_000_000),
            (2025, 1.00, 40_000_000),
        )
        for element, (plan_year, decay_factor, term_cents) in zip(breakdown, expected):
            assert element["plan_year"] == plan_year
            assert element["decay_factor"] == pytest.approx(decay_factor, abs=0.0001)
            assert element["term_cents"] == term_cents
            # Every pool year here carries the same three-year rolling dollar ratio of
            # one thirtieth, recorded to ten decimal places.
            assert element["ratio"] == pytest.approx(1 / 30, abs=0.0000000001)
            assert round(element["ratio"], 10) == element["ratio"]
