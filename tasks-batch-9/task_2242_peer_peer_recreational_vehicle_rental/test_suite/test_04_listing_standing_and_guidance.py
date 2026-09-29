"""Owner standing and its consequences for a listing: the twelve-point
threshold, deliberate reinstatement, terminal archival, and the read-only
pricing guidance an owner can ask for at any time."""

from test_helpers import (
    ApiErrorId,
    ListingStatus,
    OwnerStatus,
    PLATFORM_ADMIN_HEADERS,
    SeasonCode,
    VehicleClass,
    assert_pricing_guidance,
    factories,
    fixtures,
    make_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

BARE_LISTING = {
    "nickname": "Retired Fifth Wheel",
    "vehicle_class": VehicleClass.FIFTH_WHEEL,
    "gvwr_lbs": 15000,
    "length_ft": 34,
    "base_nightly_rate_cents": 25000,
    "included_miles_per_night": 100,
    "mileage_overage_rate_cents_per_mile": 70,
    "included_generator_hours_per_night": 3.0,
    "generator_overage_rate_cents_per_hour": 450,
    "min_renter_age": 25,
}


def _bare_draft_listing(api, owner_id, nickname="Retired Fifth Wheel", **overrides):
    """A DRAFT listing with no documents and no delivery offer at all."""
    payload = dict(BARE_LISTING)
    payload["nickname"] = nickname
    payload.update(overrides)
    return fixtures.create_draft_listing(api, owner_id, **payload)


def test_eleven_penalty_points_leave_the_owner_active_and_the_listing_listed(api):
    """PRD 3.1: "If the resulting total reaches or exceeds twelve points, the
    owner's `status` becomes `SUSPENDED` and every one of that owner's `LISTED`
    listings cascades to `SUSPENDED` with all the downstream consequences described
    in §3.3." Eleven points does not reach twelve, so nothing fires.

    Design: Difficulty/boundary_precision_check/owner_suspension_fires_at_exactly_twelve_points_not_eleven
    """
    world = fixtures.seed_marketplace(api)

    owner = validate_success(
        api.adjust_owner_penalty_points(
            world.owner_id,
            factories.penalty_adjustment_payload(
                11, "eleven points of accumulated sanctions"
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )

    assert owner["owner_penalty_points"] == 11
    assert owner["status"] == OwnerStatus.ACTIVE
    assert owner["listed_listing_count"] == 1

    listing = validate_success(
        api.get_listing(world.listing_id, world.owner_headers), 200
    )
    assert listing["listing_status"] == ListingStatus.LISTED


def test_the_twelfth_point_suspends_the_owner_and_cascades_to_the_listing(api):
    """PRD 3.1: "If the resulting total reaches or exceeds twelve points, the
    owner's `status` becomes `SUSPENDED` and every one of that owner's `LISTED`
    listings cascades to `SUSPENDED`". PRD 3.3 states the cascade's own bookkeeping:
    "The listing moves `LISTED → SUSPENDED`, the owner's `listed_listing_count`
    decreases by one, and both the listing's and the owner's `version` increment."

    Design: Difficulty/boundary_precision_check/owner_suspension_fires_at_exactly_twelve_points_not_eleven
    """
    world = fixtures.seed_marketplace(api)
    fixtures.adjust_owner_points(
        api, world.owner_id, 11, "eleven points of accumulated sanctions"
    )

    owner = validate_success(
        api.adjust_owner_penalty_points(
            world.owner_id,
            factories.penalty_adjustment_payload(1, "the twelfth point"),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )

    assert owner["owner_penalty_points"] == 12
    assert owner["status"] == OwnerStatus.SUSPENDED
    assert owner["listed_listing_count"] == 0

    listing = validate_success(
        api.get_listing(world.listing_id, world.owner_headers), 200
    )
    assert listing["listing_status"] == ListingStatus.SUSPENDED


def test_dropping_back_below_twelve_reactivates_the_owner_but_not_the_listing(api):
    """PRD 3.1: "If instead the resulting total falls back below twelve, the
    owner's `status` returns to `ACTIVE` — but previously suspended listings are
    **not** automatically reinstated; each must be reinstated deliberately." The
    cascade is therefore not a reversible function of the current point total.

    Design: Difficulty/boundary_precision_check/owner_suspension_fires_at_exactly_twelve_points_not_eleven
    """
    world = fixtures.seed_marketplace(api)
    fixtures.adjust_owner_points(
        api, world.owner_id, 11, "eleven points of accumulated sanctions"
    )
    fixtures.adjust_owner_points(api, world.owner_id, 1, "the twelfth point")

    owner = validate_success(
        api.adjust_owner_penalty_points(
            world.owner_id,
            factories.penalty_adjustment_payload(
                -1, "one point credited back on appeal"
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )

    assert owner["owner_penalty_points"] == 11
    assert owner["status"] == OwnerStatus.ACTIVE
    assert owner["listed_listing_count"] == 0

    listing = validate_success(
        api.get_listing(world.listing_id, world.owner_headers), 200
    )
    assert listing["listing_status"] == ListingStatus.SUSPENDED


def test_reinstatement_is_refused_while_the_owner_sits_at_twelve_points(api):
    """PRD 3.3: "The owner's `owner_penalty_points` must be strictly below twelve,
    and a reinstatement attempted while the owner still sits at or above that
    threshold is refused with `ERR_LISTING_STATE_INVALID`." PRD 2.8 step 11 gives
    the same code the same status: "reinstatement additionally requires that the
    owner's `owner_penalty_points` is strictly below the twelve-point suspension
    threshold."

    Design: Difficulty/cross_entity_state_dependency/listing_reinstatement_is_gated_by_the_owners_penalty_point_total
    """
    world = fixtures.seed_marketplace(api)
    fixtures.adjust_owner_points(
        api, world.owner_id, 12, "repeated host cancellations"
    )

    response = api.reinstate_listing(world.listing_id, PLATFORM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.LISTING_STATE_INVALID, 409)

    listing = validate_success(
        api.get_listing(world.listing_id, world.owner_headers), 200
    )
    assert listing["listing_status"] == ListingStatus.SUSPENDED


def test_crediting_one_point_back_lets_the_identical_reinstatement_succeed(api):
    """PRD 3.3: "A `PlatformAdmin` returns a `SUSPENDED` listing to `LISTED`, which
    increases the owner's `listed_listing_count` by one and increments both the
    listing's and the owner's `version`." The only thing that changed is a number on
    the parent owner: "The owner's `owner_penalty_points` must be strictly below
    twelve".

    Design: Difficulty/cross_entity_state_dependency/listing_reinstatement_is_gated_by_the_owners_penalty_point_total
    """
    world = fixtures.seed_marketplace(api)
    fixtures.adjust_owner_points(
        api, world.owner_id, 12, "repeated host cancellations"
    )
    validate_error(
        api.reinstate_listing(world.listing_id, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.LISTING_STATE_INVALID,
        409,
    )

    owner = validate_success(
        api.adjust_owner_penalty_points(
            world.owner_id,
            factories.penalty_adjustment_payload(
                -1, "one sanction vacated on appeal"
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )
    assert owner["owner_penalty_points"] == 11
    assert owner["status"] == OwnerStatus.ACTIVE
    assert owner["listed_listing_count"] == 0

    reinstated = validate_success(
        api.reinstate_listing(world.listing_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert reinstated["listing_status"] == ListingStatus.LISTED

    counted = validate_success(
        api.get_owner(world.owner_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert counted["listed_listing_count"] == 1


def test_an_archived_listing_refuses_a_further_submission(api):
    """PRD 3.3: "A listing's full set of states is `DRAFT`, `IN_REVIEW`, `LISTED`,
    `SUSPENDED` and `ARCHIVED`, of which `ARCHIVED` is terminal." PRD 2.8 step 11
    answers before the documentation gates of steps 28 and 29: "**Listing state** —
    the listing's `listing_status` is a legal origin for the requested listing
    transition, otherwise `ERR_LISTING_STATE_INVALID` (409). Applies to
    submit-for-review, the review decision, suspension, reinstatement and
    archival."

    Design: Corner/state_machines/archived_listing_accepts_no_further_transition
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])
    listing = _bare_draft_listing(api, owner["id"])
    validate_success(api.archive_listing(listing["id"], owner_headers), 200)

    response = api.submit_listing_for_review(listing["id"], owner_headers)
    validate_error(response, ApiErrorId.LISTING_STATE_INVALID, 409)

    unchanged = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert unchanged["listing_status"] == ListingStatus.ARCHIVED


def test_an_archived_listing_refuses_a_platform_decision(api):
    """PRD 3.3: "A listing's full set of states is `DRAFT`, `IN_REVIEW`, `LISTED`,
    `SUSPENDED` and `ARCHIVED`, of which `ARCHIVED` is terminal." The review
    decision is in the same step-11 list, so an operator has no more reach into the
    terminal state than the owner does.

    Design: Corner/state_machines/archived_listing_accepts_no_further_transition
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])
    listing = _bare_draft_listing(api, owner["id"])
    validate_success(api.archive_listing(listing["id"], owner_headers), 200)

    response = api.decide_listing(
        listing["id"],
        factories.listing_decision_payload("APPROVE"),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.LISTING_STATE_INVALID, 409)

    unchanged = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert unchanged["listing_status"] == ListingStatus.ARCHIVED


def test_archiving_a_bare_draft_needs_no_documents_and_no_operator(api):
    """PRD 3.3: "Archival is the terminal exit and is available from `DRAFT` and
    from `SUSPENDED` — never directly from `LISTED` or `IN_REVIEW`. Either the
    owning `Owner` or a `PlatformAdmin` may archive." Its only side effect is small:
    "Both source states share the same single side effect as well: `listing_status`
    becomes `ARCHIVED` and the listing's `version` increments."

    Design: Corner/endpoints/archive_action_retires_a_draft_listing_with_no_live_bookings
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])
    listing = _bare_draft_listing(
        api,
        owner["id"],
        nickname="Abandoned Fifth Wheel",
        gvwr_lbs=14000,
        included_generator_hours_per_night=4.0,
    )
    assert listing["version"] == 1

    archived = validate_success(api.archive_listing(listing["id"], owner_headers), 200)

    assert archived["listing_status"] == ListingStatus.ARCHIVED
    assert archived["version"] == 2

    counted = validate_success(api.get_owner(owner["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert counted["listed_listing_count"] == 0

    _rows, meta = validate_paginated(
        api.list_listings(
            factories.page_params(listing_status=ListingStatus.ARCHIVED),
            PLATFORM_ADMIN_HEADERS,
        )
    )
    assert meta["total_count"] == 1


def test_pricing_guidance_marks_a_lightly_booked_peak_rig_down(api):
    """PRD 3.11: "The analysis window opens on the logical clock's calendar date
    and runs for ninety days inclusive, so the window's last date is eighty-nine
    days after its first." Four confirmed nights out of ninety give "the booked-night
    count multiplied by 10000, divided by 90, rounded half up to whole basis
    points", and "Below 2000 basis points the adjustment is a negative 1000 basis
    points, a ten percent markdown suggested to stimulate demand." The seasonal leg
    "looks ahead rather than at today: the platform resolves the seasonal multiplier
    and season code for the date thirty days after the window's opening date", and
    the rate is "rounded half up to whole cents **exactly once, at the very end**".
    Nothing is stored: "The guidance is advisory: nothing about it changes the
    listing's stored `base_nightly_rate_cents`."

    Design: Corner/endpoints/pricing_guidance_derives_the_suggested_rate_from_utilization_and_season
    """
    world = fixtures.seed_marketplace(api)
    fixtures.seed_confirmed_booking(api, world)

    guidance = validate_success(
        api.get_pricing_guidance(world.listing_id, world.owner_headers), 200
    )

    assert_pricing_guidance(guidance)
    assert guidance["listing_id"] == world.listing_id
    assert guidance["window_start_date"] == "2026-08-01"
    assert guidance["window_end_date"] == "2026-10-29"
    assert guidance["booked_nights"] == 4
    assert guidance["utilization_bp"] == 444
    assert guidance["util_adj_bp"] == -1000
    assert guidance["season_code"] == SeasonCode.PEAK
    assert guidance["season_multiplier_bp"] == 13500
    assert guidance["suggested_nightly_rate_cents"] == 26163

    listing = validate_success(
        api.get_listing(world.listing_id, world.owner_headers), 200
    )
    assert listing["base_nightly_rate_cents"] == 21533
    assert listing["version"] == 14
