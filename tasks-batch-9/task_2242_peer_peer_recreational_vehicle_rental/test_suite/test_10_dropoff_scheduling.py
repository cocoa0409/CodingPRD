"""Campground drop-off windows: the capacity fork between a slot and the
waitlist, the buffered collision test, and the four gates on creation."""

from test_helpers import (
    ApiErrorId,
    AssignmentStatus,
    CampgroundStatus,
    DeliveryOption,
    LoyaltyTier,
    PLATFORM_ADMIN_HEADERS,
    VehicleClass,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_CAMPGROUND_ID = "00000000-0000-4000-8000-000000000000"
SECOND_WINDOW = ("2026-08-29T18:00:00Z", "2026-08-29T20:00:00Z")


def _dropoff_booking_on(api, world, listing_id, **overrides):
    """A REQUESTED drop-off booking against a nominated listing."""
    overrides.setdefault("delivery_option", DeliveryOption.CAMPGROUND_DROPOFF)
    return validate_success(
        api.create_booking(
            factories.booking_payload(
                listing_id,
                world.renter_id,
                world.plan_id,
                world.policy_id,
                **overrides,
            ),
            world.renter_headers,
        ),
        201,
    )


def _assignment_attempt(
    api,
    world,
    booking,
    campground_id,
    window_start,
    window_end,
    distance_miles=20,
):
    """The raw create call, so refusals can be inspected as well as successes."""
    return api.create_delivery_assignment(
        factories.delivery_assignment_payload(
            booking["id"],
            campground_id,
            window_start,
            window_end,
            distance_miles,
            booking["version"],
            setup_fee_cents=0,
        ),
        world.owner_headers,
    )


def _assignment_count(api, booking_id):
    _rows, meta = validate_paginated(
        api.list_delivery_assignments(
            factories.page_params(booking_id=booking_id), PLATFORM_ADMIN_HEADERS
        )
    )
    return meta["total_count"]


def test_the_second_dropoff_of_the_day_lands_on_the_waitlist(api):
    """PRD 3.6: "When the campground is `ACCEPTING` but the bucket for that
    `dropoff_date` already holds at least `daily_dropoff_capacity` scheduled
    assignments, the assignment lands in `WAITLISTED` instead — which is a normal
    outcome and not an error. A waitlisted assignment consumes no slot, leaves
    `scheduled_assignment_count` unchanged, and does not bill: the booking's
    `delivery_fee_cents` stays 0. The assignment's `promoted_from_waitlist` flag is
    false on creation".

    Design: Difficulty/non_linear_state_machine/delivery_assignment_forks_to_waitlisted_without_billing_or_slot
    """
    world = fixtures.seed_marketplace(api)
    campground = fixtures.seed_campground(api, daily_dropoff_capacity=1)
    _first, scheduled = fixtures.seed_scheduled_dropoff(
        api,
        world,
        campground_id=campground["id"],
        distance_miles=10,
        setup_fee_cents=0,
    )
    assert scheduled["status"] == AssignmentStatus.SCHEDULED
    assert scheduled["delivery_fee_cents"] == 15500

    second_listing = fixtures.add_second_listed_listing(api, world)
    second_booking = _dropoff_booking_on(api, world, second_listing["id"])

    waitlisted = validate_success(
        _assignment_attempt(
            api, world, second_booking, campground["id"], *SECOND_WINDOW
        ),
        201,
    )

    assert waitlisted["status"] == AssignmentStatus.WAITLISTED
    assert waitlisted["promoted_from_waitlist"] is False
    assert waitlisted["delivery_fee_cents"] == 19000

    site = validate_success(
        api.get_campground(campground["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert site["scheduled_assignment_count"] == 1


def test_a_waitlisted_window_bills_nothing_and_disturbs_no_other_booking(api):
    """PRD 3.6: "A waitlisted assignment consumes no slot, leaves
    `scheduled_assignment_count` unchanged, and does not bill: the booking's
    `delivery_fee_cents` stays 0." The billing that did happen belongs to the
    scheduled row alone, where "the booking's `delivery_fee_cents` is set to the
    assignment's `delivery_fee_cents`, and the booking's quote is recomputed through
    all six steps of §3.5 with that new delivery fee in play."

    Design: Difficulty/non_linear_state_machine/delivery_assignment_forks_to_waitlisted_without_billing_or_slot
    """
    world = fixtures.seed_marketplace(api)
    campground = fixtures.seed_campground(api, daily_dropoff_capacity=1)
    first_booking, scheduled = fixtures.seed_scheduled_dropoff(
        api,
        world,
        campground_id=campground["id"],
        distance_miles=10,
        setup_fee_cents=0,
    )
    second_listing = fixtures.add_second_listed_listing(api, world)
    second_booking = _dropoff_booking_on(api, world, second_listing["id"])
    validate_success(
        _assignment_attempt(
            api, world, second_booking, campground["id"], *SECOND_WINDOW
        ),
        201,
    )

    waiting = validate_success(
        api.get_booking(second_booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert waiting["delivery_fee_cents"] == 0
    assert waiting["quoted_total_cents"] == 146063

    billed = validate_success(
        api.get_booking(first_booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert billed["delivery_fee_cents"] == 15500
    assert billed["quoted_total_cents"] == 157643

    held = validate_success(
        api.get_delivery_assignment(scheduled["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert held["status"] == AssignmentStatus.SCHEDULED


def test_two_windows_separated_by_exactly_the_buffer_collide(api):
    """PRD 3.6: "A new window collides with an existing one when the new
    `window_start` falls at or before the existing `window_end` plus the buffer,
    **and** the new `window_end` falls at or after the existing `window_start` minus
    the buffer. Because the interval ends are closed and the buffer is applied on
    both sides, two windows that merely touch at a shared instant collide, and so do
    two windows separated by exactly the buffer. A collision is reported as
    `ERR_DROPOFF_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/campground_dropoff_windows_are_closed_intervals_with_a_symmetric_buffer
    """
    world = fixtures.seed_marketplace(api)
    campground = fixtures.seed_campground(
        api,
        name="Twin Pines RV Resort",
        daily_dropoff_capacity=2,
        dropoff_buffer_minutes=30,
    )
    fixtures.seed_scheduled_dropoff(
        api,
        world,
        campground_id=campground["id"],
        distance_miles=10,
        setup_fee_cents=0,
    )
    second_listing = fixtures.add_second_listed_listing(api, world)
    second_booking = _dropoff_booking_on(api, world, second_listing["id"])

    response = _assignment_attempt(
        api,
        world,
        second_booking,
        campground["id"],
        "2026-08-29T16:30:00Z",
        "2026-08-29T17:30:00Z",
    )
    validate_error(response, ApiErrorId.DROPOFF_WINDOW_CONFLICT, 409)

    site = validate_success(
        api.get_campground(campground["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert site["scheduled_assignment_count"] == 1

    untouched = validate_success(
        api.get_booking(second_booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert untouched["delivery_fee_cents"] == 0


def test_one_minute_past_the_buffer_takes_the_second_slot(api):
    """PRD 3.6: the collision needs the new `window_start` to fall "at or before the
    existing `window_end` plus the buffer", so a single minute beyond that instant
    clears the test and the free slot applies: "the number of `SCHEDULED` assignments
    already holding that campground and that `dropoff_date` is strictly fewer than the
    campground's `daily_dropoff_capacity`". The row then bills, and "The row's
    `dropoff_date` is derived as the UTC calendar date of `window_start` in
    `YYYY-MM-DD` form, and that date is the capacity bucket key."

    Design: Difficulty/resource_temporal_overlap/campground_dropoff_windows_are_closed_intervals_with_a_symmetric_buffer
    """
    world = fixtures.seed_marketplace(api)
    campground = fixtures.seed_campground(
        api,
        name="Twin Pines RV Resort",
        daily_dropoff_capacity=2,
        dropoff_buffer_minutes=30,
    )
    fixtures.seed_scheduled_dropoff(
        api,
        world,
        campground_id=campground["id"],
        distance_miles=10,
        setup_fee_cents=0,
    )
    second_listing = fixtures.add_second_listed_listing(api, world)
    second_booking = _dropoff_booking_on(api, world, second_listing["id"])

    scheduled = validate_success(
        _assignment_attempt(
            api,
            world,
            second_booking,
            campground["id"],
            "2026-08-29T16:31:00Z",
            "2026-08-29T17:31:00Z",
        ),
        201,
    )

    assert scheduled["status"] == AssignmentStatus.SCHEDULED
    assert scheduled["promoted_from_waitlist"] is False
    assert scheduled["delivery_fee_cents"] == 19000
    assert scheduled["dropoff_date"] == "2026-08-29"

    site = validate_success(
        api.get_campground(campground["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert site["scheduled_assignment_count"] == 2

    billed = validate_success(
        api.get_booking(second_booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert billed["delivery_fee_cents"] == 19000
    assert billed["quoted_total_cents"] == 161289


def test_scheduling_a_window_rewrites_the_whole_quote(api):
    """PRD 3.6: on landing in `SCHEDULED` "the campground's
    `scheduled_assignment_count` increases by one, the campground's `version`
    increments, the booking's `delivery_fee_cents` is set to the assignment's
    `delivery_fee_cents`, and the booking's quote is recomputed through all six steps
    of §3.5 with that new delivery fee in play." The fee itself is "the listing's
    `delivery_base_fee_cents`, plus the listing's `delivery_per_mile_cents` multiplied
    by the assignment's `distance_miles`, plus the assignment's `setup_fee_cents`".

    Design: Corner/state_machines/scheduling_an_assignment_rewrites_the_bookings_quote
    """
    world = fixtures.seed_marketplace(api)
    campground = fixtures.seed_campground(api)
    booking = fixtures.seed_dropoff_booking(api, world)
    approved = fixtures.approve_booking(api, world, booking["id"])
    assert approved["delivery_fee_cents"] == 0
    assert approved["quoted_total_cents"] == 146063

    scheduled = validate_success(
        _assignment_attempt(
            api,
            world,
            approved,
            campground["id"],
            "2026-08-29T14:00:00Z",
            "2026-08-29T16:00:00Z",
            distance_miles=10,
        ),
        201,
    )

    assert scheduled["status"] == AssignmentStatus.SCHEDULED
    assert scheduled["delivery_fee_cents"] == 15500
    assert scheduled["dropoff_date"] == "2026-08-29"
    assert scheduled["promoted_from_waitlist"] is False

    site = validate_success(
        api.get_campground(campground["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert site["scheduled_assignment_count"] == 1

    requoted = validate_success(
        api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert requoted["delivery_fee_cents"] == 15500
    assert requoted["loyalty_tier"] == LoyaltyTier.TIER_2
    assert requoted["loyalty_discount_cents"] == 10594
    assert requoted["service_fee_cents"] == 16890
    assert requoted["quoted_total_cents"] == 157643


def test_a_pickup_booking_accepts_no_dropoff_window(api):
    """PRD 3.6: "The booking's `delivery_option` must be `CAMPGROUND_DROPOFF`;
    creating an assignment for a `PICKUP` booking is refused with
    `ERR_DELIVERY_NOT_APPLICABLE`." PRD 3.5 explains why the fee stays where it is on
    such a booking: on `PICKUP` "`delivery_fee_cents` is 0, because no delivery
    assignment exists yet".

    Design: Corner/endpoints/delivery_assignment_on_a_pickup_booking_is_rejected
    """
    world = fixtures.seed_marketplace(api)
    campground = fixtures.seed_campground(api)
    booking = fixtures.seed_requested_booking(api, world)
    assert booking["delivery_option"] == DeliveryOption.PICKUP

    response = _assignment_attempt(
        api,
        world,
        booking,
        campground["id"],
        "2026-08-29T14:00:00Z",
        "2026-08-29T16:00:00Z",
        distance_miles=10,
    )
    validate_error(response, ApiErrorId.DELIVERY_NOT_APPLICABLE, 422)

    assert _assignment_count(api, booking["id"]) == 0

    stored = validate_success(
        api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["delivery_fee_cents"] == 0
    assert stored["quoted_total_cents"] == 146063


def test_an_unresolvable_campground_answers_before_the_delivery_option(api):
    """PRD 2.8 rung 6: "**Body foreign-key resolution** — every foreign key carried
    in the request body resolves, checked in the order the fields are listed for that
    operation in Section 3. The concrete code is again the per-entity 404: ...
    `campground_id` yields `ERR_CAMPGROUND_NOT_FOUND`". That sits thirty rungs above
    "**Delivery applicable** — `ERR_DELIVERY_NOT_APPLICABLE` (422), at
    delivery-assignment creation.", so an unknown campground on a `PICKUP` booking
    reports the missing row rather than the wrong delivery option.

    Design: Corner/endpoints/assignment_link_with_an_unknown_campground_is_not_found
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_requested_booking(api, world)

    response = _assignment_attempt(
        api,
        world,
        booking,
        UNKNOWN_CAMPGROUND_ID,
        "2026-08-29T14:00:00Z",
        "2026-08-29T16:00:00Z",
        distance_miles=10,
    )
    validate_error(response, ApiErrorId.CAMPGROUND_NOT_FOUND, 404)

    assert _assignment_count(api, booking["id"]) == 0


def test_a_registered_campground_reads_back_exactly_as_it_was_filed(api):
    """PRD 3.3: "A **campground** is registered with a `name` of 1 to 120 characters,
    a `state_code` of exactly two uppercase letters, a `max_rig_length_ft` between 10
    and 60 feet, a `daily_dropoff_capacity` of at least 1, a `dropoff_buffer_minutes`
    figure from 0 to 240, and an optional `status` that defaults to `ACCEPTING` and
    may otherwise be `CLOSED`. Only an `ACCEPTING` campground may receive drop-offs. A
    newly registered campground opens with `scheduled_assignment_count` at 0."

    Design: Corner/endpoints/campground_create_then_read_round_trips_every_stored_field
    """
    created = validate_success(
        api.create_campground(
            factories.campground_payload(
                name="Deschutes River Sites",
                state_code="OR",
                max_rig_length_ft=36,
                daily_dropoff_capacity=3,
                dropoff_buffer_minutes=45,
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )

    assert created["status"] == CampgroundStatus.ACCEPTING
    assert created["scheduled_assignment_count"] == 0
    assert created["version"] == 1

    fetched = validate_success(
        api.get_campground(created["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "Deschutes River Sites"
    assert fetched["state_code"] == "OR"
    assert fetched["max_rig_length_ft"] == 36
    assert fetched["daily_dropoff_capacity"] == 3
    assert fetched["dropoff_buffer_minutes"] == 45
    assert fetched["version"] == 1


def test_a_short_site_and_a_closed_site_share_one_refusal(api):
    """PRD 3.6: "The rig must fit and the site must be open: the listing's `length_ft`
    must be no greater than the campground's `max_rig_length_ft` and the campground's
    `status` must be `ACCEPTING`, or the request is refused with
    `ERR_RIG_LENGTH_EXCEEDS_CAMPGROUND`." PRD 3.3 states the same gate from the
    campground's side: "Only an `ACCEPTING` campground may receive drop-offs."

    Design: Corner/errors/campground_length_limit_and_closed_status_both_reject_the_dropoff
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_dropoff_booking(api, world)
    approved = fixtures.approve_booking(api, world, booking["id"])

    too_short = fixtures.seed_campground(
        api,
        name="Tiny Sites Only",
        max_rig_length_ft=25,
        daily_dropoff_capacity=5,
    )
    refused_for_length = _assignment_attempt(
        api,
        world,
        approved,
        too_short["id"],
        "2026-08-29T16:00:00Z",
        "2026-08-29T17:00:00Z",
        distance_miles=10,
    )
    validate_error(
        refused_for_length, ApiErrorId.RIG_LENGTH_EXCEEDS_CAMPGROUND, 422
    )

    shuttered = fixtures.seed_campground(
        api,
        name="Winterized Big Rig Park",
        max_rig_length_ft=50,
        daily_dropoff_capacity=5,
        status=CampgroundStatus.CLOSED,
    )
    refused_for_closure = _assignment_attempt(
        api,
        world,
        approved,
        shuttered["id"],
        "2026-08-29T16:00:00Z",
        "2026-08-29T17:00:00Z",
        distance_miles=10,
    )
    validate_error(
        refused_for_closure, ApiErrorId.RIG_LENGTH_EXCEEDS_CAMPGROUND, 422
    )

    assert _assignment_count(api, booking["id"]) == 0

    stored = validate_success(
        api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["delivery_fee_cents"] == 0


def test_a_listing_that_does_not_deliver_refuses_the_dropoff_option(api):
    """PRD 3.5: "when `delivery_option` is `CAMPGROUND_DROPOFF`, the listing's
    `delivery_offered` must be true, otherwise `ERR_DELIVERY_NOT_OFFERED`." PRD 3.2
    makes the flag opt-in: "Three delivery fields are optional: `delivery_offered`
    defaults to false, and `delivery_base_fee_cents` and `delivery_per_mile_cents`
    each default to 0 and must be non-negative."

    Design: Corner/errors/dropoff_requested_on_a_listing_that_does_not_deliver_is_rejected
    """
    world = fixtures.seed_marketplace(api)
    van = fixtures.add_second_listed_listing(
        api,
        world,
        nickname="Cascade Camper Van",
        vehicle_class=VehicleClass.CAMPER_VAN,
        gvwr_lbs=12000,
        length_ft=21,
        delivery_offered=False,
        delivery_base_fee_cents=0,
        delivery_per_mile_cents=0,
    )

    stored_listing = validate_success(
        api.get_listing(van["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored_listing["delivery_offered"] is False
    assert stored_listing["delivery_base_fee_cents"] == 0

    refused = api.create_booking(
        factories.booking_payload(
            van["id"],
            world.renter_id,
            world.plan_id,
            world.policy_id,
            delivery_option=DeliveryOption.CAMPGROUND_DROPOFF,
        ),
        world.renter_headers,
    )
    validate_error(refused, ApiErrorId.DELIVERY_NOT_OFFERED, 422)

    accepted = validate_success(
        api.create_booking(
            factories.booking_payload(
                van["id"],
                world.renter_id,
                world.plan_id,
                world.policy_id,
                delivery_option=DeliveryOption.PICKUP,
            ),
            world.renter_headers,
        ),
        201,
    )
    assert accepted["quoted_total_cents"] == 140698

    _rows, meta = validate_paginated(
        api.list_bookings(
            factories.page_params(listing_id=van["id"]), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 1
