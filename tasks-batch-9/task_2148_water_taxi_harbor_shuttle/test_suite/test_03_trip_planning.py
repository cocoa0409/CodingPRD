"""Planning a sailing: timetable validity, the layup calendar, and committed seats."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_seat_commitment,
    assert_trip,
    create_confirmed_booking,
    create_offered_booking,
    create_trip,
    create_trip_payload,
    request_booking,
    setup_harbor_world,
    suspend_day,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["harbor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_sailing_whose_arrival_equals_its_departure_is_rejected(api):
    """PRD §3.3: "The timetable itself is `scheduled_departure_utc` and
    `scheduled_arrival_utc`, both ISO 8601 UTC instants, the arrival strictly after
    the departure."
    PRD §2.8: "**Time windows.** A trip's `scheduled_arrival_utc` is strictly after
    its `scheduled_departure_utc`; a berth slot's `end_utc` is strictly after its
    `start_utc`; a vessel's `layup_end_date` is not earlier than its
    `layup_start_date`; and a completion's clock reading is strictly after the trip's
    `actual_departure_utc`."

    Design: Corner/validations/trip_whose_arrival_equals_its_departure_is_rejected
    """
    world = setup_harbor_world()

    response = api.create_trip(
        create_trip_payload(world["day_id"], world["vessel_id"], world["crew_id"],
                            world["stop1_id"], world["stop2_id"],
                            scheduled_departure_utc="2026-09-12T14:00:00Z",
                            scheduled_arrival_utc="2026-09-12T14:00:00Z"),
        DISPATCHER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_TIME_WINDOW.value, 422)

    _trips, meta = validate_paginated(
        api.list_trips(DISPATCHER, params={"service_day_id": world["day_id"]})
    )
    assert meta["total_count"] == 0, (
        f"A rejected timetable must not persist a trip, got {meta['total_count']}"
    )


def test_boarding_a_sailing_on_a_suspended_day_is_refused(api):
    """PRD §3.7: "The trip must be `SCHEDULED`, else `ERR_TRIP_NOT_SCHEDULED`, and
    the day's `posture` must not be `SUSPENDED`, else `ERR_SERVICE_SUSPENDED`."
    PRD §3.3: "The **posture ceiling** applies a percentage factor of 100 percent
    under `NORMAL`, 70 percent under `RESTRICTED`, and 0 percent under `SUSPENDED`:
    multiply `seat_capacity` by that percentage, divide by 100, and round the result
    down to a whole seat."

    Design: Corner/state_machines/board_a_trip_created_after_the_day_was_suspended_returns_service_suspended
    """
    world = setup_harbor_world()
    suspended_day = suspend_day(world["day_id"], manual_suspension=True)
    assert suspended_day["posture"] == "SUSPENDED"

    trip = create_trip(world)

    response = api.board_trip(trip["id"], {"boarded_booking_ids": []},
                             world["master_headers"])
    validate_error(response, ApiErrorId.ERR_SERVICE_SUSPENDED.value, 409)

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "SCHEDULED"
    assert refreshed["effective_capacity"] == 0, (
        f"A SUSPENDED day derates every trip to 0 seats, got "
        f"{refreshed['effective_capacity']}"
    )


def test_seats_committed_counts_only_confirmed_and_boarded_bookings(api):
    """PRD §3.6: "Either way the trip's `seats_committed` is recomputed as the sum of
    `party_size` over that trip's bookings whose `status` is exactly `CONFIRMED` or
    `BOARDED` — bookings in `OFFERED`, `REQUESTED`, `INTERRUPTED`, `UNFULFILLED`, or
    `COMPLETED` are all excluded from that sum — and both the trip's `version` and
    the booking's `version` increment by 1."
    PRD §2.9: "A trip's `seats_committed` always equals the sum of `party_size` over
    its bookings in `CONFIRMED` or `BOARDED`."

    Design: Corner/calculations/seats_committed_counts_only_confirmed_and_boarded_bookings
    """
    world = setup_harbor_world()
    trip = create_trip(world)

    confirmed = create_confirmed_booking(world, "rider-ann", party_size=3)
    offered = create_offered_booking(world, "rider-bob", party_size=2)
    requested = request_booking(world, "rider-cid", party_size=4)

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert_trip(refreshed)
    assert refreshed["seats_committed"] == 3, (
        f"Only the CONFIRMED 3-seat booking counts, got {refreshed['seats_committed']}"
    )
    assert refreshed["effective_capacity"] == 40
    assert confirmed["status"] == "CONFIRMED"
    assert offered["status"] == "OFFERED"
    assert requested["status"] == "REQUESTED"
    assert_seat_commitment(api, trip["id"], DISPATCHER)


def _layup_world():
    """A 30-seat hull laid up from 2026-11-01, on the last operable day before it."""
    return setup_harbor_world(
        vessel={"name": "Wintergull", "seat_capacity": 30, "draft_m": 1.10,
                "hull_class": "OFFSHORE", "required_endorsement": "MASTER_25T",
                "layup_start_date": "2026-11-01", "layup_end_date": "2027-03-31"},
        annual_inspection=False,
        service_day={"service_date": "2026-10-31", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
        clock="2026-10-31T06:00:00Z",
    )


def test_sailing_that_ends_the_day_before_the_layup_window_is_accepted(api):
    """PRD §3.3: "If either `layup_start_date` or `layup_end_date` is null there is
    no conflict and the trip may be created."
    PRD §3.3: "Otherwise, take the trip's first calendar day as the UTC date of
    `scheduled_departure_utc` and its last calendar day as the UTC date of
    `scheduled_arrival_utc`; the trip conflicts with the layup when its first day
    falls on or before `layup_end_date` and its last day falls on or after
    `layup_start_date`, and the creation is then rejected with `ERR_VESSEL_IN_LAYUP`."

    Design: Difficulty/resource_temporal_overlap/vessel_layup_closed_closed_date_window_rejects_a_trip_that_only_touches_its_first_day
    """
    world = _layup_world()

    trip = create_trip(world,
                       scheduled_departure_utc="2026-10-31T21:00:00Z",
                       scheduled_arrival_utc="2026-10-31T21:30:00Z")

    assert_trip(trip)
    assert trip["operational_status"] == "SCHEDULED"
    assert trip["effective_capacity"] == 30, (
        f"A 30-seat hull on a NORMAL day with 1.00 m clearance and a MASTER_100T "
        f"master must read 30 seats, got {trip['effective_capacity']}"
    )

    vessel = validate_success(api.get_vessel(world["vessel_id"], DISPATCHER))
    assert vessel["service_state"] == "IN_SERVICE"


def test_sailing_that_reaches_into_the_layup_window_is_rejected(api):
    """PRD §3.3: "Otherwise, take the trip's first calendar day as the UTC date of
    `scheduled_departure_utc` and its last calendar day as the UTC date of
    `scheduled_arrival_utc`; the trip conflicts with the layup when its first day
    falls on or before `layup_end_date` and its last day falls on or after
    `layup_start_date`, and the creation is then rejected with `ERR_VESSEL_IN_LAYUP`."
    PRD §3.3: "Because both ends of the layup window are inclusive, a trip whose
    departure date is exactly `layup_end_date` does conflict — a deliberate contrast
    with the berth rule in §3.4, where an occupancy ending exactly when the candidate
    begins does not by itself conflict."

    Design: Difficulty/resource_temporal_overlap/vessel_layup_closed_closed_date_window_rejects_a_trip_that_only_touches_its_first_day
    """
    world = _layup_world()
    create_trip(world,
                scheduled_departure_utc="2026-10-31T21:00:00Z",
                scheduled_arrival_utc="2026-10-31T21:30:00Z")

    response = api.create_trip(
        create_trip_payload(world["day_id"], world["vessel_id"], world["crew_id"],
                            world["stop1_id"], world["stop2_id"],
                            scheduled_departure_utc="2026-10-31T23:00:00Z",
                            scheduled_arrival_utc="2026-11-01T01:00:00Z"),
        DISPATCHER,
    )

    validate_error(response, ApiErrorId.ERR_VESSEL_IN_LAYUP.value, 409)

    vessel = validate_success(api.get_vessel(world["vessel_id"], DISPATCHER))
    assert vessel["service_state"] == "IN_SERVICE", (
        f"The clock is still outside the layup window, got {vessel['service_state']}"
    )

    _trips, meta = validate_paginated(
        api.list_trips(DISPATCHER, params={"vessel_id": world["vessel_id"]})
    )
    assert meta["total_count"] == 1, (
        f"Only the accepted sailing may exist, got {meta['total_count']}"
    )
