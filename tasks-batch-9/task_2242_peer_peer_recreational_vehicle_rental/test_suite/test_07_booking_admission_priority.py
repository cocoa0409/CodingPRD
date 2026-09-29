"""Which refusal a booking request earns when several gates fail at once, and
where the listing calendar's asymmetric edges actually fall."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN_HEADERS,
    PlanTier,
    TripStatus,
    VehicleClass,
    factories,
    fixtures,
    make_renter_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

RENTER_YOUNG = {
    "display_name": "Cody Young",
    "email": "cody@rvshare.test",
    "date_of_birth": "2005-01-15",
    "license_state_code": "OR",
}
RENTER_D = {
    "display_name": "Dana Pointy",
    "email": "dana@rvshare.test",
    "date_of_birth": "1988-03-04",
    "license_state_code": "OR",
}
RENTER_E = {
    "display_name": "Eli Borderline",
    "email": "eli@rvshare.test",
    "date_of_birth": "1986-11-22",
    "license_state_code": "OR",
}


def _book_as(api, world, renter_id, **overrides):
    """A booking request against the canonical listing from a chosen renter."""
    return api.create_booking(
        factories.booking_payload(
            world.listing_id, renter_id, world.plan_id, world.policy_id, **overrides
        ),
        make_renter_headers(renter_id),
    )


def _class_a_only_plan(api):
    """A plan whose eligible classes leave the canonical trailer out."""
    return fixtures.create_protection_plan(
        api,
        tier=PlanTier.PREMIUM,
        daily_premium_cents=5200,
        premium_pct_of_base_bp=1800,
        deductible_cents=100000,
        coverage_ceiling_cents=3000000,
        excluded_causes=[],
        eligible_vehicle_classes=[VehicleClass.CLASS_A, VehicleClass.CLASS_C],
    )


def _booking_count(api, listing_id=None, renter_id=None):
    params = {}
    if listing_id is not None:
        params["listing_id"] = listing_id
    if renter_id is not None:
        params["renter_id"] = renter_id
    _rows, meta = validate_paginated(
        api.list_bookings(factories.page_params(**params), PLATFORM_ADMIN_HEADERS)
    )
    return meta["total_count"]


def test_a_suspended_listing_answers_before_the_renters_age(api):
    """PRD 2.8: "the error a client receives must be the *first* failure in the
    ladder below, not an arbitrary one." Rung 14 is "**Listing bookable** — the
    listing referenced by the request has `listing_status` equal to `LISTED`,
    otherwise `ERR_LISTING_NOT_BOOKABLE` (409). Applies to booking request, owner
    approval and renter confirmation." while the age rule waits at rung 16:
    "**Renter age** — `ERR_RENTER_AGE_BELOW_MINIMUM` (422), at booking request."

    Design: Difficulty/priority_pair_validation_conflict/suspended_listing_409_outranks_underage_renter_422
    """
    world = fixtures.seed_marketplace(api)
    young = fixtures.create_renter(api, **RENTER_YOUNG)
    validate_success(
        api.suspend_listing(
            world.listing_id,
            factories.listing_suspend_payload(),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )

    response = _book_as(api, world, young["id"])
    validate_error(response, ApiErrorId.LISTING_NOT_BOOKABLE, 409)

    assert _booking_count(api, renter_id=young["id"]) == 0


def test_reinstating_the_listing_exposes_the_age_gate_on_the_same_body(api):
    """PRD 3.5: "The renter's whole-year age at the booking's `start_date` —
    recorded on the booking as `renter_age_years_at_start`, computed from the
    renter's `date_of_birth` to `start_date` and truncated downward to whole years —
    must be at least the listing's `min_renter_age`, otherwise
    `ERR_RENTER_AGE_BELOW_MINIMUM`." The body never changes; only the parent
    listing's state does, and PRD 2.8 puts that state ahead of the age: "Implementations
    must evaluate in exactly this sequence, stopping at the first failure."

    Design: Difficulty/priority_pair_validation_conflict/suspended_listing_409_outranks_underage_renter_422
    """
    world = fixtures.seed_marketplace(api)
    young = fixtures.create_renter(api, **RENTER_YOUNG)
    validate_success(
        api.suspend_listing(
            world.listing_id,
            factories.listing_suspend_payload(),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )
    validate_error(
        _book_as(api, world, young["id"]), ApiErrorId.LISTING_NOT_BOOKABLE, 409
    )

    reinstated = validate_success(
        api.reinstate_listing(world.listing_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert reinstated["listing_status"] == "LISTED"

    response = _book_as(api, world, young["id"])
    validate_error(response, ApiErrorId.RENTER_AGE_BELOW_MINIMUM, 422)

    assert _booking_count(api, renter_id=young["id"]) == 0


def test_the_rolling_point_ceiling_answers_before_the_towing_lookup(api):
    """PRD 2.8 separates two refusals that share a status code — rung 18 is
    "**Driving-record point ceiling** — `ERR_DRIVING_RECORD_POINTS_EXCEEDED` (422),
    at booking request." and rung 19 is "**Towing experience present** —
    `ERR_TOWING_EXPERIENCE_MISSING` (422), at booking request." — and insists that
    "the order in which they are evaluated is part of the contract". A renter with
    four in-window two-point checks and no towing credential violates both.

    Design: Difficulty/priority_pair_validation_conflict/rolling_driving_points_422_outranks_missing_towing_verification_422
    """
    world = fixtures.seed_marketplace(api)
    dana = fixtures.seed_renter_with_driving_history(
        api,
        [
            (2, "2024-01-15T00:00:00Z"),
            (2, "2025-02-20T00:00:00Z"),
            (2, "2026-03-10T00:00:00Z"),
            (2, "2026-07-01T00:00:00Z"),
        ],
        towing_result=None,
        **RENTER_D,
    )

    response = _book_as(api, world, dana["id"])
    validate_error(response, ApiErrorId.DRIVING_RECORD_POINTS_EXCEEDED, 422)

    renter = validate_success(api.get_renter(dana["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert renter["driving_record_points"] == 8
    assert renter["driving_record_status"] == "MINOR"


def test_exactly_six_points_lets_the_missing_towing_check_surface(api):
    """PRD 3.5 admits the boundary — "The renter's rolling `driving_record_points`
    must be at most six" — and then the next rung bites: "When the listing's
    `requires_towing` is true, the renter's `towing_verified_tier` must be something
    other than `NONE`, otherwise `ERR_TOWING_EXPERIENCE_MISSING`." Both renters lack
    a towing check, so only the point total decides which code appears.

    Design: Difficulty/priority_pair_validation_conflict/rolling_driving_points_422_outranks_missing_towing_verification_422
    """
    world = fixtures.seed_marketplace(api)
    eli = fixtures.seed_renter_with_driving_history(
        api,
        [
            (2, "2024-05-05T00:00:00Z"),
            (2, "2025-06-06T00:00:00Z"),
            (2, "2026-07-02T00:00:00Z"),
        ],
        towing_result=None,
        **RENTER_E,
    )
    renter = validate_success(api.get_renter(eli["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert renter["driving_record_points"] == 6

    response = _book_as(api, world, eli["id"])
    validate_error(response, ApiErrorId.TOWING_EXPERIENCE_MISSING, 422)

    assert _booking_count(api, renter_id=eli["id"]) == 0


def test_a_start_inside_the_turnaround_buffer_answers_before_the_plan_class(api):
    """PRD 3.5: "Collision is evaluated on the half-open date range extended by a
    one-night turnaround buffer after the existing booking's checkout: the two
    bookings collide when the new booking's `start_date` falls strictly before one
    day after the existing booking's `end_date`, **and** the new booking's `end_date`
    falls strictly after the existing booking's `start_date`." PRD 2.8 puts that
    collision at rung 24 — "**Listing dates available** —
    `ERR_LISTING_DATES_UNAVAILABLE` (409), at booking request." — ten rungs ahead of
    "**Plan covers the class** — `ERR_PLAN_CLASS_NOT_ELIGIBLE` (422), at booking
    request."

    Design: Difficulty/priority_pair_validation_conflict/date_collision_409_outranks_plan_class_ineligibility_422
    """
    world = fixtures.seed_marketplace(api)
    fixtures.seed_confirmed_booking(api, world)
    narrow_plan = _class_a_only_plan(api)

    response = api.create_booking(
        factories.booking_payload(
            world.listing_id,
            world.renter_id,
            narrow_plan["id"],
            world.policy_id,
            start_date="2026-09-02",
            end_date="2026-09-04",
            declared_miles=150,
            declared_generator_hours=4.0,
        ),
        world.renter_headers,
    )
    validate_error(response, ApiErrorId.LISTING_DATES_UNAVAILABLE, 409)

    assert _booking_count(api, listing_id=world.listing_id) == 1


def test_clearing_the_buffer_exposes_the_ineligible_plan_class(api):
    """PRD 3.5: "The listing's `vehicle_class` must be a member of the chosen
    protection plan's `eligible_vehicle_classes`, otherwise
    `ERR_PLAN_CLASS_NOT_ELIGIBLE`." The plan choice is unchanged from the colliding
    attempt; only the start date moves past "one day after the existing booking's
    `end_date`", which retires the higher-priority conflict.

    Design: Difficulty/priority_pair_validation_conflict/date_collision_409_outranks_plan_class_ineligibility_422
    """
    world = fixtures.seed_marketplace(api)
    fixtures.seed_confirmed_booking(api, world)
    narrow_plan = _class_a_only_plan(api)
    validate_error(
        api.create_booking(
            factories.booking_payload(
                world.listing_id,
                world.renter_id,
                narrow_plan["id"],
                world.policy_id,
                start_date="2026-09-02",
                end_date="2026-09-04",
                declared_miles=150,
                declared_generator_hours=4.0,
            ),
            world.renter_headers,
        ),
        ApiErrorId.LISTING_DATES_UNAVAILABLE,
        409,
    )

    response = api.create_booking(
        factories.booking_payload(
            world.listing_id,
            world.renter_id,
            narrow_plan["id"],
            world.policy_id,
            start_date="2026-09-03",
            end_date="2026-09-05",
            declared_miles=150,
            declared_generator_hours=4.0,
        ),
        world.renter_headers,
    )
    validate_error(response, ApiErrorId.PLAN_CLASS_NOT_ELIGIBLE, 422)

    assert _booking_count(api, listing_id=world.listing_id) == 1


def test_a_start_on_the_existing_end_date_still_collides(api):
    """PRD 3.5: "the two bookings collide when the new booking's `start_date` falls
    strictly before one day after the existing booking's `end_date`, **and** the new
    booking's `end_date` falls strictly after the existing booking's `start_date`."
    A live booking is one "whose `trip_status` is `REQUESTED`, `OWNER_APPROVED`,
    `CONFIRMED`, `IN_TRIP` or `RETURNED`", so the turnaround night after a confirmed
    trip is spoken for and the night after that is free.

    Design: Difficulty/resource_temporal_overlap/listing_calendar_is_half_open_forward_and_buffered_only_after_the_end_date
    """
    world = fixtures.seed_marketplace(api)
    fixtures.seed_confirmed_booking(api, world)

    validate_error(
        api.create_booking(
            factories.booking_payload(
                world.listing_id,
                world.renter_id,
                world.plan_id,
                world.policy_id,
                start_date="2026-09-02",
                end_date="2026-09-04",
                declared_miles=150,
                declared_generator_hours=4.0,
            ),
            world.renter_headers,
        ),
        ApiErrorId.LISTING_DATES_UNAVAILABLE,
        409,
    )

    accepted = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id,
                world.renter_id,
                world.plan_id,
                world.policy_id,
                start_date="2026-09-03",
                end_date="2026-09-05",
                declared_miles=150,
                declared_generator_hours=4.0,
            ),
            world.renter_headers,
        ),
        201,
    )
    assert accepted["nights"] == 2
    assert accepted["trip_status"] == TripStatus.REQUESTED

    assert _booking_count(api, listing_id=world.listing_id) == 2


def test_a_booking_ending_on_the_existing_start_date_does_not_collide(api):
    """PRD 3.5 buffers one edge only: the collision needs "the new booking's
    `end_date` falls strictly after the existing booking's `start_date`", with no
    turnaround allowance on that side. PRD 3.5 also fixes what a date range means:
    "The sharing period is the half-open date range that includes `start_date` and
    excludes `end_date`, so `nights` is simply the number of days between the two
    dates".

    Design: Difficulty/resource_temporal_overlap/listing_calendar_is_half_open_forward_and_buffered_only_after_the_end_date
    """
    world = fixtures.seed_marketplace(api)
    fixtures.seed_confirmed_booking(api, world)

    accepted = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id,
                world.renter_id,
                world.plan_id,
                world.policy_id,
                start_date="2026-08-27",
                end_date="2026-08-29",
                declared_miles=150,
                declared_generator_hours=4.0,
            ),
            world.renter_headers,
        ),
        201,
    )

    assert accepted["nights"] == 2
    assert accepted["trip_status"] == TripStatus.REQUESTED
    assert _booking_count(api, listing_id=world.listing_id) == 2


def test_a_start_before_the_clock_and_a_zero_length_range_are_both_refused(api):
    """PRD 3.5: "Separately, `start_date` must fall strictly before `end_date` and
    must be on or after the current logical-clock date; violating either yields
    `ERR_INVALID_DATE_RANGE`." The comparison is against the injected clock, because
    PRD 2.5 says "Every date, deadline, expiry, lookback window and elapsed-time
    computation in this system evaluates against a **logical clock**, never against
    real wall-clock time."

    Design: Corner/validations/booking_dates_before_the_clock_or_out_of_order_are_rejected
    """
    world = fixtures.seed_marketplace(api)

    before_the_clock = api.create_booking(
        factories.booking_payload(
            world.listing_id,
            world.renter_id,
            world.plan_id,
            world.policy_id,
            start_date="2026-07-31",
            end_date="2026-08-04",
        ),
        world.renter_headers,
    )
    validate_error(before_the_clock, ApiErrorId.INVALID_DATE_RANGE, 422)

    zero_length = api.create_booking(
        factories.booking_payload(
            world.listing_id,
            world.renter_id,
            world.plan_id,
            world.policy_id,
            start_date="2026-09-05",
            end_date="2026-09-05",
        ),
        world.renter_headers,
    )
    validate_error(zero_length, ApiErrorId.INVALID_DATE_RANGE, 422)

    assert _booking_count(api, listing_id=world.listing_id) == 0
