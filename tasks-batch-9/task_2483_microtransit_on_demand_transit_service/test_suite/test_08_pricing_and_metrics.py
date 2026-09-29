"""Pricing arithmetic and the zone scorecard.

Every test builds its own state from scratch through the public endpoints, moves
the logical clock explicitly whenever a recipe depends on "now", and re-derives
each expected figure from the PRD's rounding rules (PRD §2.6, §2.7, §3.7, §3.8).
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions
from test_helpers.api_client import api_client
from test_helpers.factories import pool_assignment_payload
from test_helpers.fixtures import (
    accept_assignment,
    board_assignment,
    close_block,
    complete_assignment,
    create_rider,
    create_trip,
    dispatch_trip,
    ledger_for_trip,
    refresh_assignment,
    refresh_block,
    refresh_rider,
    refresh_trip,
    refresh_zone,
    set_clock,
    setup_completed_trip,
    setup_dispatch_ready,
    setup_offered_trip,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    DISPATCHER_HEADERS,
    make_rider_headers,
)

SERVICE_DAY_OPEN_UTC = "2026-08-03T06:00:00Z"

# Zone policy that lifts both fare ceilings clear of a 325-cent ride, so capping
# never perturbs the metrics under test.
UNCAPPED_FARE_POLICY = {
    "fare_cap_cents_daily": 2000,
    "fare_cap_cents_weekly": 5000,
}


# ─── Shared state builders ─────────────────────────────────────────────────


def _build_mixed_outcome_day() -> dict:
    """One completed ride, one cancelled trip and one boarded-but-unfinished ride
    on a single still-open block.

    Rider RA is picked up at 07:04Z (four minutes after asking for 07:00Z) and
    dropped at 07:16Z, so her wait is 4 minutes and her ride 12 minutes. Rider
    RB cancels before any offer. Rider RC boards at 08:02Z and stays aboard.
    """
    state = setup_dispatch_ready(zone_overrides=dict(UNCAPPED_FARE_POLICY))
    zone_id = state["zone"]["id"]
    block_id = state["block"]["id"]
    driver_id = state["driver"]["id"]
    origin_id = state["stops"][0]["id"]
    destination_id = state["stops"][4]["id"]

    rider_a = create_rider(zone_id, "RA")
    rider_b = create_rider(zone_id, "RB")
    rider_c = create_rider(zone_id, "RC")

    trip_a = create_trip(
        zone_id,
        rider_a["id"],
        origin_id,
        destination_id,
        requested_pickup_utc="2026-08-03T07:00:00Z",
    )
    assignment_a = dispatch_trip(trip_a["id"], block_id)
    accept_assignment(assignment_a["id"], driver_id)
    set_clock("2026-08-03T07:04:00Z")
    board_assignment(assignment_a["id"], driver_id)
    set_clock("2026-08-03T07:16:00Z")
    complete_assignment(assignment_a["id"], driver_id)

    trip_b = create_trip(
        zone_id,
        rider_b["id"],
        origin_id,
        destination_id,
        requested_pickup_utc="2026-08-03T07:40:00Z",
    )
    validate_success(
        api_client.cancel_trip_request(
            trip_b["id"],
            make_rider_headers(rider_b["id"]),
            payload={"note": "rider walked instead"},
        )
    )

    trip_c = create_trip(
        zone_id,
        rider_c["id"],
        origin_id,
        destination_id,
        requested_pickup_utc="2026-08-03T08:00:00Z",
    )
    assignment_c = dispatch_trip(trip_c["id"], block_id)
    accept_assignment(assignment_c["id"], driver_id)
    set_clock("2026-08-03T08:02:00Z")
    board_assignment(assignment_c["id"], driver_id)

    state.update(
        {
            "trip_a": trip_a,
            "trip_b": trip_b,
            "trip_c": trip_c,
        }
    )
    return state


def _build_three_rides_then_park_clock_at_close() -> dict:
    """Three completed rides on one block, with the clock parked at 07:40Z.

    Waits are 3, 4 and 5 minutes (R1 07:00Z/07:03Z, R2 07:05Z/07:09Z, R3
    07:20Z/07:25Z) and every ride runs the 12-minute S0->S4 baseline. R3 has
    declared a wheelchair, so R3 is the only wheelchair-accessible ride. The
    block opened at 06:00Z, so closing at 07:40Z spans 100 minutes.
    """
    state = setup_dispatch_ready(zone_overrides=dict(UNCAPPED_FARE_POLICY))
    zone_id = state["zone"]["id"]
    block_id = state["block"]["id"]
    driver_id = state["driver"]["id"]
    origin_id = state["stops"][0]["id"]
    destination_id = state["stops"][4]["id"]

    rider_1 = state["rider"]
    rider_2 = create_rider(zone_id, "R2")
    rider_3 = create_rider(zone_id, "R3", mobility_device="WHEELCHAIR")

    assignments = {}
    for key, rider, pickup in (
        ("a1", rider_1, "2026-08-03T07:00:00Z"),
        ("a2", rider_2, "2026-08-03T07:05:00Z"),
        ("a3", rider_3, "2026-08-03T07:20:00Z"),
    ):
        trip = create_trip(
            zone_id,
            rider["id"],
            origin_id,
            destination_id,
            requested_pickup_utc=pickup,
        )
        assignment = dispatch_trip(trip["id"], block_id)
        accept_assignment(assignment["id"], driver_id)
        assignments[key] = assignment

    set_clock("2026-08-03T07:03:00Z")
    board_assignment(assignments["a1"]["id"], driver_id)
    set_clock("2026-08-03T07:09:00Z")
    board_assignment(assignments["a2"]["id"], driver_id)
    set_clock("2026-08-03T07:15:00Z")
    complete_assignment(assignments["a1"]["id"], driver_id)
    set_clock("2026-08-03T07:21:00Z")
    complete_assignment(assignments["a2"]["id"], driver_id)
    set_clock("2026-08-03T07:25:00Z")
    board_assignment(assignments["a3"]["id"], driver_id)
    set_clock("2026-08-03T07:37:00Z")
    complete_assignment(assignments["a3"]["id"], driver_id)
    set_clock("2026-08-03T07:40:00Z")

    state["assignments"] = assignments
    return state


# ─── SHORT band: base fare only ────────────────────────────────────────────


def test_short_band_hop_quotes_exactly_the_zone_base_fare():
    """A six-minute hop is SHORT, so its quote is the base fare with no surcharge.

    PRD: "The surcharge is 0 cents for a `SHORT` trip, 75 cents for a `MEDIUM` trip and 150 cents for a `LONG` trip."

    Design: Corner/calculations/short_band_quote_is_base_fare_with_no_surcharge
    """
    state = setup_dispatch_ready(clock_at=SERVICE_DAY_OPEN_UTC)
    trip = create_trip(
        state["zone"]["id"],
        state["rider"]["id"],
        state["stops"][0]["id"],
        state["stops"][2]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
    )

    block = refresh_block(state["block"]["id"])
    created = validate_success(
        api_client.create_pool_assignment(
            pool_assignment_payload(trip["id"], block["id"], block["version"]),
            DISPATCHER_HEADERS,
        ),
        201,
    )

    trip = refresh_trip(trip["id"])
    # 2 index steps x 3 minutes = 6 minutes of basis, at or below the 10-minute
    # SHORT edge, so the gross fare is the 250-cent base fare and the FULL
    # multiplier of 1.00 leaves it there. No connection, so no transfer credit.
    assert trip["quoted_fare_cents"] == 250
    assert isinstance(trip["quoted_fare_cents"], int)
    assertions.assert_trip_state(trip, "OFFERED", "QUOTED")
    assertions.assert_null_fields(trip, "applied_cap", "charged_fare_cents")
    assertions.assert_assignment_state(created, "OFFERED")


def test_short_band_offer_stamps_geometry_and_the_promised_window():
    """The only offer on a block detours nobody, so the promised ride is exactly
    the baseline direct ride.

    PRD: "On the trip, `assigned_block_id` is set to the winning block, `match_attempt_count` increases by 1, `baseline_direct_minutes` and `projected_detour_minutes` are written from the corridor geometry, `promised_pickup_utc` is set to the later of `requested_pickup_utc` and the current logical clock reading, and `promised_dropoff_utc` is set to the promised pickup plus the sum of `baseline_direct_minutes` and `projected_detour_minutes` in minutes."

    Design: Corner/calculations/short_band_quote_is_base_fare_with_no_surcharge
    """
    state = setup_offered_trip(
        state=setup_dispatch_ready(clock_at=SERVICE_DAY_OPEN_UTC),
        destination_index=2,
        manual=True,
        requested_pickup_utc="2026-08-03T07:00:00Z",
    )

    assignment = refresh_assignment(state["assignment"]["id"])
    assertions.assert_fields(
        assignment,
        baseline_direct_minutes=6,
        projected_detour_minutes=0,
    )

    trip = refresh_trip(state["trip"]["id"])
    assertions.assert_fields(
        trip,
        baseline_direct_minutes=6,
        projected_detour_minutes=0,
        assigned_block_id=state["block"]["id"],
    )
    # The clock reads 06:00Z, earlier than the 07:00Z request, so the later of
    # the two is the request itself; the promise adds 6 + 0 minutes.
    assertions.assert_instant_equals(
        trip["promised_pickup_utc"], "2026-08-03T07:00:00Z"
    )
    assertions.assert_instant_equals(
        trip["promised_dropoff_utc"], "2026-08-03T07:06:00Z"
    )


# ─── Fare-category multipliers ─────────────────────────────────────────────


def test_reduced_and_paratransit_riders_get_the_declared_multipliers():
    """Two SHORT hops off the same 250-cent gross quote 125 and 0 cents.

    PRD: "A `FULL` rider's multiplier is 1.00, a `REDUCED` rider's is 0.50, and a `PARATRANSIT` rider's is 0.00 — paratransit trips are fare-free in this service."

    Design: Corner/calculations/fare_category_multiplier_constants_are_applied_once_at_step_four
    """
    state = setup_dispatch_ready(clock_at=SERVICE_DAY_OPEN_UTC)
    zone_id = state["zone"]["id"]
    block_id = state["block"]["id"]
    origin_id = state["stops"][0]["id"]
    destination_id = state["stops"][2]["id"]

    reduced_rider = create_rider(zone_id, "RR", fare_category="REDUCED")
    paratransit_rider = create_rider(zone_id, "RP", fare_category="PARATRANSIT")

    reduced_trip = create_trip(
        zone_id,
        reduced_rider["id"],
        origin_id,
        destination_id,
        requested_pickup_utc="2026-08-03T07:00:00Z",
    )
    paratransit_trip = create_trip(
        zone_id,
        paratransit_rider["id"],
        origin_id,
        destination_id,
        requested_pickup_utc="2026-08-03T07:20:00Z",
    )

    reduced_assignment = dispatch_trip(reduced_trip["id"], block_id)
    paratransit_assignment = dispatch_trip(paratransit_trip["id"], block_id)

    reduced_trip = refresh_trip(reduced_trip["id"])
    paratransit_trip = refresh_trip(paratransit_trip["id"])

    assert reduced_trip["quoted_fare_cents"] == 125
    assert paratransit_trip["quoted_fare_cents"] == 0
    assertions.assert_trip_state(reduced_trip, "OFFERED", "QUOTED")
    assertions.assert_trip_state(paratransit_trip, "OFFERED", "QUOTED")

    assert refresh_assignment(reduced_assignment["id"])["baseline_direct_minutes"] == 6
    assert (
        refresh_assignment(paratransit_assignment["id"])["baseline_direct_minutes"] == 6
    )

    assertions.assert_block_commitments(
        refresh_block(block_id), seats_committed=2, wav_positions_committed=0
    )
    # Quoting moves no money, so the fare counters are untouched.
    assert refresh_rider(reduced_rider["id"])["daily_fare_paid_cents"] == 0
    assert refresh_rider(paratransit_rider["id"])["daily_fare_paid_cents"] == 0


@pytest.mark.parametrize(
    "destination_index,fare_category,expected_quote_cents",
    [
        (2, "FULL", 250),
        (2, "REDUCED", 125),
        (2, "PARATRANSIT", 0),
        # A MEDIUM hop grosses 250 + 75 = 325; 325 x 0.50 = 162.5 rounds half up.
        (4, "REDUCED", 163),
    ],
)
def test_category_multiplication_rounds_half_up_to_whole_cents(
    destination_index, fare_category, expected_quote_cents
):
    """The multiplier is applied to the gross fare and the product rounds half up.

    PRD: "Multiply the gross fare by the rider's category multiplier and round the product half up to whole cents."

    Design: Corner/calculations/fare_category_multiplier_constants_are_applied_once_at_step_four
    """
    state = setup_dispatch_ready(
        clock_at=SERVICE_DAY_OPEN_UTC,
        rider_overrides={"fare_category": fare_category},
    )
    trip = create_trip(
        state["zone"]["id"],
        state["rider"]["id"],
        state["stops"][0]["id"],
        state["stops"][destination_index]["id"],
        requested_pickup_utc="2026-08-03T07:00:00Z",
    )
    dispatch_trip(trip["id"], state["block"]["id"])

    trip = refresh_trip(trip["id"])
    assert trip["quoted_fare_cents"] == expected_quote_cents
    assert isinstance(trip["quoted_fare_cents"], int)
    assertions.assert_trip_state(trip, "OFFERED", "QUOTED")


# ─── Metric input sets: completed trips and closed blocks only ─────────────


def test_wait_and_ride_means_cover_completed_trips_only():
    """A cancelled trip and a still-riding trip stay out of the zone means.

    PRD: "The population for the wait and ride statistics is the set of trip requests in the zone whose `status` is `COMPLETED`."

    Design: Corner/calculations/performance_metrics_include_only_completed_trips_and_closed_blocks
    """
    state = _build_mixed_outcome_day()

    zone = validate_success(
        api_client.get_service_zone(state["zone"]["id"], AUDITOR_HEADERS)
    )
    assert zone["completed_trip_count"] == 1
    # Only rider RA's ride contributes: 07:04Z minus 07:00Z is a 4-minute wait
    # and 07:16Z minus 07:04Z a 12-minute ride.
    assert zone["avg_wait_minutes"] == pytest.approx(4.00, abs=0.01)
    assert zone["avg_ride_minutes"] == pytest.approx(12.00, abs=0.01)

    assertions.assert_trip_state(refresh_trip(state["trip_b"]["id"]), "CANCELLED")
    assertions.assert_trip_state(refresh_trip(state["trip_c"]["id"]), "PICKED_UP")


def test_cancelled_trip_does_not_raise_the_unserved_count():
    """`unserved_trip_count` counts NO_SERVICE trips, and a cancellation is not one.

    PRD: "`completed_trip_count` is simply the size of that set, and `unserved_trip_count` is the count of trip requests in the zone whose `status` is `NO_SERVICE`."

    Design: Corner/calculations/performance_metrics_include_only_completed_trips_and_closed_blocks
    """
    state = _build_mixed_outcome_day()

    zone = refresh_zone(state["zone"]["id"])
    assert zone["unserved_trip_count"] == 0
    assert zone["completed_trip_count"] == 1


def test_empty_wheelchair_subset_leaves_its_mean_and_the_ratio_at_zero():
    """With no wheelchair-accessible ride completed, the accessible mean reads
    0.00 and the equivalence ratio 0.000.

    PRD: "`wav_avg_wait_minutes` is the mean `wait_minutes` over completed trips whose `wav_required` is true, and `nonwav_avg_wait_minutes` is the mean over completed trips whose `wav_required` is false; both are carried to 2 decimal places rounded half up, and both read 0.00 when their respective subset is empty."

    Design: Corner/calculations/performance_metrics_include_only_completed_trips_and_closed_blocks
    """
    state = _build_mixed_outcome_day()

    zone = refresh_zone(state["zone"]["id"])
    assert zone["wav_avg_wait_minutes"] == pytest.approx(0.00, abs=0.01)
    assert zone["nonwav_avg_wait_minutes"] == pytest.approx(4.00, abs=0.01)
    assert zone["wav_equivalence_ratio"] == pytest.approx(0.000, abs=0.001)
    assert zone["equivalence_verdict"] == "COMPLIANT"


def test_productivity_stays_zero_while_the_only_block_is_open():
    """Revenue hours come from closed blocks only, so productivity is 0.00 while
    the block is still open.

    PRD: "`boardings_per_revenue_hour` is the sum of `boardings_count` across the zone's vehicle blocks whose `state` is `CLOSED`, divided by the sum of `actual_revenue_hours` across the same blocks, rounded half up to 2 decimal places; when that divisor is 0 the metric reads 0.00."

    Design: Corner/calculations/performance_metrics_include_only_completed_trips_and_closed_blocks
    """
    state = _build_mixed_outcome_day()

    block = refresh_block(state["block"]["id"])
    assertions.assert_block_state(block, "OPEN")
    # boardings_count only grows when a ride completes, so rider RC's boarding
    # has not moved it and rider RA's completion moved it by one seat.
    assert block["boardings_count"] == 1
    assert block["actual_revenue_hours"] == pytest.approx(0.00, abs=0.01)

    zone = refresh_zone(state["zone"]["id"])
    assert zone["boardings_per_revenue_hour"] == pytest.approx(0.00, abs=0.01)


# ─── Rounding: two and three decimal places ────────────────────────────────


def test_closing_a_block_rounds_actual_revenue_hours_half_up_at_two_decimals():
    """A 100-minute block span settles as 1.67 revenue hours.

    PRD: "On success `state` becomes `CLOSED`, `closed_at` is stamped with the current logical clock reading, and `actual_revenue_hours` is recomputed as the difference between `closed_at` and `opened_at` expressed in hours to 2 decimal places rounded half up."

    Design: Corner/calculations/metric_rounding_is_half_up_at_two_and_three_decimals
    """
    state = _build_three_rides_then_park_clock_at_close()

    closed = validate_success(
        api_client.close_vehicle_block(state["block"]["id"], DISPATCHER_HEADERS)
    )
    assertions.assert_block_state(closed, "CLOSED")
    assertions.assert_instant_equals(closed["closed_at"], "2026-08-03T07:40:00Z")
    # 06:00Z -> 07:40Z is 100 minutes, i.e. 1.6666... hours.
    assert closed["actual_revenue_hours"] == pytest.approx(1.67, abs=0.01)
    assert closed["boardings_count"] == 3


def test_zone_means_are_carried_to_two_decimal_places_half_up():
    """Waits of 3, 4 and 5 minutes split into a 3.50 ambulatory mean and a 5.00
    accessible mean, and 3 boardings over 1.67 hours read 1.80.

    PRD: "**Zone performance means** — `avg_wait_minutes`, `avg_ride_minutes`, `wav_avg_wait_minutes`, `nonwav_avg_wait_minutes` and `boardings_per_revenue_hour` — are carried to exactly 2 decimal places, rounded half up."

    Design: Corner/calculations/metric_rounding_is_half_up_at_two_and_three_decimals
    """
    state = _build_three_rides_then_park_clock_at_close()
    close_block(state["block"]["id"])

    zone = refresh_zone(state["zone"]["id"])
    assert zone["completed_trip_count"] == 3
    assert zone["avg_wait_minutes"] == pytest.approx(4.00, abs=0.01)
    assert zone["avg_ride_minutes"] == pytest.approx(12.00, abs=0.01)
    assert zone["nonwav_avg_wait_minutes"] == pytest.approx(3.50, abs=0.01)
    assert zone["wav_avg_wait_minutes"] == pytest.approx(5.00, abs=0.01)
    # 3 boardings divided by the already-rounded 1.67 revenue hours is 1.7964.
    assert zone["boardings_per_revenue_hour"] == pytest.approx(1.80, abs=0.01)


def test_equivalence_ratio_is_carried_to_three_decimal_places_half_up():
    """5.00 divided by 3.50 is 1.4285714, which rounds half up to 1.429.

    PRD: "The ratio between them, `wav_equivalence_ratio`, is `wav_avg_wait_minutes` divided by `nonwav_avg_wait_minutes`, rounded half up to 3 decimal places; when `nonwav_avg_wait_minutes` is 0.00 the ratio reads 0.000 rather than being undefined."

    Design: Corner/calculations/metric_rounding_is_half_up_at_two_and_three_decimals
    """
    state = _build_three_rides_then_park_clock_at_close()
    close_block(state["block"]["id"])

    zone = refresh_zone(state["zone"]["id"])
    assert zone["wav_avg_wait_minutes"] == pytest.approx(5.00, abs=0.01)
    assert zone["nonwav_avg_wait_minutes"] == pytest.approx(3.50, abs=0.01)
    assert zone["wav_equivalence_ratio"] == pytest.approx(1.429, abs=0.001)


def test_ratio_above_the_threshold_makes_the_verdict_deficient():
    """A ratio of 1.429 exceeds the 1.25 ceiling, so the zone is DEFICIENT.

    PRD: "`equivalence_verdict` is `COMPLIANT` when the ratio is less than or equal to 1.25, and `DEFICIENT` when it is above."

    Design: Corner/calculations/metric_rounding_is_half_up_at_two_and_three_decimals
    """
    state = _build_three_rides_then_park_clock_at_close()
    close_block(state["block"]["id"])

    zone = refresh_zone(state["zone"]["id"])
    assert zone["wav_equivalence_ratio"] == pytest.approx(1.429, abs=0.001)
    assert zone["equivalence_verdict"] == "DEFICIENT"


# ─── Which fare variant runs where ─────────────────────────────────────────


def test_only_the_quote_variant_runs_at_offer_creation():
    """Offer creation writes the quote and leaves the settled charge untouched.

    PRD: "The **provisional-quote variant** runs at offer creation, when the fare axis moves `UNPRICED → QUOTED`, and writes `quoted_fare_cents`."

    Design: Corner/calculations/quote_variant_runs_at_offer_and_settle_variant_runs_at_dropoff
    """
    state = setup_offered_trip(
        state=setup_dispatch_ready(clock_at=SERVICE_DAY_OPEN_UTC),
        destination_index=4,
        manual=True,
        requested_pickup_utc="2026-08-03T07:00:00Z",
    )

    trip = get_success_data(
        api_client.get_trip_request(
            state["trip"]["id"], make_rider_headers(state["rider"]["id"])
        )
    )
    # Basis is the offer's 12-minute baseline direct ride: MEDIUM band, so the
    # gross is 250 + 75 and the FULL multiplier leaves it at 325.
    assert trip["quoted_fare_cents"] == 325
    assertions.assert_null_fields(trip, "charged_fare_cents", "applied_cap")
    assertions.assert_trip_state(trip, "OFFERED", "QUOTED")


def test_only_the_settle_variant_runs_at_dropoff():
    """Drop-off writes the charge and the cap attribution without rewriting the
    quote.

    PRD: "The **settled-charge variant** runs at drop-off, when the fare axis moves `QUOTED → CHARGED` or `CAPPED → CHARGED`, and writes both `charged_fare_cents` and `applied_cap`."

    Design: Corner/calculations/quote_variant_runs_at_offer_and_settle_variant_runs_at_dropoff
    """
    state = setup_completed_trip(
        state=setup_dispatch_ready(clock_at=SERVICE_DAY_OPEN_UTC),
        destination_index=4,
        manual=True,
        requested_pickup_utc="2026-08-03T07:00:00Z",
        board_at="2026-08-03T07:00:00Z",
        complete_at="2026-08-03T07:12:00Z",
    )

    trip = refresh_trip(state["trip"]["id"])
    # ride_minutes is 12, still the MEDIUM band, so the settled figure matches
    # the quote; the daily headroom of 600 cents binds nothing.
    assert trip["ride_minutes"] == 12
    assert trip["charged_fare_cents"] == 325
    assert trip["quoted_fare_cents"] == 325
    assert isinstance(trip["charged_fare_cents"], int)
    assertions.assert_fields(trip, applied_cap="NONE")
    assertions.assert_trip_state(trip, "COMPLETED", "CHARGED")
    assertions.assert_assignment_state(
        refresh_assignment(state["assignment"]["id"]), "COMPLETED"
    )


def test_settlement_appends_a_single_charge_row_for_the_post_multiplier_fare():
    """With no transfer credit and no cap rebate, the ledger carries one row.

    PRD: "Completing a ride appends a `CHARGE` row for the full post-multiplier fare from step 4, then a `TRANSFER_CREDIT` row for the negative of the transfer credit **only when that credit is greater than zero**, then a `CAP_REBATE` row for the negative of the cap rebate **only when that rebate is greater than zero**."

    Design: Corner/calculations/quote_variant_runs_at_offer_and_settle_variant_runs_at_dropoff
    """
    state = setup_completed_trip(
        state=setup_dispatch_ready(clock_at=SERVICE_DAY_OPEN_UTC),
        destination_index=4,
        manual=True,
        requested_pickup_utc="2026-08-03T07:00:00Z",
        board_at="2026-08-03T07:00:00Z",
        complete_at="2026-08-03T07:12:00Z",
    )

    rows = ledger_for_trip(state["trip"]["id"])
    assertions.assert_row_count(rows, 1)
    assertions.assert_ledger_kinds(rows, ["CHARGE"])
    assert rows[0]["amount_cents"] == 325
    assertions.assert_fields(
        rows[0],
        service_date="2026-08-03",
        applied_cap="NONE",
        trip_request_id=state["trip"]["id"],
        rider_id=state["rider"]["id"],
    )
    assertions.assert_ledger_row_shape(rows[0])
    assertions.assert_ledger_nets_to(rows, 325)


def test_settlement_moves_the_riders_daily_and_weekly_counters():
    """The rider's counters are the sums of their ledger rows for the service
    date and the Monday-anchored week.

    PRD: "Structurally, `daily_fare_paid_cents` is the sum of the `amount_cents` of that rider's fare-ledger rows whose `service_date` equals `fare_counter_date`, and `weekly_fare_paid_cents` is the sum over rows whose `service_date` falls in the ISO week beginning at `fare_counter_week_start`."

    Design: Corner/calculations/quote_variant_runs_at_offer_and_settle_variant_runs_at_dropoff
    """
    state = setup_completed_trip(
        state=setup_dispatch_ready(clock_at=SERVICE_DAY_OPEN_UTC),
        destination_index=4,
        manual=True,
        requested_pickup_utc="2026-08-03T07:00:00Z",
        board_at="2026-08-03T07:00:00Z",
        complete_at="2026-08-03T07:12:00Z",
    )

    rider = refresh_rider(state["rider"]["id"])
    # 2026-08-03 is a Monday, so the service date anchors the ISO week too.
    assertions.assert_fields(
        rider,
        daily_fare_paid_cents=325,
        weekly_fare_paid_cents=325,
        fare_counter_date="2026-08-03",
        fare_counter_week_start="2026-08-03",
    )
