"""Renter eligibility at booking time: the two driving-record numbers, the
six-point rolling ceiling, the eight-point block, and the towing credential
rules that only towed rigs impose."""

from test_helpers import (
    ApiErrorId,
    DrivingRecordStatus,
    LoyaltyTier,
    PLATFORM_ADMIN_HEADERS,
    QualificationResult,
    TowingTier,
    TripStatus,
    VehicleClass,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

RENTER_F = {
    "display_name": "Fern Sixpoint",
    "email": "fern@rvshare.test",
    "date_of_birth": "1985-04-04",
    "license_state_code": "OR",
}
RENTER_G = {
    "display_name": "Gus Sevenpoint",
    "email": "gus@rvshare.test",
    "date_of_birth": "1983-09-09",
    "license_state_code": "OR",
}
RENTER_CARA = {
    "display_name": "Cara Risky",
    "email": "cara@rvshare.test",
    "date_of_birth": "1990-03-02",
    "license_state_code": "WA",
}


def _book_as(api, world, listing_id, renter_id, **overrides):
    """A booking request issued by an arbitrary renter against a listing."""
    return api.create_booking(
        factories.booking_payload(
            listing_id, renter_id, world.plan_id, world.policy_id, **overrides
        ),
        fixtures.make_renter_headers(renter_id),
    )


def test_the_rolling_window_sums_every_check_while_the_snapshot_reads_the_newest(api):
    """PRD 3.4: "`driving_record_points` is the sum of `violation_points` over every
    driving-record check whose `checked_at` falls on or after the window's opening
    instant and on or before the clock. Because it sums, three separate two-point
    checks inside the window total six points, and a fourth breaches the ceiling."
    The status, by contrast, "reflects the single newest driving-record check,
    selected by descending `checked_at` and, where two checks share an instant, by
    descending `created_at`."

    Design: Difficulty/dual_variant_calc/driving_record_rolling_36m_gate_vs_most_recent_only_snapshot
    """
    world = fixtures.seed_marketplace(api)
    fixtures.add_driving_record_check(
        api,
        world.renter_id,
        violation_points=2,
        result=QualificationResult.CLEAR,
        checked_at="2024-09-01T00:00:00Z",
    )
    fixtures.add_driving_record_check(
        api,
        world.renter_id,
        violation_points=2,
        result=QualificationResult.MINOR,
        checked_at="2025-06-01T00:00:00Z",
    )

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )

    assert renter["driving_record_points"] == 6
    assert renter["driving_record_status"] == DrivingRecordStatus.CLEAR
    assert renter["towing_verified_tier"] == TowingTier.BASIC


def test_the_booking_freezes_the_newest_check_not_the_rolling_total(api):
    """PRD 3.4: "`renter_record_points_snapshot`, is frozen onto each booking at the
    moment the booking is requested and reads only the **single newest**
    driving-record check ... taking that one check's `violation_points`". The two
    numbers are deliberately allowed to disagree: "the very same renter can show six
    points on the rolling gate and two on the snapshot."

    Design: Difficulty/dual_variant_calc/driving_record_rolling_36m_gate_vs_most_recent_only_snapshot
    """
    world = fixtures.seed_marketplace(api)
    fixtures.add_driving_record_check(
        api,
        world.renter_id,
        violation_points=2,
        result=QualificationResult.CLEAR,
        checked_at="2024-09-01T00:00:00Z",
    )
    fixtures.add_driving_record_check(
        api,
        world.renter_id,
        violation_points=2,
        result=QualificationResult.MINOR,
        checked_at="2025-06-01T00:00:00Z",
    )

    booking = validate_success(
        _book_as(api, world, world.listing_id, world.renter_id), 201
    )

    assert booking["renter_record_points_snapshot"] == 2
    assert booking["trip_status"] == TripStatus.REQUESTED
    assert booking["base_subtotal_cents"] == 110896
    assert booking["premium_cents"] == 24951
    assert booking["quoted_total_cents"] == 146063


def test_exactly_six_rolling_points_are_admitted(api):
    """PRD 3.5: "The renter's rolling `driving_record_points` must be at most six,
    and a renter above six is rejected with `ERR_DRIVING_RECORD_POINTS_EXCEEDED` —
    note that this gate reads the rolling three-year sum, not the snapshot." Six is
    at most six, so the boundary admits.

    Design: Difficulty/boundary_precision_check/rolling_record_points_admit_exactly_six_and_reject_seven
    """
    world = fixtures.seed_marketplace(api)
    fern = fixtures.seed_renter_with_driving_history(
        api,
        [
            (2, "2024-02-02T00:00:00Z"),
            (2, "2025-03-03T00:00:00Z"),
            (2, "2026-04-04T00:00:00Z"),
        ],
        towing_result=QualificationResult.VERIFIED_BASIC,
        **RENTER_F,
    )
    checked = validate_success(api.get_renter(fern["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert checked["driving_record_points"] == 6

    booking = validate_success(_book_as(api, world, world.listing_id, fern["id"]), 201)

    assert booking["trip_status"] == TripStatus.REQUESTED
    assert booking["renter_record_points_snapshot"] == 2
    assert booking["towing_verified_tier"] == TowingTier.BASIC


def test_seven_rolling_points_are_rejected(api):
    """PRD 3.5: "The renter's rolling `driving_record_points` must be at most six,
    and a renter above six is rejected with `ERR_DRIVING_RECORD_POINTS_EXCEEDED`".
    PRD 3.4 explains why a single extra point on the newest check is enough:
    "Because it sums, three separate two-point checks inside the window total six
    points, and a fourth breaches the ceiling."

    Design: Difficulty/boundary_precision_check/rolling_record_points_admit_exactly_six_and_reject_seven
    """
    world = fixtures.seed_marketplace(api)
    gus = fixtures.seed_renter_with_driving_history(
        api,
        [
            (2, "2024-02-02T00:00:00Z"),
            (2, "2025-03-03T00:00:00Z"),
            (3, "2026-04-04T00:00:00Z"),
        ],
        towing_result=QualificationResult.VERIFIED_BASIC,
        **RENTER_G,
    )
    checked = validate_success(api.get_renter(gus["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert checked["driving_record_points"] == 7

    response = _book_as(
        api,
        world,
        world.listing_id,
        gus["id"],
        start_date="2026-09-10",
        end_date="2026-09-14",
    )
    validate_error(response, ApiErrorId.DRIVING_RECORD_POINTS_EXCEEDED, 422)

    _rows, meta = validate_paginated(
        api.list_bookings(
            factories.page_params(renter_id=gus["id"]), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 0


def test_an_invalid_driving_record_outranks_its_point_total(api):
    """PRD 2.8 orders the pair: step 17 is "**Driving-record validity** —
    `ERR_DRIVING_RECORD_INVALID` (422), at booking request." and step 18 is
    "**Driving-record point ceiling** — `ERR_DRIVING_RECORD_POINTS_EXCEEDED` (422),
    at booking request." PRD 3.5 defines the first: "a renter with no driving-record
    check, a newest check reading `MAJOR`, or a newest check expiring before the trip
    ends is rejected with `ERR_DRIVING_RECORD_INVALID`."

    Design: Corner/validations/driving_record_validity_is_checked_before_its_point_total
    """
    world = fixtures.seed_marketplace(api)
    cara = fixtures.create_renter(api, **RENTER_CARA)
    fixtures.add_driving_record_check(
        api,
        cara["id"],
        violation_points=4,
        result=QualificationResult.CLEAR,
        checked_at="2025-01-01T00:00:00Z",
    )
    fixtures.add_driving_record_check(
        api,
        cara["id"],
        violation_points=4,
        result=QualificationResult.MAJOR,
        checked_at="2026-07-01T00:00:00Z",
    )
    fixtures.add_towing_experience_check(
        api, cara["id"], result=QualificationResult.VERIFIED_ADVANCED
    )

    response = _book_as(api, world, world.listing_id, cara["id"])
    validate_error(response, ApiErrorId.DRIVING_RECORD_INVALID, 422)

    renter = validate_success(api.get_renter(cara["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert renter["driving_record_points"] == 8
    assert renter["driving_record_status"] == DrivingRecordStatus.MAJOR

    _rows, meta = validate_paginated(
        api.list_bookings(
            factories.page_params(renter_id=cara["id"]), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 0


def test_a_motorised_class_needs_no_towing_credential_and_pays_no_surcharge(api):
    """PRD 3.2: "`requires_towing` is true exactly when `vehicle_class` is
    `TRAVEL_TRAILER` or `FIFTH_WHEEL`, and false for the three motorised classes."
    PRD 3.5 hangs both gates on that flag — "When the listing's `requires_towing` is
    true, the renter's `towing_verified_tier` must be something other than `NONE`" —
    and so does the surcharge: "when the listing's `requires_towing` is true and the
    booking's frozen `towing_verified_tier` is exactly `BASIC`, a towing surcharge
    equal to 2500 basis points — a quarter — of the tier premium is computed", while
    "in every other case, including an `ADVANCED` tier or a rig that needs no
    towing, the surcharge is 0."

    Design: Corner/validations/towing_rules_apply_only_to_towed_vehicle_classes
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
    assert van["requires_towing"] is False

    booking = validate_success(
        _book_as(api, world, van["id"], world.renter_id), 201
    )

    assert booking["base_subtotal_cents"] == 110896
    assert booking["premium_cents"] == 19961
    assert booking["loyalty_tier"] == LoyaltyTier.TIER_1
    assert booking["loyalty_discount_cents"] == 5234
    assert booking["service_fee_cents"] == 15075
    assert booking["quoted_total_cents"] == 140698


def test_exactly_eight_penalty_points_block_the_renter(api):
    """PRD 3.5: "The renter's `renter_penalty_points` must be strictly below eight,
    and a renter at or above eight points is rejected with `ERR_RENTER_BLOCKED`." PRD
    2.8 places the gate at step 21, after every qualification check has already
    passed.

    Design: Corner/errors/renter_at_the_block_threshold_cannot_book
    """
    world = fixtures.seed_marketplace(api)
    fixtures.adjust_renter_points(
        api, world.renter_id, 8, "two late returns and a no-show"
    )

    response = _book_as(api, world, world.listing_id, world.renter_id)
    validate_error(response, ApiErrorId.RENTER_BLOCKED, 422)

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert renter["renter_penalty_points"] == 8

    _rows, meta = validate_paginated(
        api.list_bookings(
            factories.page_params(renter_id=world.renter_id), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 0


def test_a_heavy_trailer_rejects_a_basic_tier_then_accepts_advanced(api):
    """PRD 3.5: "When `requires_towing` is true **and** the listing's `gvwr_lbs` is
    strictly greater than 10000 pounds — five short tons, the point at which a
    trailer stops being a weekend proposition — the tier must be exactly `ADVANCED`,
    so a renter holding only `BASIC` is rejected with
    `ERR_TOWING_TIER_INSUFFICIENT`. A heavy trailer therefore rejects a `BASIC`
    renter at the second step even though the first step passed." PRD 3.4 supplies
    the upgrade: "The renter's `towing_verified_tier` is the highest tier among the
    renter's towing-experience checks whose `expires_on` is on or after the clock
    date, where `ADVANCED` outranks `BASIC`".

    Design: Corner/errors/heavy_fifth_wheel_rejects_a_basic_towing_tier_then_accepts_advanced
    """
    world = fixtures.seed_marketplace(api)
    heavy = fixtures.add_second_listed_listing(
        api,
        world,
        nickname="Ponderosa Fifth Wheel",
        vehicle_class=VehicleClass.FIFTH_WHEEL,
        gvwr_lbs=15000,
        length_ft=33,
    )
    assert heavy["requires_towing"] is True

    refused = _book_as(api, world, heavy["id"], world.renter_id)
    validate_error(refused, ApiErrorId.TOWING_TIER_INSUFFICIENT, 422)

    fixtures.add_towing_experience_check(
        api,
        world.renter_id,
        result=QualificationResult.VERIFIED_ADVANCED,
        checked_at="2026-07-15T00:00:00Z",
        expires_on="2027-07-15",
    )
    upgraded = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert upgraded["towing_verified_tier"] == TowingTier.ADVANCED

    booking = validate_success(_book_as(api, world, heavy["id"], world.renter_id), 201)
    assert booking["towing_verified_tier"] == TowingTier.ADVANCED
    assert booking["premium_cents"] == 19961
    assert booking["quoted_total_cents"] == 140698
