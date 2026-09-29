"""The twenty-year cap: its pinned evaluation order, and the mass-withdrawal
variant that has no cap to forgive a shortfall with."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    build_issued_assessment,
    build_priced_assessment,
    get_assessment,
    get_schedule,
    latest_schedule,
    list_all_installments,
)
from test_helpers.test_users import FUND_ADMINISTRATOR_HEADERS, PLAN_ACTUARY_HEADERS
from test_helpers.types import PaymentScheduleSource

# All of the employer's dollars land in 2021 at a rate of 5000 cents per base
# unit, which makes the allocated basis enormous relative to the level annual
# payment the same history supports.
FRONT_LOADED_HISTORY = (
    {
        "plan_year_start": 2021,
        "plan_year_end": 2021,
        "contribution_base_units": 200_000,
        "contribution_amount_cents": 1_000_000_000,
        "contribution_rate_cents_per_cbu": 5_000,
    },
    {
        "plan_year_start": 2022,
        "plan_year_end": 2025,
        "contribution_base_units": 4_000,
        "contribution_amount_cents": 2_000_000,
        "contribution_rate_cents_per_cbu": 500,
    },
)

LARGE_POOL_VALUATION = {
    "uvb_total_cents": 100_000_000_000,
    "uvb_pool_cents": 10_000_000_000,
    "all_employer_contributions_cents": 2_000_000_000,
    "all_employer_cbu": 2_000_000,
}

UNAMORTIZABLE_BASIS_CENTS = 10_020_000_000
FORGIVEN_BY_CAP_CENTS = 6_453_348_534
CAPPED_BASIS_CENTS = 3_566_651_466
HISTORY_DERIVED_ANNUAL_PAYMENT_CENTS = 336_666_667


def _capped_scenario(api, cessation_date, reported_cause=None, issue=True):
    withdrawal_overrides = {"cessation_date": cessation_date}
    if reported_cause is not None:
        withdrawal_overrides["reported_cause"] = reported_cause
    builder = build_issued_assessment if issue else build_priced_assessment
    return builder(
        api,
        plan_overrides={"industry": "TRUCKING", "mass_withdrawal_declared": False},
        employer_overrides={"obligation_start_year": 2021, "cba_count": 1},
        valuation_overrides=dict(LARGE_POOL_VALUATION),
        contribution_entries=FRONT_LOADED_HISTORY,
        withdrawal_overrides=withdrawal_overrides,
    )


class TestAmortizationCapVariants:
    def test_capped_variant_forgives_the_shortfall_the_annuity_cannot_reach(self, api):
        """With the twenty-year ceiling in force an unreachable basis amortises over
        exactly twenty years and the shortfall of 6453348534 cents is extinguished.

        PRD 3.6: "Otherwise — whether because the required term exceeds twenty or because
        no term in the search range sufficed — `amortization_years` is exactly 20 and
        `forgiven_by_cap_cents` is `amortization_basis_cents` less the annuity present
        value over twenty years rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/amortization_cap_variant_capped_forgiveness_versus_mass_withdrawal_rejection
        """
        scenario = _capped_scenario(api, "2026-05-15T00:00:00Z")
        schedule = scenario["schedule"]

        assert schedule["amortization_basis_cents"] == UNAMORTIZABLE_BASIS_CENTS
        assert schedule["amortization_years"] == 20
        assert schedule["forgiven_by_cap_cents"] == FORGIVEN_BY_CAP_CENTS
        assert schedule["capped_basis_cents"] == CAPPED_BASIS_CENTS
        assert schedule["installment_count"] == 80
        assert schedule["quarterly_installment_cents"] == 44_583_143
        assert schedule["final_installment_cents"] == 44_583_169

    def test_mass_withdrawal_variant_refuses_the_same_unreachable_basis(self, api):
        """Declaring a mass withdrawal disapplies the ceiling, so the identical basis
        and identical annual payment are rejected outright instead of being forgiven.

        PRD 3.6: "If no required term was found in step one the request is rejected with
        `ERR_UNAMORTIZABLE_ASSESSMENT`, because there is no cap available to forgive the
        shortfall."

        Design: Difficulty/dual_variant_calc/amortization_cap_variant_capped_forgiveness_versus_mass_withdrawal_rejection
        """
        scenario = _capped_scenario(api, "2026-05-15T00:00:00Z")
        assessment_id = scenario["assessment"]["id"]

        validate_success(
            api.update_plan(
                scenario["plan"]["id"],
                {"mass_withdrawal_declared": True},
                FUND_ADMINISTRATOR_HEADERS,
            ),
            200,
        )
        current_version = get_assessment(api, assessment_id)["version"]
        response = api.create_payment_schedule(
            factories.payment_schedule_payload(
                assessment_id,
                current_version,
                source=PaymentScheduleSource.ACTUARIAL_CORRECTION.value,
                override_net_assessed_cents=UNAMORTIZABLE_BASIS_CENTS,
            ),
            PLAN_ACTUARY_HEADERS,
        )
        validate_error(response, ApiErrorId.UNAMORTIZABLE_ASSESSMENT.value, 422)

    def test_the_refused_regeneration_supersedes_nothing(self, api):
        """A rejected minting leaves the incumbent generation live and the assessment's
        active generation still pointing at it.

        PRD 3.6: "The assessment's `active_schedule_generation` records the
        `generation_seq` of whichever of its schedules is currently in a non-terminal
        status — `ACTIVE`, `DEFAULT_ELIGIBLE` or `NOTICED` — and is 0 when no such
        generation exists."

        Design: Difficulty/dual_variant_calc/amortization_cap_variant_capped_forgiveness_versus_mass_withdrawal_rejection
        """
        scenario = _capped_scenario(api, "2026-05-15T00:00:00Z")
        assessment_id = scenario["assessment"]["id"]
        schedule_id = scenario["schedule"]["id"]

        validate_success(
            api.update_plan(
                scenario["plan"]["id"],
                {"mass_withdrawal_declared": True},
                FUND_ADMINISTRATOR_HEADERS,
            ),
            200,
        )
        current_version = get_assessment(api, assessment_id)["version"]
        response = api.create_payment_schedule(
            factories.payment_schedule_payload(
                assessment_id,
                current_version,
                source=PaymentScheduleSource.ACTUARIAL_CORRECTION.value,
                override_net_assessed_cents=UNAMORTIZABLE_BASIS_CENTS,
            ),
            PLAN_ACTUARY_HEADERS,
        )
        validate_error(response, ApiErrorId.UNAMORTIZABLE_ASSESSMENT.value, 422)

        assert get_schedule(api, schedule_id)["status"] == "ACTIVE"
        assert get_assessment(api, assessment_id)["active_schedule_generation"] == 1


class TestTwentyYearCapEvaluationOrder:
    def test_annual_payment_stays_history_derived_and_is_never_back_solved(self, api):
        """The annual payment is the peak rate times the highest three-year average, not
        the assessed amount divided by twenty.

        PRD 3.5: "`annual_payment_cents` is then the four-decimal `high_3yr_average_cbu`
        multiplied by the integer `peak_contribution_rate_cents_per_cbu`, rounded half up
        to whole cents."

        Design: Difficulty/combinatorial_formula/twenty_year_cap_pinned_evaluation_order_mode_c
        """
        scenario = _capped_scenario(
            api, "2026-03-31T00:00:00Z", reported_cause="COVERED_WORK_CEASED", issue=False
        )
        assessment = scenario["assessment"]

        assert assessment["net_assessed_cents"] == UNAMORTIZABLE_BASIS_CENTS
        assert assessment["annual_payment_cents"] == HISTORY_DERIVED_ANNUAL_PAYMENT_CENTS
        assert assessment["annual_payment_cents"] != 501_000_000
        assert assessment["high_3yr_average_cbu"] == pytest.approx(67_333.3333, abs=0.0001)
        assert assessment["high_3yr_window_start_year"] == 2021
        assert assessment["peak_contribution_rate_cents_per_cbu"] == 5_000

    def test_forgiveness_comes_from_the_pre_cap_basis_and_the_split_ties_out(self, api):
        """The capped basis is the pre-cap basis less the forgiven shortfall, and the
        eighty instalments sum back to that capped basis exactly.

        PRD 3.6: "`capped_basis_cents` is `amortization_basis_cents` less
        `forgiven_by_cap_cents`. `forgiven_by_cap_cents` was derived from the **pre-cap**
        basis in step two and is never recomputed from `capped_basis_cents`."

        Design: Difficulty/combinatorial_formula/twenty_year_cap_pinned_evaluation_order_mode_c
        """
        scenario = _capped_scenario(
            api, "2026-03-31T00:00:00Z", reported_cause="COVERED_WORK_CEASED"
        )
        schedule = latest_schedule(api, scenario["assessment"]["id"])
        installments = list_all_installments(api, schedule["id"])

        assert schedule["amortization_basis_cents"] == UNAMORTIZABLE_BASIS_CENTS
        assert schedule["forgiven_by_cap_cents"] == FORGIVEN_BY_CAP_CENTS
        assert (
            schedule["capped_basis_cents"]
            == schedule["amortization_basis_cents"] - schedule["forgiven_by_cap_cents"]
        )
        assert schedule["annual_payment_cents"] == HISTORY_DERIVED_ANNUAL_PAYMENT_CENTS
        assert (
            schedule["quarterly_installment_cents"] * 79 + schedule["final_installment_cents"]
            == CAPPED_BASIS_CENTS
        )
        assert len(installments) == 80
        assert sum(item["principal_cents"] for item in installments) == CAPPED_BASIS_CENTS
        assert schedule["first_due_date"].startswith("2026-09-30T00:00:00")
