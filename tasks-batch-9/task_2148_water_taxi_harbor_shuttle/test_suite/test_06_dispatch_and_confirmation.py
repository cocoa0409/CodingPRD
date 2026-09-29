"""Dispatch, decline and confirmation: the selector, the cycle and the OCC guard."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_vessel,
    assert_booking,
    buy_ride_pass,
    create_offered_booking,
    create_trip,
    create_confirmed_booking,
    current_trip_version,
    decline_booking,
    dispatch_booking,
    request_booking,
    setup_harbor_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["harbor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
RIDER = TEST_USERS["rider_headers"]
RIDER_BOB = TEST_USERS["rider_bob_headers"]


def test_dispatch_tie_break_prefers_the_roomier_sailing(api):
    """PRD §3.6: "Candidates are ranked by `scheduled_departure_utc` ascending, ties
    broken by the larger remaining capacity — that is, `effective_capacity` minus
    `seats_committed` descending — and any remaining ties broken by `created_at`
    ascending."
    PRD §3.6: "The top-ranked candidate becomes the offer: the booking's `trip_id` is
    set to it, the booking moves `REQUESTED → OFFERED`, and its `version` increments
    by 1."

    Design: Corner/cross_cutting_layers/dispatch_tie_break_prefers_the_trip_with_more_remaining_capacity_not_the_older_row
    """
    world = setup_harbor_world()
    small_vessel = add_vessel(name="Minnow", seat_capacity=12, draft_m=0.90,
                              hull_class="HARBOR", required_endorsement="MASTER_25T")
    small_trip = create_trip(world, vessel_id=small_vessel["id"])
    big_trip = create_trip(world)

    booking = request_booking(world, "rider-ann", party_size=1)
    offered = dispatch_booking(booking["id"])

    assert offered["trip_id"] == big_trip["id"], (
        f"The 40-seat sailing has more room and must win the tie, got "
        f"{offered['trip_id']}"
    )
    assert offered["trip_id"] != small_trip["id"]
    assert offered["status"] == "OFFERED"
    assert validate_success(api.get_trip(small_trip["id"], DISPATCHER))["effective_capacity"] == 12
    assert validate_success(api.get_trip(big_trip["id"], DISPATCHER))["effective_capacity"] == 40


def test_confirmation_carrying_a_superseded_trip_version_is_rejected(api):
    """PRD §2.7: "A booking-confirmation request — `POST /harbor/bookings/{id}/confirm`
    — must carry `expected_trip_version`, a non-optional integer in the request body
    carrying the client's last observed `version` of the offered `Trip`."
    PRD §2.7: "If it does not equal the trip's current `version`, the confirmation is
    rejected with `ERR_STALE_TRIP_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_expected_trip_version_on_confirmation_is_rejected_with_412
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    stale_version = trip["version"]

    first = create_offered_booking(world, "rider-ann", party_size=3)
    second = create_offered_booking(world, "rider-bob", party_size=2)
    validate_success(
        api.confirm_booking(first["id"], {"expected_trip_version": stale_version}, RIDER)
    )

    response = api.confirm_booking(second["id"],
                                   {"expected_trip_version": stale_version}, RIDER_BOB)
    validate_error(response, ApiErrorId.ERR_STALE_TRIP_VERSION.value, 412)

    assert validate_success(api.get_booking(first["id"], RIDER))["status"] == "CONFIRMED"
    assert validate_success(api.get_booking(second["id"], RIDER_BOB))["status"] == "OFFERED"
    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["seats_committed"] == 3, (
        f"Only the first confirmation may commit seats, got {refreshed['seats_committed']}"
    )


def test_confirmation_beyond_effective_capacity_is_rejected(api):
    """PRD §3.6: "Last, the trip's `effective_capacity` minus its `seats_committed`
    must be at least `party_size`, else `ERR_TRIP_CAPACITY_EXCEEDED`."
    PRD §2.8: "**Seat capacity.** The confirmation's party fits in the remaining
    capacity, and a boarding manifest's total party size fits inside
    `effective_capacity` — otherwise `ERR_TRIP_CAPACITY_EXCEEDED` (409)."

    Design: Corner/validations/confirming_beyond_effective_capacity_returns_trip_capacity_exceeded
    """
    world = setup_harbor_world(vessel={"seat_capacity": 12})
    trip = create_trip(world)

    first = create_offered_booking(world, "rider-ann", party_size=12)
    second = create_offered_booking(world, "rider-bob", party_size=1)
    validate_success(
        api.confirm_booking(first["id"],
                            {"expected_trip_version": trip["version"]}, RIDER)
    )

    response = api.confirm_booking(
        second["id"], {"expected_trip_version": current_trip_version(trip["id"])},
        RIDER_BOB,
    )
    validate_error(response, ApiErrorId.ERR_TRIP_CAPACITY_EXCEEDED.value, 409)

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["effective_capacity"] == 12
    assert refreshed["seats_committed"] == 12
    loser = validate_success(api.get_booking(second["id"], RIDER_BOB))
    assert loser["status"] == "OFFERED"
    assert loser["fare_charged_cents"] == 0


def test_tendering_a_stale_pass_expires_it_and_rejects_the_confirmation(api):
    """PRD §3.6: "When a pass is tendered, four further conditions are checked, in the
    order given here: the pass's `zone_tier` must cover the zone span between the
    booking's origin and destination stops, else `ERR_PASS_ZONE_NOT_COVERED`; the
    pass's `valid_until` must not be earlier than the logical clock's calendar date,
    and a stale pass is moved `ACTIVE → EXPIRED` before `ERR_PASS_EXPIRED` is
    returned, so the rejection leaves a permanent trace on the pass row; the pass's
    `status` must be `ACTIVE`, else `ERR_PASS_NOT_ACTIVE`; and `rides_remaining` must
    be at least the booking's `party_size`, else `ERR_PASS_NO_RIDES_REMAINING`."

    Design: Corner/state_machines/tendering_a_pass_past_its_valid_until_moves_it_to_expired_and_rejects_the_confirmation
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    ride_pass = buy_ride_pass("rider-ann", zone_tier="INNER", rides_purchased=5,
                              purchase_price_cents=5000, valid_until="2026-09-11")
    booking = create_offered_booking(world, "rider-ann", party_size=1,
                                     ride_pass_id=ride_pass["id"])

    response = api.confirm_booking(booking["id"],
                                   {"expected_trip_version": trip["version"]}, RIDER)
    validate_error(response, ApiErrorId.ERR_PASS_EXPIRED.value, 409)

    stale = validate_success(api.get_ride_pass(ride_pass["id"], RIDER))
    assert stale["status"] == "EXPIRED", (
        f"The rejection must leave the pass EXPIRED, got {stale['status']}"
    )
    assert stale["rides_remaining"] == 5, (
        f"No rides may be redeemed by a rejected confirmation, got "
        f"{stale['rides_remaining']}"
    )
    assert validate_success(api.get_booking(booking["id"], RIDER))["status"] == "OFFERED"
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["seats_committed"] == 0


def test_each_booking_endpoint_names_its_own_wrong_state(api):
    """PRD §3.6: "Dispatching a booking that is not in `REQUESTED` is rejected with
    `ERR_BOOKING_NOT_REQUESTED`."
    PRD §2.8: "**State preconditions.** The target resource is in the state the
    requested transition departs from, yielding one of `ERR_TRIP_NOT_SCHEDULED`,
    `ERR_TRIP_NOT_BOARDING`, `ERR_TRIP_NOT_DEPARTED`, `ERR_BOOKING_NOT_REQUESTED`,
    `ERR_BOOKING_NOT_OFFERED`, `ERR_BOOKING_NOT_CONFIRMED`, `ERR_PASS_NOT_ACTIVE`,
    `ERR_REFUND_CLAIM_NOT_OPEN`, or `ERR_INTERRUPTION_NOT_DECLARABLE` (all 409)."
    PRD §3.6: "Only the booking's owner may confirm, the booking must be `OFFERED`,
    and the offered trip must still be `SCHEDULED` — a trip that has already opened
    boarding is rejected with `ERR_TRIP_NOT_SCHEDULED`."
    PRD §3.7: "Every id in the manifest must name a booking that belongs to this trip
    and is currently `CONFIRMED`; a booking that is on another trip or in any other
    status is rejected with `ERR_BOOKING_NOT_CONFIRMED`, while an id that names no
    booking at all is an `ERR_BOOKING_NOT_FOUND`."

    Design: Corner/errors/booking_state_ladder_names_the_specific_wrong_state_on_each_endpoint
    """
    world = setup_harbor_world(annual_inspection=False)
    trip = create_trip(world)
    offered = create_offered_booking(world, "rider-ann", party_size=2)
    requested = request_booking(world, "rider-bob", party_size=1)

    validate_error(api.dispatch_booking(offered["id"], DISPATCHER),
                   ApiErrorId.ERR_BOOKING_NOT_REQUESTED.value, 409)
    validate_error(
        api.confirm_booking(requested["id"], {"expected_trip_version": trip["version"]},
                            RIDER_BOB),
        ApiErrorId.ERR_BOOKING_NOT_OFFERED.value, 409,
    )
    validate_error(
        api.board_trip(trip["id"], {"boarded_booking_ids": [offered["id"]]},
                       world["master_headers"]),
        ApiErrorId.ERR_BOOKING_NOT_CONFIRMED.value, 409,
    )

    assert validate_success(api.get_booking(offered["id"], RIDER))["status"] == "OFFERED"
    assert validate_success(api.get_booking(requested["id"], RIDER_BOB))["status"] == "REQUESTED"
    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "SCHEDULED"
    assert refreshed["seats_committed"] == 0


def _three_on_demand_sailings():
    """Three ON_DEMAND sailings an hour apart, and one single-seat hail."""
    world = setup_harbor_world(annual_inspection=False)
    trips = [
        create_trip(world, service_mode="ON_DEMAND",
                    scheduled_departure_utc=f"2026-09-12T{hour}:00:00Z",
                    scheduled_arrival_utc=f"2026-09-12T{hour}:25:00Z")
        for hour in ("14", "15", "16")
    ]
    booking = request_booking(world, "rider-ann", service_mode="ON_DEMAND", party_size=1)
    return world, trips, booking


def test_declining_twice_cycles_the_booking_back_into_the_dispatch_pool(api):
    """PRD §3.6: "Where the booking lands depends on the round: the operator allows
    three offers in total, so when the incremented `offer_round` would still be below
    3 the booking cycles `OFFERED → REQUESTED` and returns to the dispatch pool with a
    larger exclusion set, and when the incremented `offer_round` reaches 3 the booking
    instead falls `OFFERED → UNFULFILLED`, which is terminal."
    PRD §3.6: "The current `trip_id` is appended to `declined_trip_ids`, `trip_id` is
    then cleared to null, `offer_round` increments by 1, and the booking's `version`
    increments by 1."

    Design: Difficulty/non_linear_state_machine/booking_cycles_offered_back_to_requested_twice_then_falls_to_unfulfilled
    """
    world, trips, booking = _three_on_demand_sailings()

    dispatch_booking(booking["id"])
    decline_booking(booking["id"], "rider-ann")
    dispatch_booking(booking["id"])
    after_second_decline = decline_booking(booking["id"], "rider-ann")

    assert after_second_decline["status"] == "REQUESTED", (
        f"The second decline is still below three offers, got "
        f"{after_second_decline['status']}"
    )
    assert after_second_decline["offer_round"] == 2
    assert after_second_decline["trip_id"] is None
    assert after_second_decline["declined_trip_ids"] == [trips[0]["id"], trips[1]["id"]], (
        f"The exclusion set must hold the two declined sailings in order, got "
        f"{after_second_decline['declined_trip_ids']}"
    )

    third_offer = dispatch_booking(booking["id"])
    assert third_offer["trip_id"] == trips[2]["id"], (
        f"Only the undeclined 16:00 sailing remains eligible, got {third_offer['trip_id']}"
    )


def test_third_decline_drops_the_booking_to_unfulfilled(api):
    """PRD §3.6: "Where the booking lands depends on the round: the operator allows
    three offers in total, so when the incremented `offer_round` would still be below
    3 the booking cycles `OFFERED → REQUESTED` and returns to the dispatch pool with a
    larger exclusion set, and when the incremented `offer_round` reaches 3 the booking
    instead falls `OFFERED → UNFULFILLED`, which is terminal."
    PRD §3.6: "No seats are committed by an offer."

    Design: Difficulty/non_linear_state_machine/booking_cycles_offered_back_to_requested_twice_then_falls_to_unfulfilled
    """
    world, trips, booking = _three_on_demand_sailings()

    for _round in range(2):
        dispatch_booking(booking["id"])
        decline_booking(booking["id"], "rider-ann")
    dispatch_booking(booking["id"])
    final = decline_booking(booking["id"], "rider-ann")

    assert_booking(final)
    assert final["status"] == "UNFULFILLED", (
        f"The third decline is terminal, got {final['status']}"
    )
    assert final["offer_round"] == 3
    assert final["trip_id"] is None
    assert final["declined_trip_ids"] == [t["id"] for t in trips], (
        f"All three sailings must be excluded, in decline order, got "
        f"{final['declined_trip_ids']}"
    )
    assert validate_success(api.get_trip(trips[2]["id"], DISPATCHER))["seats_committed"] == 0


def _reverse_direction_world():
    """One sailing outbound, one hail asking for the opposite direction."""
    world = setup_harbor_world(annual_inspection=False)
    trip = create_trip(world)
    booking = request_booking(world, "rider-ann",
                              origin_stop_id=world["stop2_id"],
                              destination_stop_id=world["stop1_id"],
                              party_size=1)
    return world, trip, booking


def test_dispatch_over_an_empty_candidate_pool_is_rejected(api):
    """PRD §3.6: "A trip enters the candidate pool only when every one of the
    following holds: it belongs to that operating day; its `operational_status` is
    `SCHEDULED`; its `service_mode` equals the booking's `service_mode`, so a
    `SCHEDULED` booking may only ever be offered a `SCHEDULED` trip and an
    `ON_DEMAND` booking only an `ON_DEMAND` trip; its `origin_stop_id` equals the
    booking's `origin_stop_id` and its `destination_stop_id` equals the booking's
    `destination_stop_id`; its id does not appear in the booking's
    `declined_trip_ids`; its `scheduled_departure_utc` is at or after the current
    logical-clock instant; the day's `posture` is `NORMAL` or `RESTRICTED`; and its
    `effective_capacity` minus its `seats_committed` is at least the booking's
    `party_size`."
    PRD §3.6: "If the pool is empty the request is rejected with
    `ERR_NO_ELIGIBLE_TRIP` and the booking is left completely untouched — `status`
    stays `REQUESTED`, `offer_round` unchanged, `declined_trip_ids` unchanged,
    `version` unchanged."

    Design: Difficulty/boundary_precision_check/dispatch_over_empty_candidate_pool_writes_nothing_to_the_booking
    """
    _world, _trip, booking = _reverse_direction_world()

    validate_error(api.dispatch_booking(booking["id"], DISPATCHER),
                   ApiErrorId.ERR_NO_ELIGIBLE_TRIP.value, 409)


def test_rejected_dispatch_leaves_every_booking_field_untouched(api):
    """PRD §3.6: "If the pool is empty the request is rejected with
    `ERR_NO_ELIGIBLE_TRIP` and the booking is left completely untouched — `status`
    stays `REQUESTED`, `offer_round` unchanged, `declined_trip_ids` unchanged,
    `version` unchanged."
    PRD §3.6: "No seats are committed by an offer."

    Design: Difficulty/boundary_precision_check/dispatch_over_empty_candidate_pool_writes_nothing_to_the_booking
    """
    _world, trip, booking = _reverse_direction_world()
    version_before = booking["version"]

    validate_error(api.dispatch_booking(booking["id"], DISPATCHER),
                   ApiErrorId.ERR_NO_ELIGIBLE_TRIP.value, 409)

    untouched = validate_success(api.get_booking(booking["id"], RIDER))
    assert untouched["status"] == "REQUESTED"
    assert untouched["offer_round"] == 0
    assert untouched["trip_id"] is None
    assert untouched["declined_trip_ids"] == []
    assert untouched["version"] == version_before, (
        f"A rejected dispatch must not bump the booking version: "
        f"{version_before} -> {untouched['version']}"
    )
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["seats_committed"] == 0


def _zone_and_balance_world():
    """An INNER pass with one ride left, offered a three-zone hop."""
    world = setup_harbor_world(
        annual_inspection=False,
        dock_b={"berth_count": 2},
        extra_stops_on_dock_b=[{"name": "Outer Point", "zone_index": 4,
                                "charted_depth_m": 5.50}],
    )
    outer_stop = world["extra_stops"][0]
    near_trip = create_trip(world)
    far_trip = create_trip(world, destination_stop_id=outer_stop["id"],
                           scheduled_departure_utc="2026-09-12T15:00:00Z",
                           scheduled_arrival_utc="2026-09-12T15:40:00Z")
    ride_pass = buy_ride_pass("rider-ann", zone_tier="INNER", rides_purchased=2,
                              purchase_price_cents=3000, valid_until="2026-12-31")
    create_confirmed_booking(world, "rider-ann", party_size=1,
                             ride_pass_id=ride_pass["id"])
    far_booking = create_offered_booking(world, "rider-ann", party_size=2,
                                         ride_pass_id=ride_pass["id"],
                                         destination_stop_id=outer_stop["id"])
    return world, near_trip, far_trip, ride_pass, far_booking


def test_pass_zone_coverage_is_reported_before_the_ride_balance(api):
    """PRD §3.6: "When a pass is tendered, four further conditions are checked, in the
    order given here: the pass's `zone_tier` must cover the zone span between the
    booking's origin and destination stops, else `ERR_PASS_ZONE_NOT_COVERED`; the
    pass's `valid_until` must not be earlier than the logical clock's calendar date,
    and a stale pass is moved `ACTIVE → EXPIRED` before `ERR_PASS_EXPIRED` is
    returned, so the rejection leaves a permanent trace on the pass row; the pass's
    `status` must be `ACTIVE`, else `ERR_PASS_NOT_ACTIVE`; and `rides_remaining` must
    be at least the booking's `party_size`, else `ERR_PASS_NO_RIDES_REMAINING`."
    PRD §2.8: "An `INNER` pass with zero rides left, tendered for a three-zone hop, is
    rejected with `ERR_PASS_ZONE_NOT_COVERED`, not `ERR_PASS_NO_RIDES_REMAINING`,
    because zone coverage is checked before the ride balance."

    Design: Difficulty/priority_pair_validation_conflict/pass_zone_referential_error_wins_over_pass_ride_balance_fiscal_error
    """
    _world, _near, far_trip, _ride_pass, far_booking = _zone_and_balance_world()

    response = api.confirm_booking(
        far_booking["id"], {"expected_trip_version": far_trip["version"]}, RIDER
    )

    error = validate_error(response, ApiErrorId.ERR_PASS_ZONE_NOT_COVERED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_PASS_NO_RIDES_REMAINING.value


def test_the_zone_rejection_leaves_the_pass_and_the_booking_alone(api):
    """PRD §2.8: "An `INNER` pass with zero rides left, tendered for a three-zone hop,
    is rejected with `ERR_PASS_ZONE_NOT_COVERED`, not `ERR_PASS_NO_RIDES_REMAINING`,
    because zone coverage is checked before the ride balance."
    PRD §3.5: "The tier determines the reach of the pass: `INNER` covers a zone span
    of at most 1, `OUTER` covers a zone span of at most 3, and `ALL_ZONE` covers any
    span at all."

    Design: Difficulty/priority_pair_validation_conflict/pass_zone_referential_error_wins_over_pass_ride_balance_fiscal_error
    """
    _world, _near, far_trip, ride_pass, far_booking = _zone_and_balance_world()

    validate_error(
        api.confirm_booking(far_booking["id"],
                            {"expected_trip_version": far_trip["version"]}, RIDER),
        ApiErrorId.ERR_PASS_ZONE_NOT_COVERED.value, 422,
    )

    untouched_pass = validate_success(api.get_ride_pass(ride_pass["id"], RIDER))
    assert untouched_pass["rides_remaining"] == 1, (
        f"The rejected confirmation must not take a ride, got "
        f"{untouched_pass['rides_remaining']}"
    )
    assert untouched_pass["status"] == "ACTIVE"
    assert validate_success(api.get_booking(far_booking["id"], RIDER))["status"] == "OFFERED"
    assert validate_success(api.get_trip(far_trip["id"], DISPATCHER))["seats_committed"] == 0
