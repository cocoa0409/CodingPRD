"""Two shared resources with deliberately opposite interval conventions."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_EVALUATOR_SLOT_CONFLICT,
    ERR_PICKUP_WINDOW_LATE,
    ERR_VEHICLE_NOT_ACCESSIBLE,
    ERR_VEHICLE_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_slot_mirror, assert_vehicle_counters
from test_helpers.fixtures import (
    create_applicant,
    create_slot,
    create_vehicle,
    scheduled_assessment,
    set_clock,
)
from test_helpers.test_users import ADMIN_HEADERS, CLERK_HEADERS


def _published_nine_to_ten_slot(api):
    """One slot staffed by eval-1 from 09:00 to 10:00 on 2026-08-05."""
    set_clock(api, "2026-08-01T00:00:00Z")
    return create_slot(
        api,
        site_name="Central Mobility Center",
        evaluator_user_id="eval-1",
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
        capacity=1,
        site_is_wheelchair_accessible=True,
    )


def _slot_payload_for_eval_one(starts_at, ends_at):
    return factories.assessment_slot_payload(
        site_name="Central Mobility Center",
        evaluator_user_id="eval-1",
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=1,
        site_is_wheelchair_accessible=True,
    )


def test_the_buffer_rejects_a_back_to_back_slot_and_a_ten_minute_gap(api):
    """A closed interval widened by fifteen minutes swallows both attempts.

    "The conflict test treats each slot as a closed interval expanded by that
    buffer on both sides: the new slot conflicts with an existing one when the new
    slot's start falls earlier than the existing slot's end extended forward by 15
    minutes **and** the existing slot's start falls earlier than the new slot's
    end extended forward by 15 minutes."

    "Note that back-to-back slots — where one ends exactly when the next begins —
    do conflict here, and a gap of exactly 15 minutes is the smallest gap that is
    accepted."

    Design: Difficulty/resource_temporal_overlap/evaluator_slot_closed_interval_plus_fifteen_minute_buffer
    """
    slot_a = _published_nine_to_ten_slot(api)

    validate_error(
        api.create_assessment_slot(
            _slot_payload_for_eval_one("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"),
            ADMIN_HEADERS,
        ),
        ERR_EVALUATOR_SLOT_CONFLICT,
        409,
    )
    validate_error(
        api.create_assessment_slot(
            _slot_payload_for_eval_one("2026-08-05T10:10:00Z", "2026-08-05T11:10:00Z"),
            ADMIN_HEADERS,
        ),
        ERR_EVALUATOR_SLOT_CONFLICT,
        409,
    )

    slot_a = validate_success(api.get_assessment_slot(slot_a["id"], ADMIN_HEADERS))
    assert_slot_mirror(slot_a, booked_count=0, status="OPEN")


def test_a_fifteen_minute_gap_is_accepted_and_a_second_evaluator_may_overlap(api):
    """The buffer closes at exactly fifteen minutes and is scoped to one evaluator.

    "Evaluators need turnaround time between appointments, so two slots staffed by
    the same `evaluator_user_id` must be separated by a mandatory quarter-hour
    buffer."

    "A new slot always begins with `booked_count` zero and `status` `OPEN`."

    Design: Difficulty/resource_temporal_overlap/evaluator_slot_closed_interval_plus_fifteen_minute_buffer
    """
    _published_nine_to_ten_slot(api)

    accepted = validate_success(
        api.create_assessment_slot(
            _slot_payload_for_eval_one("2026-08-05T10:15:00Z", "2026-08-05T11:15:00Z"),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "OPEN"
    assert accepted["booked_count"] == 0

    other_evaluator = validate_success(
        api.create_assessment_slot(
            factories.assessment_slot_payload(
                site_name="East Branch Center",
                evaluator_user_id="eval-2",
                starts_at="2026-08-05T09:00:00Z",
                ends_at="2026-08-05T10:00:00Z",
                capacity=1,
                site_is_wheelchair_accessible=False,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert other_evaluator["evaluator_user_id"] == "eval-2"
    assert other_evaluator["status"] == "OPEN"


def _wheelchair_rider_with_a_one_position_vehicle(api):
    """A scheduled wheelchair assessment plus a vehicle with a single position."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Bea Tomlin",
        date_of_birth="1955-08-23",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="MANUAL_WHEELCHAIR",
    )
    context = scheduled_assessment(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=30,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        booking_overrides={"requires_wheelchair_position": True},
    )
    context["vehicle"] = create_vehicle(
        api,
        vehicle_number="V-0002",
        wheelchair_positions=1,
        ambulatory_seats=2,
        status="IN_SERVICE",
    )
    return context


def _book(api, context, start, end, wheelchair):
    return api.create_transportation_booking(
        factories.transportation_booking_payload(
            context["assessment"]["id"],
            context["vehicle"]["id"],
            pickup_window_start=start,
            pickup_window_end=end,
            requires_wheelchair_position=wheelchair,
        ),
        CLERK_HEADERS,
    )


def test_two_touching_wheelchair_windows_both_fit_a_single_position_vehicle(api):
    """Half-open windows that merely touch never overlap, so both reserve.

    "The window-capacity test treats pickup windows as half-open intervals that
    include their start and exclude their end. Two bookings overlap when the first
    one's start falls strictly before the second one's end and the second one's
    start falls strictly before the first one's end; consequently two windows that
    merely touch — one ending exactly when the other begins — never overlap and
    are always allowed."

    Design: Difficulty/resource_temporal_overlap/vehicle_half_open_window_with_aggregate_wheelchair_lane_capacity
    """
    context = _wheelchair_rider_with_a_one_position_vehicle(api)

    first = validate_success(
        _book(api, context, "2026-08-05T08:00:00Z", "2026-08-05T08:45:00Z", True), 201
    )
    assert first["status"] == "RESERVED"
    second = validate_success(
        _book(api, context, "2026-08-05T08:45:00Z", "2026-08-05T09:00:00Z", True), 201
    )
    assert second["status"] == "RESERVED"

    vehicle = validate_success(
        api.get_vehicle(context["vehicle"]["id"], ADMIN_HEADERS)
    )
    assert_vehicle_counters(vehicle, wheelchair=2, ambulatory=0)


def test_a_window_overlapping_both_reservations_is_refused_in_one_lane_only(api):
    """The lanes are counted separately, so the ambulatory copy still fits.

    "The two lanes on a vehicle are counted separately: a booking that needs a
    securement position is measured against the vehicle's `wheelchair_positions`,
    and one that does not is measured against its `ambulatory_seats`."

    "The server counts the vehicle's bookings that are still in `RESERVED`, that
    sit in the same lane as the new request, and that overlap the requested
    window; if adding the new booking to that set would exceed the lane's
    capacity, the reservation is refused."

    Design: Difficulty/resource_temporal_overlap/vehicle_half_open_window_with_aggregate_wheelchair_lane_capacity
    """
    context = _wheelchair_rider_with_a_one_position_vehicle(api)
    validate_success(
        _book(api, context, "2026-08-05T08:00:00Z", "2026-08-05T08:45:00Z", True), 201
    )
    validate_success(
        _book(api, context, "2026-08-05T08:45:00Z", "2026-08-05T09:00:00Z", True), 201
    )

    blocked = validate_error(
        _book(api, context, "2026-08-05T08:44:00Z", "2026-08-05T09:00:00Z", True),
        ERR_VEHICLE_WINDOW_CONFLICT,
        409,
    )
    assert blocked["error_id"] != ERR_VEHICLE_NOT_ACCESSIBLE
    assert blocked["error_id"] != ERR_PICKUP_WINDOW_LATE

    ambulatory = validate_success(
        _book(api, context, "2026-08-05T08:44:00Z", "2026-08-05T09:00:00Z", False), 201
    )
    assert ambulatory["status"] == "RESERVED"
    assert ambulatory["requires_wheelchair_position"] is False

    vehicle = validate_success(
        api.get_vehicle(context["vehicle"]["id"], ADMIN_HEADERS)
    )
    assert_vehicle_counters(vehicle, wheelchair=2, ambulatory=1)

    _bookings, meta = validate_paginated(
        api.list_transportation_bookings(
            CLERK_HEADERS, params={"vehicle_id": context["vehicle"]["id"]}
        )
    )
    assert meta["total_count"] == 3
