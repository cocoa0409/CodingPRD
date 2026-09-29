"""Two inclusive comparisons at their exact boundary: the de minimis phase-out in
cents and the seventy-percent decline ratio."""

import pytest

from test_helpers.fixtures import (
    create_assessment,
    determine_withdrawal_event,
    file_certified_valuations,
    file_contribution_history,
    get_employer,
    register_controlled_group,
    register_employer,
    register_plan,
    report_withdrawal_event,
)
from test_helpers.types import AllocationMethod, Industry

PHASEOUT_START_CENTS = 10_000_000
DE_MINIMIS_BASE_CENTS = 3_000_000

SMALL_POOL_VALUATION = {
    "uvb_total_cents": 400_000_000,
    "uvb_pool_cents": 40_000_000,
    "all_employer_contributions_cents": 100_000_000,
    "all_employer_cbu": 100_000,
}

DECLINE_HISTORY_CENTS_PER_CBU = 1_000


def _phaseout_pair(api):
    """Two employers of one plan whose gross shares straddle the phase-out start."""
    plan = register_plan(
        api,
        allocation_method=AllocationMethod.MODIFIED_PRESUMPTIVE.value,
        de_minimis_variant="STATUTORY",
    )
    group = register_controlled_group(api)
    at_threshold = register_employer(
        api, plan["id"], group["id"], obligation_start_year=2021, cba_count=1
    )
    one_cent_over = register_employer(
        api, plan["id"], group["id"], obligation_start_year=2021, cba_count=1
    )
    file_certified_valuations(api, plan["id"], **SMALL_POOL_VALUATION)

    for employer, dollars in ((at_threshold, 12_500_000), (one_cent_over, 12_500_001)):
        file_contribution_history(
            api,
            employer["id"],
            [
                {
                    "plan_year_start": 2021,
                    "plan_year_end": 2025,
                    "contribution_base_units": 12_500,
                    "contribution_amount_cents": dollars,
                    "contribution_rate_cents_per_cbu": 1_000,
                }
            ],
        )

    assessments = {}
    for key, employer in (("at_threshold", at_threshold), ("one_cent_over", one_cent_over)):
        event = report_withdrawal_event(
            api, employer["id"], cessation_date="2026-01-31T00:00:00Z"
        )
        determine_withdrawal_event(api, event["id"])
        assessments[key] = create_assessment(api, event["id"])
    return assessments


def _decline_pair(api):
    """Two employers whose testing-period averages differ by a third of a base unit."""
    plan = register_plan(
        api,
        industry=Industry.GENERAL.value,
        allocation_method=AllocationMethod.ROLLING_5.value,
    )
    group = register_controlled_group(api)
    file_certified_valuations(api, plan["id"], years=(2025,))

    employers = {}
    events = {}
    for key, recent_cbu, recent_cents in (
        ("exactly_thirty_percent", 9_000, 9_000_000),
        ("one_unit_above", 9_001, 9_001_000),
    ):
        employer = register_employer(
            api, plan["id"], group["id"], obligation_start_year=2019, cba_count=1
        )
        file_contribution_history(
            api,
            employer["id"],
            [
                {
                    "plan_year_start": 2019,
                    "plan_year_end": 2020,
                    "contribution_base_units": 20_000,
                    "contribution_amount_cents": 20_000_000,
                    "contribution_rate_cents_per_cbu": DECLINE_HISTORY_CENTS_PER_CBU,
                },
                {
                    "plan_year_start": 2021,
                    "plan_year_end": 2023,
                    "contribution_base_units": 24_000,
                    "contribution_amount_cents": 24_000_000,
                    "contribution_rate_cents_per_cbu": DECLINE_HISTORY_CENTS_PER_CBU,
                },
                {
                    "plan_year_start": 2024,
                    "plan_year_end": 2026,
                    "contribution_base_units": recent_cbu,
                    "contribution_amount_cents": recent_cents,
                    "contribution_rate_cents_per_cbu": DECLINE_HISTORY_CENTS_PER_CBU,
                },
            ],
        )
        event = report_withdrawal_event(
            api,
            employer["id"],
            cessation_date="2026-07-01T00:00:00Z",
            reported_cause="CBU_DECLINE",
        )
        employers[key] = employer
        events[key] = determine_withdrawal_event(api, event["id"])
    return employers, events


class TestDeMinimisPhaseoutBoundary:
    def test_a_gross_share_exactly_at_the_phaseout_start_keeps_the_whole_reduction(self, api):
        """A gross of exactly 10000000 cents is inside the boundary, so the full
        3000000-cent base reduction survives and the demand is 7000000.

        PRD 3.5: "otherwise, if `gross_allocated_cents` is less than or equal to the
        phase-out start the reduction is the full base figure, the comparison at the
        boundary being inclusive"

        Design: Difficulty/boundary_precision_check/de_minimis_phaseout_inclusive_at_exactly_ten_million_cents
        """
        assessment = _phaseout_pair(api)["at_threshold"]

        assert assessment["gross_allocated_cents"] == PHASEOUT_START_CENTS
        assert assessment["de_minimis_reduction_cents"] == DE_MINIMIS_BASE_CENTS
        assert assessment["net_assessed_cents"] == 7_000_000
        assert assessment["de_minimis_variant_applied"] == "STATUTORY"
        assert assessment["annual_payment_cents"] == 2_500_000

    def test_one_cent_past_the_phaseout_start_burns_exactly_one_cent(self, api):
        """A gross of 10000001 exceeds the boundary by a single cent, so the reduction
        falls to 2999999 and the demand rises to 7000002.

        PRD 3.5: "otherwise the reduction is the base figure less the amount by which
        `gross_allocated_cents` exceeds the phase-out start, floored at 0"

        Design: Difficulty/boundary_precision_check/de_minimis_phaseout_inclusive_at_exactly_ten_million_cents
        """
        assessments = _phaseout_pair(api)
        just_over = assessments["one_cent_over"]

        assert just_over["gross_allocated_cents"] == PHASEOUT_START_CENTS + 1
        assert just_over["de_minimis_reduction_cents"] == DE_MINIMIS_BASE_CENTS - 1
        assert just_over["net_assessed_cents"] == 7_000_002
        assert just_over["annual_payment_cents"] == 2_500_000
        # One extra cent of gross costs the employer two cents of net.
        assert (
            just_over["net_assessed_cents"]
            - assessments["at_threshold"]["net_assessed_cents"]
            == 2
        )


class TestSeventyPercentDeclineBoundary:
    def test_a_ratio_of_exactly_three_tenths_is_a_seventy_percent_decline(self, api):
        """A testing-period average of 3000 against a high base-year average of 10000
        gives 0.300000, which the inclusive comparison treats as a decline.

        PRD 3.4: "The test reports a seventy-percent decline when `decline_ratio` is less
        than or equal to 0.30 — the comparison is inclusive, so a ratio of exactly
        0.300000 *is* a decline."

        Design: Difficulty/boundary_precision_check/seventy_percent_decline_inclusive_at_ratio_exactly_zero_point_three
        """
        employers, events = _decline_pair(api)
        event = events["exactly_thirty_percent"]

        assert event["high_base_year_average_cbu"] == pytest.approx(10_000.0, abs=0.0001)
        assert event["testing_period_average_cbu"] == pytest.approx(3_000.0, abs=0.0001)
        assert event["decline_ratio"] == pytest.approx(0.300000, abs=0.0000005)
        assert event["determined_type"] == "PARTIAL_70_DECLINE"
        assert event["status"] == "PARTIAL_DETERMINED"
        assert event["partial_withdrawal_fraction"] == pytest.approx(0.5000, abs=0.0001)
        assert event["base_year_one"] == 2019
        assert event["base_year_two"] == 2020

        employer = get_employer(api, employers["exactly_thirty_percent"]["id"])
        assert employer["status"] == "PARTIAL_WITHDRAWN"
        assert employer["obligation_end_year"] is None

    def test_one_extra_base_unit_pushes_the_ratio_past_the_threshold(self, api):
        """A single additional base unit in the testing period lifts the ratio to 0.300033
        and the determination falls to no withdrawal at all.

        PRD 3.4: "A reported decline in contribution base units yields
        `PARTIAL_70_DECLINE` when the decline test below reports a `decline_ratio` at or
        below the threshold of 0.30, and yields `NONE` otherwise."

        Design: Difficulty/boundary_precision_check/seventy_percent_decline_inclusive_at_ratio_exactly_zero_point_three
        """
        employers, events = _decline_pair(api)
        event = events["one_unit_above"]

        assert event["testing_period_average_cbu"] == pytest.approx(3_000.3333, abs=0.0001)
        assert event["decline_ratio"] == pytest.approx(0.300033, abs=0.0000005)
        assert event["determined_type"] == "NONE"
        assert event["status"] == "NO_WITHDRAWAL"
        assert event["partial_withdrawal_fraction"] == pytest.approx(0.0, abs=0.0001)

        assert get_employer(api, employers["one_unit_above"]["id"])["status"] == "CONTRIBUTING"
