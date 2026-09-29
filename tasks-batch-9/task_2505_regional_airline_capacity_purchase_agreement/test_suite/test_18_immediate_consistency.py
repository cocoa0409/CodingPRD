"""Derived values are settled inside the write that caused them.

One completion is reported and then the parent month is read once. The response to the
write already carries the leg's own derived money and punctuality, and the very next
read of the cycle shows every counter the completion moved.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_block_hours,
    assert_departure_ledger_identity,
    assert_money,
    assert_status,
)
from test_helpers.factories import make_agreement_payload, make_completion_payload
from test_helpers.fixtures import add_leg, build_open_cycle, read_cycle
from test_helpers.test_users import OPS_HEADERS


class TestCompletionIsVisibleImmediately:
    """No second write and no delay stands between the report and the ledger."""

    def test_the_completion_response_and_the_next_cycle_read_already_agree(self, api):
        """The leg's payment and on-time flag arrive with the write; the counters with the read.

        PRD 2.7: "Derived attributes are always kept immediately consistent: there is no
        deferred or batched recomputation, so a read that follows a successful write always
        observes the settled result of every cascade that write triggered."

        PRD 3.4: "`on_time` is true when `actual_arrival_utc` is no later than
        `scheduled_arrival_utc` plus a fourteen-minute grace allowance; the boundary is
        inclusive, so an arrival exactly fourteen minutes late is on time and an arrival
        fourteen minutes and one second late is not."

        PRD 3.4: "`leg_variable_payment_usd` is the leg's own variable earnings: the product of
        `actual_block_hours` and the agreement's `block_hour_rate_usd`, rounded half-up to two
        decimal places, plus the agreement's `departure_rate_usd`, which is already carried at
        two decimals."

        PRD 3.4: "Completion also rolls the month's counters forward: `recorded_completed_legs`
        rises by 1, `open_leg_count` falls by 1, `credited_block_hours` takes on the leg's
        `actual_block_hours` in addition to what it held, `enplaned_bags_total` and
        `mishandled_bags_total` absorb the two reported bag counts, and `on_time_leg_count`
        rises by 1 only when `on_time` came out true."

        Design: Corner/consistency_model/completion_response_and_parent_ledger_are_immediately_consistent
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N5901RG"],
            cycle_month="2026-09",
            published_departures=2,
        )
        leg = add_leg(
            api,
            scenario,
            flight_number="SM8901",
            origin="MKE",
            destination="DEN",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T10:00:00Z",
            planned_block_hours=2.000,
        )

        flown = validate_success(
            api.complete_flight_leg(
                leg["id"],
                make_completion_payload(
                    actual_block_hours=1.750,
                    actual_arrival_utc="2026-09-02T10:20:00Z",
                    enplaned_bags=150,
                    mishandled_bags=1,
                ),
                headers=OPS_HEADERS,
            )
        )
        assert_status(flown, "COMPLETED")
        assert flown["on_time"] is False, "twenty minutes late is outside the fourteen-minute grace"
        assert_money(
            flown["leg_variable_payment_usd"],
            2858.81,
            "the rounded block-hour earnings plus the departure rate",
        )

        month = read_cycle(api, scenario.cycle_id)
        assert_block_hours(month["credited_block_hours"], 1.750, "credited block hours")
        assert month["recorded_completed_legs"] == 1
        assert month["open_leg_count"] == 0
        assert month["enplaned_bags_total"] == 150
        assert month["mishandled_bags_total"] == 1
        assert month["on_time_leg_count"] == 0

        assert month["metric_completed_departures"] == 2, "flying a departure moves no counter"
        assert month["departure_ledger_total"] == 2
        assert_departure_ledger_identity(month)
