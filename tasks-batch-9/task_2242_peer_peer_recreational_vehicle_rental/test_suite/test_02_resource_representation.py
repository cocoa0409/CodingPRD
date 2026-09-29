"""How resources present themselves: system fields, immutability, pagination
and the server-side derivation of a booking quote."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    LoyaltyTier,
    OwnerStatus,
    PLATFORM_ADMIN_HEADERS,
    SeasonCode,
    SettlementStatus,
    TowingTier,
    TripStatus,
    assert_booking,
    assert_booking_quote_identity,
    assert_identifier,
    assert_owner,
    assert_renter_qualification,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_INSTANT = "2026-08-01T00:00:00.000Z"
UNKNOWN_PLAN_ID = "11111111-1111-4111-8111-111111111111"


def test_owner_creation_stamps_the_clock_into_the_system_fields(api):
    """PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC
    timestamp with three fractional digits recording the moment of creation as
    read from the logical clock described in §2.5.", together with "`version`, an
    integer that starts at 1 and increments by one on every mutation of that
    resource." PRD 3.1 pins the opening counters: "The new owner opens with
    `status` set to `ACTIVE`, `owner_penalty_points` at 0, `payout_balance_cents`
    at 0 and `listed_listing_count` at 0."

    Design: Corner/entities/owner_create_stamps_system_fields_and_version_one
    """
    fixtures.set_clock(api)

    owner = validate_success(
        api.create_owner(factories.owner_payload(), PLATFORM_ADMIN_HEADERS), 201
    )

    assert_owner(owner)
    assert_identifier(owner["id"], "owner.id")
    assert owner["created_at"] == CLOCK_INSTANT
    assert owner["updated_at"] == CLOCK_INSTANT
    assert owner["version"] == 1
    assert owner["status"] == OwnerStatus.ACTIVE
    assert owner["owner_penalty_points"] == 0
    assert owner["payout_balance_cents"] == 0
    assert owner["listed_listing_count"] == 0


def test_a_qualification_check_carries_no_version_or_updated_at(api):
    """PRD 3.4: "Qualification records are append-only evidence: they carry `id`
    and `created_at` and nothing else from the common set." PRD 2.4 says the same
    from the other direction: "renter qualification checks, meter readings, trip
    photos and ledger entries have no `updated_at` and no `version` at all, and
    clients must not expect either field on them."

    Design: Corner/entities/renter_qualification_is_immutable_and_carries_no_version
    """
    fixtures.set_clock(api)
    renter = fixtures.create_renter(api)
    fixtures.add_driving_record_check(api, renter["id"])

    rows, meta = validate_paginated(
        api.list_renter_qualifications(
            factories.page_params(renter_id=renter["id"], check_type="DRIVING_RECORD"),
            PLATFORM_ADMIN_HEADERS,
        )
    )

    assert meta["total_count"] == 1
    assert len(rows) == 1
    check = rows[0]
    assert_renter_qualification(check)
    assert check["violation_points"] == 2
    assert check["result"] == "CLEAR"
    assert "id" in check and "created_at" in check
    assert "version" not in check
    assert "updated_at" not in check


def test_first_page_of_pricing_seasons_reports_the_unpaginated_total(api):
    """PRD 2.3: "`total_count` is the number of rows matching the filters before
    pagination is applied; `has_more` is true exactly when rows remain beyond the
    returned page." Ordering follows the same section: "Unless a specific
    endpoint says otherwise, list results are sorted by `created_at` in ascending
    order."

    Design: Corner/entities/pricing_season_list_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(api)
    fixtures.create_pricing_seasons(api)

    rows, meta = validate_paginated(
        api.list_pricing_seasons(
            factories.page_params(limit=2, offset=0), PLATFORM_ADMIN_HEADERS
        )
    )

    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert len(rows) == 2
    assert rows[0]["season_code"] == SeasonCode.PEAK
    assert rows[1]["season_code"] == SeasonCode.SHOULDER


def test_last_page_of_pricing_seasons_reports_no_further_rows(api):
    """PRD 2.3: "`total_count` is the number of rows matching the filters before
    pagination is applied; `has_more` is true exactly when rows remain beyond the
    returned page." The trailing page therefore keeps the same total while
    reporting `has_more` false.

    Design: Corner/entities/pricing_season_list_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(api)
    fixtures.create_pricing_seasons(api)

    rows, meta = validate_paginated(
        api.list_pricing_seasons(
            factories.page_params(limit=2, offset=2), PLATFORM_ADMIN_HEADERS
        )
    )

    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["season_code"] == SeasonCode.OFF
    assert rows[0]["multiplier_bp"] == 8500


def test_booking_creation_derives_every_money_and_risk_field_server_side(api):
    """PRD 3.5 computes the booking rather than echoing it: "The sharing period is
    the half-open date range that includes `start_date` and excludes `end_date`,
    so `nights` is simply the number of days between the two dates", and the age
    is "recorded on the booking as `renter_age_years_at_start`, computed from the
    renter's `date_of_birth` to `start_date` and truncated downward to whole
    years". PRD 3.7 keeps the hold out of it: the hold is placed only at renter
    confirmation.

    Design: Corner/entities/booking_computed_fields_are_derived_not_echoed
    """
    world = fixtures.seed_marketplace(api)

    booking = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id, world.renter_id, world.plan_id, world.policy_id
            ),
            world.renter_headers,
        ),
        201,
    )

    assert_booking(booking)
    assert booking["nights"] == 4
    assert booking["renter_age_years_at_start"] == 32
    assert booking["renter_record_points_snapshot"] == 2
    assert booking["towing_verified_tier"] == TowingTier.BASIC
    assert booking["base_subtotal_cents"] == 110896
    assert booking["premium_cents"] == 24951
    assert booking["delivery_fee_cents"] == 0
    assert booking["loyalty_tier"] == LoyaltyTier.TIER_1
    assert booking["loyalty_discount_cents"] == 5434
    assert booking["service_fee_cents"] == 15650
    assert booking["estimated_overage_cents"] == 0
    assert booking["quoted_total_cents"] == 146063
    assert_booking_quote_identity(booking)
    assert booking["hold_amount_cents"] == 0
    assert booking["trip_status"] == TripStatus.REQUESTED
    assert booking["settlement_status"] == SettlementStatus.NONE
    assert booking["version"] == 1


def test_unresolvable_listing_outranks_an_unresolvable_plan_on_the_same_body(api):
    """PRD 3.5: "those four foreign keys are resolved in that order, so an
    unresolvable listing reports `ERR_LISTING_NOT_FOUND` before an unresolvable
    plan would have reported `ERR_PLAN_NOT_FOUND`."

    Design: Corner/entities/booking_body_foreign_keys_resolve_left_to_right
    """
    world = fixtures.seed_marketplace(api)

    response = api.create_booking(
        factories.booking_payload(
            NON_EXISTENT_UUID, world.renter_id, UNKNOWN_PLAN_ID, world.policy_id
        ),
        world.renter_headers,
    )
    validate_error(response, ApiErrorId.LISTING_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_bookings(
            factories.page_params(listing_id=world.listing_id), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 0


def test_a_real_listing_lets_the_unresolvable_plan_surface_next(api):
    """PRD 2.8 step 6: "every foreign key carried in the request body resolves,
    checked in the order the fields are listed for that operation in Section 3.
    The concrete code is again the per-entity 404 ... `protection_plan_id` yields
    `ERR_PLAN_NOT_FOUND`". With the listing resolvable, the plan becomes the
    first unresolvable key.

    Design: Corner/entities/booking_body_foreign_keys_resolve_left_to_right
    """
    world = fixtures.seed_marketplace(api)

    response = api.create_booking(
        factories.booking_payload(
            world.listing_id, world.renter_id, UNKNOWN_PLAN_ID, world.policy_id
        ),
        world.renter_headers,
    )
    validate_error(response, ApiErrorId.PLAN_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_bookings(
            factories.page_params(listing_id=world.listing_id), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 0
