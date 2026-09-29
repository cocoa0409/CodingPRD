"""Creating, reading and validating a rig listing before it enters review."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    InsuranceStatus,
    ListingStatus,
    PLATFORM_ADMIN_HEADERS,
    VehicleClass,
    assert_listing,
    assert_requires_towing_derivation,
    factories,
    fixtures,
    make_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_listing_opens_in_draft_with_zeroed_onboarding_counters(api):
    """PRD 3.2: "The listing is born in `listing_status` `DRAFT`, with
    `insurance_status` at `PENDING`, `inspection_photo_zone_count` at 0,
    `completed_night_count` at 0 and `last_reconciled_at` null."

    PRD 3.2 also derives the towing flag: "`requires_towing` is true exactly
    when `vehicle_class` is `TRAVEL_TRAILER` or `FIFTH_WHEEL`, and false for the
    three motorised classes."

    Design: Corner/entities/listing_create_returns_draft_with_computed_onboarding_counters
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)

    response = api.create_listing(
        factories.listing_payload(owner["id"]), make_owner_headers(owner["id"])
    )
    listing = validate_success(response, 201)

    assert_listing(listing)
    assert listing["owner_id"] == owner["id"]
    assert listing["listing_status"] == ListingStatus.DRAFT
    assert listing["insurance_status"] == InsuranceStatus.PENDING
    assert listing["requires_towing"] is True
    assert_requires_towing_derivation(listing)
    assert listing["inspection_photo_zone_count"] == 0
    assert listing["completed_night_count"] == 0
    assert listing["last_reconciled_at"] is None
    assert listing["version"] == 1


def test_reading_a_draft_listing_returns_the_stored_values_without_mutating_it(api):
    """PRD 2.4: "`version`, an integer that starts at 1 and increments by one on
    every mutation of that resource." A read is not a mutation, so the stored
    row comes back exactly as supplied and the version stays at 1.

    Design: Corner/entities/get_listing_returns_the_stored_row_unchanged
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    created = fixtures.create_draft_listing(api, owner["id"])

    response = api.get_listing(created["id"], make_owner_headers(owner["id"]))
    listing = validate_success(response, 200)

    assert listing["id"] == created["id"]
    assert listing["base_nightly_rate_cents"] == 21533
    assert listing["gvwr_lbs"] == 8500
    assert listing["length_ft"] == 30
    assert listing["delivery_offered"] is True
    assert listing["delivery_base_fee_cents"] == 12000
    assert listing["listing_status"] == ListingStatus.DRAFT
    assert listing["version"] == 1


def test_listing_creation_without_a_nightly_rate_is_a_malformed_request(api):
    """PRD 3.2 requires "a `base_nightly_rate_cents` list price of at least 1000
    cents" on every listing, and PRD 2.8 step 4 judges shape first: "request body
    and query parameters satisfy the declared field types, enum memberships,
    numeric ranges and required-field presence, and pagination bounds are
    respected (`limit` between 1 and 100, `offset` not negative), otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/listing_create_missing_required_base_nightly_rate_is_rejected
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])

    payload = factories.listing_payload(
        owner["id"],
        nickname="No Rate Rig",
        vehicle_class=VehicleClass.CLASS_C,
        gvwr_lbs=12000,
        length_ft=28,
    )
    payload.pop("base_nightly_rate_cents")
    payload.pop("delivery_offered")
    payload.pop("delivery_base_fee_cents")
    payload.pop("delivery_per_mile_cents")

    response = api.create_listing(payload, owner_headers)
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_listings(factories.page_params(owner_id=owner["id"]), owner_headers)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_listing_creation_rejects_an_unknown_vehicle_class(api):
    """PRD 3.2 fixes the vocabulary: "a `vehicle_class` of `CLASS_A`, `CLASS_C`,
    `CAMPER_VAN`, `TRAVEL_TRAILER` or `FIFTH_WHEEL`", and PRD 2.8 step 4 makes an
    enum membership failure a 400: "request body and query parameters satisfy the
    declared field types, enum memberships, numeric ranges and required-field
    presence".

    Design: Corner/entities/listing_create_with_invalid_enum_and_out_of_range_number_is_rejected
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])

    response = api.create_listing(
        factories.listing_payload(
            owner["id"],
            nickname="Bad Class Rig",
            vehicle_class="MOTORHOME",
            gvwr_lbs=12000,
            length_ft=28,
            base_nightly_rate_cents=20000,
        ),
        owner_headers,
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(
        api.list_listings(factories.page_params(owner_id=owner["id"]), owner_headers)
    )
    assert meta["total_count"] == 0


def test_listing_creation_rejects_a_minimum_renter_age_above_thirty(api):
    """PRD 3.2 bounds the field: "a `min_renter_age` between 21 and 30 whole
    years". PRD 2.8 step 4 turns an out-of-range number into
    `ERR_INVALID_REQUEST` (400) before any existence or state check runs.

    Design: Corner/entities/listing_create_with_invalid_enum_and_out_of_range_number_is_rejected
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])

    response = api.create_listing(
        factories.listing_payload(
            owner["id"],
            nickname="Bad Age Rig",
            vehicle_class=VehicleClass.CLASS_C,
            gvwr_lbs=12000,
            length_ft=28,
            base_nightly_rate_cents=20000,
            min_renter_age=31,
        ),
        owner_headers,
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(
        api.list_listings(factories.page_params(owner_id=owner["id"]), owner_headers)
    )
    assert meta["total_count"] == 0


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults(api):
    """PRD 3.2: "Three delivery fields are optional: `delivery_offered` defaults
    to false, and `delivery_base_fee_cents` and `delivery_per_mile_cents` each
    default to 0 and must be non-negative." PRD 3.1 does the same for the other
    two rows: a campground takes "an optional `status` that defaults to
    `ACCEPTING` and may otherwise be `CLOSED`" and "A newly registered campground
    opens with `scheduled_assignment_count` at 0", while a qualification takes
    "an optional `violation_points` count defaulting to 0 and bounded between 0
    and 20".

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    renter = fixtures.create_renter(api)

    listing_payload = factories.listing_payload(
        owner["id"],
        nickname="Pickup Only Van",
        vehicle_class=VehicleClass.CAMPER_VAN,
        gvwr_lbs=9000,
        length_ft=21,
        base_nightly_rate_cents=18000,
        mileage_overage_rate_cents_per_mile=60,
        included_generator_hours_per_night=2.0,
        generator_overage_rate_cents_per_hour=400,
    )
    for optional in ("delivery_offered", "delivery_base_fee_cents", "delivery_per_mile_cents"):
        listing_payload.pop(optional)

    listing = validate_success(
        api.create_listing(listing_payload, make_owner_headers(owner["id"])), 201
    )
    assert listing["delivery_offered"] is False
    assert listing["delivery_base_fee_cents"] == 0
    assert listing["delivery_per_mile_cents"] == 0
    assert listing["requires_towing"] is False

    campground_payload = factories.campground_payload()
    campground_payload.pop("status", None)
    campground = validate_success(
        api.create_campground(campground_payload, PLATFORM_ADMIN_HEADERS), 201
    )
    assert campground["status"] == "ACCEPTING"
    assert campground["scheduled_assignment_count"] == 0

    qualification_payload = factories.towing_experience_check_payload(
        renter["id"], result="UNVERIFIED"
    )
    qualification_payload.pop("violation_points")
    qualification = validate_success(
        api.create_renter_qualification(qualification_payload, PLATFORM_ADMIN_HEADERS), 201
    )
    assert qualification["violation_points"] == 0


def test_reading_a_listing_that_does_not_exist_returns_the_listing_specific_code(api):
    """PRD 2.8 step 5: "every identifier embedded in the URL path resolves to an
    existing row, validated strictly left to right, so the first unresolvable
    segment determines the error. The concrete code is the per-entity 404 ...
    `ERR_LISTING_NOT_FOUND` for `listingId`".

    Design: Corner/entities/get_listing_with_unknown_uuid_not_found_returns_listing_code
    """
    fixtures.set_clock(api)

    response = api.get_listing(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.LISTING_NOT_FOUND, 404)


def test_document_upload_naming_an_unknown_listing_is_rejected_before_the_version_check(api):
    """PRD 2.8 step 6 resolves body foreign keys — "`listing_id` yields
    `ERR_LISTING_NOT_FOUND`" — and sits ahead of step 8, "**Parent version** —
    where the endpoint declares an expected-parent-version input, it equals the
    parent's current `version`, otherwise `ERR_STALE_PARENT_VERSION` (412)". So a
    correct version for a real listing cannot rescue a body that points at no
    listing at all.

    Design: Corner/entities/vehicle_document_with_unknown_listing_parent_not_found
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])
    listing = fixtures.create_draft_listing(api, owner["id"])

    response = api.create_vehicle_document(
        factories.title_document_payload(
            NON_EXISTENT_UUID,
            listing["version"],
            image_ref="s3://docs/orphan-title.pdf",
        ),
        owner_headers,
    )
    validate_error(response, ApiErrorId.LISTING_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_vehicle_documents(
            factories.page_params(listing_id=listing["id"]), owner_headers
        )
    )
    assert meta["total_count"] == 0

    unchanged = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert unchanged["version"] == 1
    assert unchanged["insurance_status"] == InsuranceStatus.PENDING
