"""Two conserved quantities that must survive a release and a mid-term rescind."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_BOOKING_NOT_CANCELLABLE,
    ERR_VEHICLE_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_day_ledger_conserved,
    assert_ladder_duration,
    assert_sweep_counters,
    assert_vehicle_counters,
)
from test_helpers.fixtures import (
    create_applicant,
    create_vehicle,
    rider_responded_proceeding,
    run_day_close,
    scheduled_assessment,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_2_HEADERS,
    CONDUCT_OFFICER_HEADERS,
)


def _scooter_rider_with_a_single_position_vehicle(api):
    """A scheduled wheelchair ride waiting on a vehicle with one position."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Cyrus Adeleke",
        date_of_birth="1961-10-09",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="SCOOTER",
    )
    context = scheduled_assessment(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=80,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        booking_overrides={"requires_wheelchair_position": True},
    )
    context["vehicle"] = create_vehicle(
        api,
        vehicle_number="V-0003",
        wheelchair_positions=1,
        ambulatory_seats=2,
        status="IN_SERVICE",
    )
    assert_vehicle_counters(context["vehicle"], wheelchair=0, ambulatory=0)
    return context


def _reserve_the_eight_to_nine_window(api, context):
    return api.create_transportation_booking(
        factories.transportation_booking_payload(
            context["assessment"]["id"],
            context["vehicle"]["id"],
            pickup_window_start="2026-08-05T08:00:00Z",
            pickup_window_end="2026-08-05T09:00:00Z",
            requires_wheelchair_position=True,
        ),
        CLERK_HEADERS,
    )


def test_cancelling_a_reserved_ride_returns_the_lane_counter_to_its_prior_value(api):
    """The counter goes up by one, refuses a rival, and comes back to zero.

    "The booking is created in `RESERVED` with `cancelled_reason` null, and it
    increments `open_wheelchair_reservations` on the vehicle when it consumes a
    securement position and `open_ambulatory_reservations` when it does not."

    "Cancellation decrements exactly the one vehicle counter the booking had
    consumed — `open_wheelchair_reservations` when the booking needed a securement
    position, `open_ambulatory_reservations` otherwise — returning it to its
    pre-booking value."

    Design: Difficulty/compensating_invariant/vehicle_open_reservation_counter_restored_by_booking_cancel
    """
    context = _scooter_rider_with_a_single_position_vehicle(api)
    vehicle_id = context["vehicle"]["id"]

    booking = validate_success(_reserve_the_eight_to_nine_window(api, context), 201)
    assert booking["status"] == "RESERVED"
    assert booking["cancelled_reason"] is None
    assert_vehicle_counters(
        validate_success(api.get_vehicle(vehicle_id, ADMIN_HEADERS)),
        wheelchair=1,
        ambulatory=0,
    )

    validate_error(
        _reserve_the_eight_to_nine_window(api, context),
        ERR_VEHICLE_WINDOW_CONFLICT,
        409,
    )
    assert_vehicle_counters(
        validate_success(api.get_vehicle(vehicle_id, ADMIN_HEADERS)),
        wheelchair=1,
        ambulatory=0,
    )

    cancelled = validate_success(
        api.cancel_transportation_booking(
            booking["id"],
            factories.booking_cancel_payload(
                cancelled_reason="Rider arranged their own ride"
            ),
            CLERK_HEADERS,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "Rider arranged their own ride"
    assert_vehicle_counters(
        validate_success(api.get_vehicle(vehicle_id, ADMIN_HEADERS)),
        wheelchair=0,
        ambulatory=0,
    )


def test_the_released_lane_takes_an_identical_rebooking_but_not_a_second_cancel(api):
    """A cancelled booking stops occupying the lane and stops being cancellable.

    "Bookings in `CANCELLED`, `COMPLETED` or `NO_SHOW_CLOSED` never occupy a lane."

    "Only a booking still in `RESERVED` is cancellable; anything else is
    `ERR_BOOKING_NOT_CANCELLABLE` (409)."

    Design: Difficulty/compensating_invariant/vehicle_open_reservation_counter_restored_by_booking_cancel
    """
    context = _scooter_rider_with_a_single_position_vehicle(api)
    vehicle_id = context["vehicle"]["id"]

    first = validate_success(_reserve_the_eight_to_nine_window(api, context), 201)
    validate_success(
        api.cancel_transportation_booking(
            first["id"],
            factories.booking_cancel_payload(
                cancelled_reason="Rider arranged their own ride"
            ),
            CLERK_HEADERS,
        )
    )

    rebooking = validate_success(_reserve_the_eight_to_nine_window(api, context), 201)
    assert rebooking["status"] == "RESERVED"
    assert_vehicle_counters(
        validate_success(api.get_vehicle(vehicle_id, ADMIN_HEADERS)),
        wheelchair=1,
        ambulatory=0,
    )

    _bookings, meta = validate_paginated(
        api.list_transportation_bookings(CLERK_HEADERS, params={"vehicle_id": vehicle_id})
    )
    assert meta["total_count"] == 2

    validate_error(
        api.cancel_transportation_booking(
            first["id"],
            factories.booking_cancel_payload(cancelled_reason="Duplicate cancel"),
            CLERK_HEADERS,
        ),
        ERR_BOOKING_NOT_CANCELLABLE,
        409,
    )
    assert_vehicle_counters(
        validate_success(api.get_vehicle(vehicle_id, ADMIN_HEADERS)),
        wheelchair=1,
        ambulatory=0,
    )


def _upheld_seven_day_suspension(api):
    """A first-offence suspension upheld to start on 2026-09-01."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Ivy Castellanos",
        date_of_birth="1968-03-16",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = rider_responded_proceeding(api, applicant=rider)

    before = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert before["suspension_days_ledger_total"] == 0
    assert before["prior_upheld_suspension_count"] == 0

    context["proceeding"] = validate_success(
        api.decide_suspension(
            context["proceeding"]["id"],
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-01"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        )
    )
    return context


def test_an_upheld_suspension_parks_its_whole_term_in_days_forgiven_until_it_starts(api):
    """Before the start date nothing is served, yet the ledger already carries it.

    "One in `UPHELD_PENDING` has `days_served` zero, so its whole `duration_days`
    sits in `days_forgiven` until it starts."

    "Finally the rider's `prior_upheld_suspension_count` increases by one and
    `suspension_days_ledger_total` grows by `duration_days`."

    Design: Difficulty/compensating_invariant/suspension_day_ledger_conserved_across_mid_service_rescind
    """
    context = _upheld_seven_day_suspension(api)
    proceeding = context["proceeding"]
    rider_id = context["applicant"]["id"]

    assert proceeding["status"] == "UPHELD_PENDING"
    assert_ladder_duration(proceeding, prior_upheld_count=0)
    assert proceeding["suspension_end_date"] == "2026-09-07"
    assert proceeding["days_served"] == 0
    assert proceeding["days_forgiven"] == 7
    assert_day_ledger_conserved(proceeding)

    rider = validate_success(api.get_applicant(rider_id, CONDUCT_OFFICER_HEADERS))
    assert rider["suspension_days_ledger_total"] == 7
    assert rider["prior_upheld_suspension_count"] == 1

    set_clock(api, "2026-09-01T00:00:00Z")
    sweep = run_day_close(api)
    assert_sweep_counters(sweep, proceedings_advanced_count=1)

    active = validate_success(
        api.get_suspension_proceeding(proceeding["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert active["status"] == "ACTIVE"
    assert active["days_served"] == 1
    assert active["days_forgiven"] == 6
    assert_day_ledger_conserved(active)
    rider = validate_success(api.get_applicant(rider_id, CONDUCT_OFFICER_HEADERS))
    assert rider["service_status"] == "SUSPENDED"


def test_rescinding_on_day_three_moves_days_across_the_ledger_without_changing_it(api):
    """Four days move from served to forgiven and the total stays at seven.

    "Rescinding a suspension already running freezes `days_served` at the number of
    days already served, computed as the smaller of `duration_days` and the number
    of days from `suspension_start_date` through today's date counted inclusively —
    that is, the day difference plus one. `days_forgiven` takes the remainder,
    `duration_days` minus `days_served`. Rescinding one that has not yet started
    leaves `days_served` at zero and forgives the whole term. The rider's
    `service_status` returns to `ACTIVE`, `suspension_days_ledger_total` is left
    untouched, and the rider's `version` increments."

    "One in `VOID` after being rescinded mid-service keeps the `days_served` figure
    frozen at rescind time."

    Design: Difficulty/compensating_invariant/suspension_day_ledger_conserved_across_mid_service_rescind
    """
    context = _upheld_seven_day_suspension(api)
    proceeding_id = context["proceeding"]["id"]
    rider_id = context["applicant"]["id"]

    set_clock(api, "2026-09-01T00:00:00Z")
    run_day_close(api)

    set_clock(api, "2026-09-03T00:00:00Z")
    voided = validate_success(
        api.rescind_suspension(
            proceeding_id, factories.rescind_payload(), CONDUCT_OFFICER_HEADERS
        )
    )
    assert voided["status"] == "VOID"
    assert voided["days_served"] == 3
    assert voided["days_forgiven"] == 4
    assert_day_ledger_conserved(voided)
    assert voided["duration_days"] == 7

    rider = validate_success(api.get_applicant(rider_id, CONDUCT_OFFICER_HEADERS))
    assert rider["suspension_days_ledger_total"] == 7
    assert rider["service_status"] == "ACTIVE"
    assert rider["prior_upheld_suspension_count"] == 1

    set_clock(api, "2026-09-08T00:00:00Z")
    run_day_close(api)
    still_void = validate_success(
        api.get_suspension_proceeding(proceeding_id, CONDUCT_OFFICER_HEADERS)
    )
    assert still_void["status"] == "VOID"
    assert still_void["days_served"] == 3
    rider = validate_success(api.get_applicant(rider_id, CONDUCT_OFFICER_HEADERS))
    assert rider["suspension_days_ledger_total"] == 7
