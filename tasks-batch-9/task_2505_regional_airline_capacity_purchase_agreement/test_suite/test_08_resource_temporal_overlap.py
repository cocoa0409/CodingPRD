"""Two temporal capacity rules with deliberately different geometry.

The tail's turn buffer compares one pair of legs at a time; the captain's duty cap
sums hours across legs that never overlap at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_AIRCRAFT_TURN_CONFLICT, ERR_PILOT_DUTY_CAP_EXCEEDED
from test_helpers.assertions import assert_status
from test_helpers.factories import make_agreement_payload, make_flight_leg_payload
from test_helpers.fixtures import (
    add_leg,
    build_open_cycle,
    read_cycle,
    read_pilot,
)
from test_helpers.test_users import SCHEDULER_HEADERS


def _build_month_with_one_morning_rotation(api):
    """An open month whose single tail already flies 08:00 to 10:00 on the tenth."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="DTW",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=1,
        line_qualified_pilots=1,
        tail_numbers=["N1301RG"],
        cycle_month="2026-09",
        published_departures=10,
    )
    add_leg(
        api,
        scenario,
        flight_number="SM5001",
        origin="DTW",
        destination="ORD",
        scheduled_departure_utc="2026-09-10T08:00:00Z",
        scheduled_arrival_utc="2026-09-10T10:00:00Z",
        planned_block_hours=2.000,
    )
    return scenario


def _return_rotation(scenario, departure_utc, arrival_utc):
    """The return leg on the same tail, offered at whichever departure time is under test."""
    return make_flight_leg_payload(
        scenario.cycle_id,
        scenario.aircraft_id,
        scenario.captain_pilot_id,
        flight_number="SM5002",
        origin="ORD",
        destination="DTW",
        scheduled_departure_utc=departure_utc,
        scheduled_arrival_utc=arrival_utc,
        planned_block_hours=1.000,
    )


class TestAircraftTurnBuffer:
    """Thirty-five minutes of separation is the whole of the pairwise test."""

    def test_thirty_four_minutes_after_the_arrival_is_refused(self, api):
        """A single existing leg on the tail decides the outcome.

        PRD 3.4: "The pair is acceptable only if they are cleanly separated in one
        direction or the other: either the new leg departs no earlier than thirty-five
        minutes after the other leg arrives, or the new leg arrives at least thirty-five
        minutes before the other leg departs."

        Design: Difficulty/resource_temporal_overlap/aircraft_turn_buffer_pairwise_thirty_five_minutes
        """
        scenario = _build_month_with_one_morning_rotation(api)

        response = api.create_flight_leg(
            _return_rotation(scenario, "2026-09-10T10:34:00Z", "2026-09-10T11:34:00Z"),
            headers=SCHEDULER_HEADERS,
        )
        validate_error(response, ERR_AIRCRAFT_TURN_CONFLICT, 409)

        assert read_cycle(api, scenario.cycle_id)["open_leg_count"] == 1

    def test_exactly_thirty_five_minutes_after_the_arrival_is_accepted(self, api):
        """The boundary is inclusive, so one further minute publishes the leg.

        PRD 3.4: "The boundary is inclusive on both sides — exactly thirty-five minutes
        of separation is accepted, and only strictly less than that conflicts."

        Design: Difficulty/resource_temporal_overlap/aircraft_turn_buffer_pairwise_thirty_five_minutes
        """
        scenario = _build_month_with_one_morning_rotation(api)

        validate_error(
            api.create_flight_leg(
                _return_rotation(scenario, "2026-09-10T10:34:00Z", "2026-09-10T11:34:00Z"),
                headers=SCHEDULER_HEADERS,
            ),
            ERR_AIRCRAFT_TURN_CONFLICT,
            409,
        )

        response = api.create_flight_leg(
            _return_rotation(scenario, "2026-09-10T10:35:00Z", "2026-09-10T11:35:00Z"),
            headers=SCHEDULER_HEADERS,
        )
        published = validate_success(response, 201)
        assert_status(published, "SCHEDULED")
        assert published["scheduled_departure_utc"] == "2026-09-10T10:35:00Z"

        month = read_cycle(api, scenario.cycle_id)
        assert month["open_leg_count"] == 2
        assert month["recorded_completed_legs"] == 0


def _build_month_with_fifteen_captain_hours(api):
    """One captain already carrying eight and seven planned hours on the fifteenth."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="STL",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=2,
        line_qualified_pilots=2,
        tail_numbers=["N1401RG", "N1402RG"],
        cycle_month="2026-09",
        published_departures=10,
    )
    add_leg(
        api,
        scenario,
        aircraft_id=scenario.aircraft[0]["id"],
        captain_pilot_id=scenario.pilots[0]["id"],
        flight_number="SM5101",
        origin="STL",
        destination="ORD",
        scheduled_departure_utc="2026-09-15T00:00:00Z",
        scheduled_arrival_utc="2026-09-15T08:00:00Z",
        planned_block_hours=8.000,
    )
    add_leg(
        api,
        scenario,
        aircraft_id=scenario.aircraft[1]["id"],
        captain_pilot_id=scenario.pilots[0]["id"],
        flight_number="SM5102",
        origin="STL",
        destination="MSP",
        scheduled_departure_utc="2026-09-15T10:00:00Z",
        scheduled_arrival_utc="2026-09-15T17:00:00Z",
        planned_block_hours=7.000,
    )
    return scenario


def _evening_leg(scenario, arrival_utc, planned_block_hours):
    """An evening return for the same captain, well clear of every tail's turn buffer."""
    return make_flight_leg_payload(
        scenario.cycle_id,
        scenario.aircraft[1]["id"],
        scenario.pilots[0]["id"],
        flight_number="SM5103",
        origin="MSP",
        destination="STL",
        scheduled_departure_utc="2026-09-15T20:00:00Z",
        scheduled_arrival_utc=arrival_utc,
        planned_block_hours=planned_block_hours,
    )


class TestCaptainRollingDutyCap:
    """Legs hours apart still collide through the aggregate sum."""

    def test_a_total_of_sixteen_and_a_half_hours_is_refused(self, api):
        """Nothing overlaps in clock time, yet the window's sum exceeds the cap.

        PRD 3.4: "If the resulting total exceeds sixteen block hours — sixteen point zero
        zero zero, to the three decimals block hours are carried at — the request is
        rejected with `ERR_PILOT_DUTY_CAP_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/pilot_rolling_duty_cap_aggregate_sixteen_hours
        """
        scenario = _build_month_with_fifteen_captain_hours(api)

        response = api.create_flight_leg(
            _evening_leg(scenario, "2026-09-15T21:30:00Z", 1.500), headers=SCHEDULER_HEADERS
        )
        error_id = validate_error(response, ERR_PILOT_DUTY_CAP_EXCEEDED, 409)["error_id"]
        assert error_id != ERR_AIRCRAFT_TURN_CONFLICT, (
            "the evening departure is three hours clear of the tail's last arrival"
        )

        assert read_cycle(api, scenario.cycle_id)["open_leg_count"] == 2

    def test_a_total_of_exactly_sixteen_hours_is_accepted(self, api):
        """The cap is inclusive and the rule mutates no pilot row.

        PRD 3.4: "A total of exactly 16.000 is accepted. Because this rule aggregates
        rather than compares pairs, two legs that never overlap in clock time, and are
        indeed many hours apart, can still collide through the sum."

        Design: Difficulty/resource_temporal_overlap/pilot_rolling_duty_cap_aggregate_sixteen_hours
        """
        scenario = _build_month_with_fifteen_captain_hours(api)

        validate_error(
            api.create_flight_leg(
                _evening_leg(scenario, "2026-09-15T21:30:00Z", 1.500), headers=SCHEDULER_HEADERS
            ),
            ERR_PILOT_DUTY_CAP_EXCEEDED,
            409,
        )

        response = api.create_flight_leg(
            _evening_leg(scenario, "2026-09-15T21:00:00Z", 1.000), headers=SCHEDULER_HEADERS
        )
        published = validate_success(response, 201)
        assert_status(published, "SCHEDULED")

        assert read_cycle(api, scenario.cycle_id)["open_leg_count"] == 3
        assert_status(read_pilot(api, scenario.pilots[0]["id"]), "LINE_QUALIFIED")
        assert_status(read_pilot(api, scenario.pilots[1]["id"]), "LINE_QUALIFIED")
