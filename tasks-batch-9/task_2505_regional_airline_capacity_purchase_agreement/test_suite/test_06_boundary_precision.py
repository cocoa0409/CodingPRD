"""Metric boundaries probed one epsilon either side.

Completion factors of 99.00 and 98.99 land in different bands, and an arrival
fourteen minutes late is on time while fourteen minutes and one second is not.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_block_hours,
    assert_money,
    assert_percentage,
)
from test_helpers.factories import (
    make_agreement_payload,
    make_completion_payload,
)
from test_helpers.fixtures import (
    add_leg,
    build_open_cycle,
    cancel_leg,
    claim_for_leg,
    close_cycle,
    create_cycle,
    open_cycle,
    read_cycle,
    read_leg,
    adjudicate_claim,
    scorecard_for_cycle,
)
from test_helpers.test_users import OPS_HEADERS
from test_helpers.types import CycleScenario

REVENUE_SHARE_CEILING_ON_FIXED_ONLY_USD = 15600.00


def _build_epsilon_pair_of_months(api):
    """Two months of one contract whose completion factors differ by one hundredth."""
    september = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="DSM",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=2,
        line_qualified_pilots=1,
        tail_numbers=["N901RG"],
        cycle_month="2026-09",
        published_departures=100,
    )
    september_leg = add_leg(
        api,
        september,
        flight_number="SM4701",
        origin="DSM",
        destination="ORD",
        scheduled_departure_utc="2026-09-12T08:00:00Z",
        scheduled_arrival_utc="2026-09-12T09:00:00Z",
        planned_block_hours=1.000,
    )
    cancel_leg(api, september_leg["id"], cause_code="CREW_UNAVAILABLE")
    close_cycle(api, september.cycle_id)

    october_cycle = create_cycle(
        api, september.agreement_id, cycle_month="2026-10", published_departures=100
    )
    october_cycle = open_cycle(api, october_cycle["id"])
    october = CycleScenario(
        agreement=september.agreement,
        crew_base=september.crew_base,
        base_headers=september.base_headers,
        pilots=september.pilots,
        aircraft=september.aircraft,
        cycle=october_cycle,
    )
    agreed_leg = add_leg(
        api,
        october,
        flight_number="SM4702",
        origin="DSM",
        destination="ORD",
        scheduled_departure_utc="2026-10-05T08:00:00Z",
        scheduled_arrival_utc="2026-10-05T09:00:00Z",
        planned_block_hours=1.000,
    )
    open_leg = add_leg(
        api,
        october,
        flight_number="SM4703",
        origin="DSM",
        destination="MSP",
        scheduled_departure_utc="2026-10-07T08:00:00Z",
        scheduled_arrival_utc="2026-10-07T09:00:00Z",
        planned_block_hours=1.000,
    )
    cancel_leg(api, agreed_leg["id"], cause_code="WEATHER")
    cancel_leg(api, open_leg["id"], cause_code="CREW_UNAVAILABLE")
    adjudicate_claim(api, claim_for_leg(api, agreed_leg["id"])["id"], "UNCONTROLLABLE")

    close_cycle(api, october.cycle_id)
    return september, october


class TestCompletionFactorBandBoundary:
    """The favourable side of the completion-factor band is inclusive."""

    def test_a_completion_factor_of_exactly_ninety_nine_earns_the_full_credit(self, api):
        """One controllable cancellation in a hundred lands exactly on the boundary.

        PRD 3.7: "Every band boundary is inclusive on the favourable side: a completion
        factor of exactly 99.00 earns the full +3, an on-time figure of exactly 80.00
        earns 0 rather than −3, and a bag rate of exactly 5.50 earns 0 rather than −2."

        Design: Difficulty/boundary_precision_check/completion_factor_epsilon_pair_at_99_00_on_cycle_close
        """
        september, october = _build_epsilon_pair_of_months(api)

        first = scorecard_for_cycle(api, september.cycle_id)
        second = scorecard_for_cycle(api, october.cycle_id)

        assert_percentage(first["completion_factor_pct"], 99.00, "September completion factor")
        assert first["completion_factor_points"] == 3
        assert_percentage(second["completion_factor_pct"], 98.99, "October completion factor")
        assert second["completion_factor_points"] == 0

    def test_the_epsilon_carries_through_the_points_and_the_capped_incentive(self, api):
        """The one-hundredth difference costs three points but not the capped payout.

        PRD 3.7: "Otherwise it is one hundred multiplied by the eligible base less
        `cancelled_controllable_count`, divided by the eligible base, rounded half-up to
        two decimal places."

        Design: Difficulty/boundary_precision_check/completion_factor_epsilon_pair_at_99_00_on_cycle_close
        """
        september, october = _build_epsilon_pair_of_months(api)

        first = scorecard_for_cycle(api, september.cycle_id)
        second = scorecard_for_cycle(api, october.cycle_id)

        assert first["performance_points"] == 6
        assert_money(first["gross_performance_usd"], 72000.00, "September gross performance")
        assert second["performance_points"] == 3
        assert_money(second["gross_performance_usd"], 36000.00, "October gross performance")
        assert_money(
            first["incentive_usd"],
            REVENUE_SHARE_CEILING_ON_FIXED_ONLY_USD,
            "September incentive",
        )
        assert_money(
            second["incentive_usd"],
            REVENUE_SHARE_CEILING_ON_FIXED_ONLY_USD,
            "October incentive",
        )
        assert_percentage(first["on_time_arrival_pct"], 100.00, "September on-time arrival")
        assert_percentage(second["on_time_arrival_pct"], 100.00, "October on-time arrival")

        october_month = read_cycle(api, october.cycle_id)
        assert october_month["cancelled_uncontrollable_count"] == 1
        assert october_month["cancelled_controllable_count"] == 1


def _build_grace_boundary_pair(api):
    """An open month with two identical legs to be reported either side of the grace."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="GRR",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=2,
        line_qualified_pilots=1,
        tail_numbers=["N1001RG"],
        cycle_month="2026-09",
        published_departures=5,
    )
    inside = add_leg(
        api,
        scenario,
        flight_number="SM4801",
        origin="GRR",
        destination="ORD",
        scheduled_departure_utc="2026-09-02T08:00:00Z",
        scheduled_arrival_utc="2026-09-02T09:00:00Z",
        planned_block_hours=1.000,
    )
    outside = add_leg(
        api,
        scenario,
        flight_number="SM4802",
        origin="GRR",
        destination="DTW",
        scheduled_departure_utc="2026-09-04T08:00:00Z",
        scheduled_arrival_utc="2026-09-04T09:00:00Z",
        planned_block_hours=1.000,
    )
    return scenario, inside, outside


class TestOnTimeGraceBoundary:
    """The fourteen-minute grace allowance is inclusive to the second."""

    def test_fourteen_minutes_late_is_on_time_and_one_second_more_is_not(self, api):
        """Two identical legs reported a second apart score differently.

        PRD 3.4: "`on_time` is true when `actual_arrival_utc` is no later than
        `scheduled_arrival_utc` plus a fourteen-minute grace allowance; the boundary is
        inclusive, so an arrival exactly fourteen minutes late is on time and an arrival
        fourteen minutes and one second late is not."

        Design: Difficulty/boundary_precision_check/on_time_grace_inclusive_boundary_on_leg_completion
        """
        scenario, inside, outside = _build_grace_boundary_pair(api)

        on_the_boundary = validate_success(
            api.complete_flight_leg(
                inside["id"],
                make_completion_payload(
                    actual_block_hours=1.000,
                    actual_arrival_utc="2026-09-02T09:14:00Z",
                    enplaned_bags=60,
                    mishandled_bags=0,
                ),
                headers=OPS_HEADERS,
            )
        )
        one_second_past = validate_success(
            api.complete_flight_leg(
                outside["id"],
                make_completion_payload(
                    actual_block_hours=1.000,
                    actual_arrival_utc="2026-09-04T09:14:01Z",
                    enplaned_bags=60,
                    mishandled_bags=0,
                ),
                headers=OPS_HEADERS,
            )
        )

        assert on_the_boundary["on_time"] is True, (
            "an arrival exactly fourteen minutes late is on time"
        )
        assert one_second_past["on_time"] is False, (
            "an arrival fourteen minutes and one second late is not on time"
        )
        assert_money(
            read_leg(api, inside["id"])["leg_variable_payment_usd"], 1770.75, "first leg payment"
        )
        assert_money(
            read_leg(api, outside["id"])["leg_variable_payment_usd"], 1770.75, "second leg payment"
        )

        month = read_cycle(api, scenario.cycle_id)
        assert month["on_time_leg_count"] == 1
        assert month["recorded_completed_legs"] == 2
        assert_block_hours(month["credited_block_hours"], 2.000, "credited block hours")

    def test_the_one_second_miss_halves_the_punctuality_metric_for_the_month(self, api):
        """Half the completed legs on time bands the metric below its floor.

        PRD 3.7: "**On-time arrival**, published as `on_time_arrival_pct`, is one hundred
        multiplied by `on_time_leg_count` divided by `recorded_completed_legs`, rounded
        half-up to two decimals, with a pinned convention of 100.00 when
        `recorded_completed_legs` is 0."

        Design: Difficulty/boundary_precision_check/on_time_grace_inclusive_boundary_on_leg_completion
        """
        scenario, inside, outside = _build_grace_boundary_pair(api)

        validate_success(
            api.complete_flight_leg(
                inside["id"],
                make_completion_payload(
                    actual_block_hours=1.000,
                    actual_arrival_utc="2026-09-02T09:14:00Z",
                    enplaned_bags=60,
                    mishandled_bags=0,
                ),
                headers=OPS_HEADERS,
            )
        )
        validate_success(
            api.complete_flight_leg(
                outside["id"],
                make_completion_payload(
                    actual_block_hours=1.000,
                    actual_arrival_utc="2026-09-04T09:14:01Z",
                    enplaned_bags=60,
                    mishandled_bags=0,
                ),
                headers=OPS_HEADERS,
            )
        )
        close_cycle(api, scenario.cycle_id)

        scorecard = scorecard_for_cycle(api, scenario.cycle_id)
        assert_percentage(scorecard["on_time_arrival_pct"], 50.00, "on-time arrival")
        assert scorecard["on_time_points"] == -3
        assert_percentage(scorecard["completion_factor_pct"], 100.00, "completion factor")
        assert scorecard["completion_factor_points"] == 3
        assert scorecard["bag_points"] == 1
        assert scorecard["performance_points"] == 1
        assert_money(scorecard["gross_performance_usd"], 12000.00, "gross performance")
        assert_money(scorecard["incentive_usd"], 12000.00, "incentive")
        assert_money(scorecard["penalty_usd"], 0.00, "penalty")
