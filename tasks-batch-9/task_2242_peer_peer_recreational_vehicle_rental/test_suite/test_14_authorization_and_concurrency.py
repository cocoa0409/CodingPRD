"""The cross-cutting layers: the two header checks, the twelve resource-family
404s, the ownership and role boundaries, the shared trip operations, and the
expected-parent-version guards on the two destructive creates."""

from test_helpers import (
    ApiErrorId,
    AssignmentStatus,
    CLAIMS_ADJUSTER_HEADERS,
    ClaimStatus,
    DeliveryOption,
    DocType,
    ListingStatus,
    PLATFORM_ADMIN_HEADERS,
    PhotoPhase,
    SettlementStatus,
    TripStatus,
    Zone,
    build_user_headers,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
UNDECLARED_ROLE_HEADERS = build_user_headers("test-auditor-1", "Auditor")
POST_TRIP_ZONES = (
    Zone.EXTERIOR_FRONT,
    Zone.EXTERIOR_REAR,
    Zone.INTERIOR,
    Zone.ROOF,
    Zone.UNDERCARRIAGE,
)
MID_TRIP_READING = (42260, 130.5, "2026-08-31T15:00:00Z")
POST_TRIP_READING = (42400, 132.0, "2026-09-02T11:00:00Z")


def _count(response):
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def _document_count(api, listing_id):
    return _count(
        api.list_vehicle_documents(
            factories.page_params(listing_id=listing_id), PLATFORM_ADMIN_HEADERS
        )
    )


def test_a_missing_header_and_an_undeclared_role_are_both_unauthenticated(api):
    """PRD 2.1: "Every request to the API — reads included — must carry two headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the
    capacity in which that principal is acting. If either header is absent or empty, the
    request is rejected with `ERR_UNAUTHENTICATED` (401). The same rejection applies
    when `X-User-Role` carries a value outside the four recognised role names, which are
    exactly `Owner`, `Renter`, `PlatformAdmin` and `ClaimsAdjuster`." Both checks sit
    above every resolution step, since rung 1 "Applies to every endpoint." and so does
    rung 2, while path identifiers are only resolved at rung 5.

    Design: Corner/validations/requests_missing_auth_headers_or_carrying_an_unknown_role_are_unauthenticated
    """
    fixtures.set_clock(api)

    bare = api.get_listing(UNKNOWN_ID)
    validate_error(bare, ApiErrorId.UNAUTHENTICATED, 401)

    unknown_role = api.get_listing(UNKNOWN_ID, UNDECLARED_ROLE_HEADERS)
    validate_error(unknown_role, ApiErrorId.UNAUTHENTICATED, 401)


def test_every_path_family_answers_with_its_own_not_found_code(api):
    """PRD 2.8 rung 5: "**Path identifier resolution** — every identifier embedded in
    the URL path resolves to an existing row, validated strictly left to right, so the
    first unresolvable segment determines the error. The concrete code is the per-entity
    404: `ERR_OWNER_NOT_FOUND` for `ownerId`, `ERR_RENTER_NOT_FOUND` for `renterId`,
    `ERR_LISTING_NOT_FOUND` for `listingId`, `ERR_DOCUMENT_NOT_FOUND` for `documentId`,
    `ERR_QUALIFICATION_NOT_FOUND` for `qualificationId`, `ERR_CAMPGROUND_NOT_FOUND` for
    `campgroundId`, `ERR_BOOKING_NOT_FOUND` for `bookingId`, `ERR_ASSIGNMENT_NOT_FOUND`
    for `assignmentId`, `ERR_READING_NOT_FOUND` for `readingId`, `ERR_PHOTO_NOT_FOUND`
    for `photoId`, `ERR_CLAIM_NOT_FOUND` for `claimId` and `ERR_LEDGER_ENTRY_NOT_FOUND`
    for `entryId`. Applies to every path-parameterised endpoint."

    Design: Corner/errors/every_path_parameter_family_returns_its_own_not_found_code
    """
    fixtures.set_clock(api)

    probes = (
        (api.get_owner(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS), ApiErrorId.OWNER_NOT_FOUND),
        (api.get_renter(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS), ApiErrorId.RENTER_NOT_FOUND),
        (
            api.get_renter_qualification(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.QUALIFICATION_NOT_FOUND,
        ),
        (api.get_listing(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS), ApiErrorId.LISTING_NOT_FOUND),
        (
            api.get_vehicle_document(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.DOCUMENT_NOT_FOUND,
        ),
        (
            api.get_campground(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.CAMPGROUND_NOT_FOUND,
        ),
        (api.get_booking(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS), ApiErrorId.BOOKING_NOT_FOUND),
        (
            api.get_delivery_assignment(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.ASSIGNMENT_NOT_FOUND,
        ),
        (
            api.get_meter_reading(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.READING_NOT_FOUND,
        ),
        (api.get_trip_photo(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS), ApiErrorId.PHOTO_NOT_FOUND),
        (api.get_damage_claim(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS), ApiErrorId.CLAIM_NOT_FOUND),
        (
            api.get_ledger_entry(UNKNOWN_ID, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.LEDGER_ENTRY_NOT_FOUND,
        ),
    )

    for response, expected in probes:
        validate_error(response, expected, 404)


def test_body_foreign_keys_resolve_in_the_order_they_are_listed(api):
    """PRD 2.8 rung 6: "**Body foreign-key resolution** — every foreign key carried in
    the request body resolves, checked in the order the fields are listed for that
    operation in Section 3. The concrete code is again the per-entity 404: `owner_id`
    yields `ERR_OWNER_NOT_FOUND`, `renter_id` yields `ERR_RENTER_NOT_FOUND`, `listing_id`
    yields `ERR_LISTING_NOT_FOUND`, `protection_plan_id` yields `ERR_PLAN_NOT_FOUND`,
    `cancellation_policy_id` yields `ERR_POLICY_NOT_FOUND`" ... PRD 3.5 fixes the
    booking's order: the four keys are named "in this order, the `listing_id` of the rig,
    the `renter_id` of the renting party, the `protection_plan_id` of the protection tier
    to be pinned for the trip, and the `cancellation_policy_id` of the cancellation
    tier — those four foreign keys are resolved in that order". Resolution sits above
    both ownership at rung 7 and the parent-version check at rung 8.

    Design: Corner/errors/unresolvable_body_foreign_keys_are_not_found_in_input_list_order
    """
    world = fixtures.seed_marketplace(api)

    ghost_owner = api.create_listing(
        factories.listing_payload(UNKNOWN_ID, nickname="Ghost Owner Rig"),
        world.owner_headers,
    )
    validate_error(ghost_owner, ApiErrorId.OWNER_NOT_FOUND, 404)

    ghost_renter = api.create_booking(
        factories.booking_payload(
            world.listing_id, UNKNOWN_ID, world.plan_id, world.policy_id
        ),
        world.renter_headers,
    )
    validate_error(ghost_renter, ApiErrorId.RENTER_NOT_FOUND, 404)

    both_unknown = api.create_booking(
        factories.booking_payload(
            world.listing_id, world.renter_id, UNKNOWN_ID, UNKNOWN_ID
        ),
        world.renter_headers,
    )
    validate_error(both_unknown, ApiErrorId.PLAN_NOT_FOUND, 404)

    ghost_policy = api.create_booking(
        factories.booking_payload(
            world.listing_id, world.renter_id, world.plan_id, UNKNOWN_ID
        ),
        world.renter_headers,
    )
    validate_error(ghost_policy, ApiErrorId.POLICY_NOT_FOUND, 404)

    ghost_booking = api.create_meter_reading(
        factories.meter_reading_payload(
            UNKNOWN_ID, "PRE_TRIP", 42000, 120.0, "2026-08-29T15:00:00Z"
        ),
        world.owner_headers,
    )
    validate_error(ghost_booking, ApiErrorId.BOOKING_NOT_FOUND, 404)

    ghost_listing = api.create_vehicle_document(
        factories.title_document_payload(UNKNOWN_ID, 1, image_ref="s3://docs/orphan.pdf"),
        world.owner_headers,
    )
    validate_error(ghost_listing, ApiErrorId.LISTING_NOT_FOUND, 404)

    assert _count(api.list_bookings(None, PLATFORM_ADMIN_HEADERS)) == 0


def test_the_operator_role_cannot_move_a_damage_claim_at_all(api):
    """PRD 2.1: "Once the headers are accepted, the acting role must appear in the
    authorised-role list published for the requested route in Section 4; a role acting
    outside its list is rejected with `ERR_FORBIDDEN_ROLE` (403). The most consequential
    instance of that rule is deliberate: a `PlatformAdmin` may configure the marketplace,
    review listings and post settlements, but may **not** adjudicate a damage claim —
    attempting to do so yields `ERR_FORBIDDEN_ROLE`, because the party that decides a
    claim must never be the party that pays it out." The adjuster's own routes are
    reserved to that role, which PRD 3.8 states of review: a `ClaimsAdjuster` "opens a
    submitted claim, moving it `SUBMITTED → UNDER_REVIEW` and incrementing its
    `version`".

    Design: Corner/rbac/platform_admin_cannot_adjudicate_a_damage_claim
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    claim = fixtures.file_damage_claim(
        api,
        world,
        returned["id"],
        damage_zone=Zone.INTERIOR,
        description="Dinette panel cracked during the trip",
    )

    admin_review = api.start_claim_review(claim["id"], PLATFORM_ADMIN_HEADERS)
    validate_error(admin_review, ApiErrorId.FORBIDDEN_ROLE, 403)

    untouched = validate_success(
        api.get_damage_claim(claim["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert untouched["status"] == ClaimStatus.SUBMITTED

    admin_decision = api.adjudicate_claim(
        claim["id"], factories.adjudication_payload(), PLATFORM_ADMIN_HEADERS
    )
    validate_error(admin_decision, ApiErrorId.FORBIDDEN_ROLE, 403)

    adjuster_review = validate_success(
        api.start_claim_review(claim["id"], CLAIMS_ADJUSTER_HEADERS), 200
    )
    assert adjuster_review["status"] == ClaimStatus.UNDER_REVIEW


def test_a_second_owner_is_a_stranger_to_the_first_owners_rig(api):
    """PRD 2.1: "When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting
    `Owner`; ownership checks on any resource that references an `Owner` compare the
    resource's foreign-key field to `X-User-ID`. Concretely, a listing is owned when its
    `owner_id` equals `X-User-ID`; a booking is owned when the `owner_id` of the listing
    named by the booking's `listing_id` equals `X-User-ID`" ... "A mismatch on either
    chain is rejected with `ERR_NOT_RESOURCE_OWNER` (403), which is distinct from
    `ERR_FORBIDDEN_ROLE`: the role was permitted, the specific resource was not." Rung 7
    sits above the state and version checks, so none of the three refusals may mutate
    anything.

    Design: Corner/rbac/second_owner_cannot_operate_on_the_first_owners_listing
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_requested_booking(api, world)
    before = validate_success(
        api.get_listing(world.listing_id, PLATFORM_ADMIN_HEADERS), 200
    )
    interloper = fixtures.create_owner(
        api, display_name="Boyd Interloper", email="boyd@rvshare.test", payout_state_code="ID"
    )
    interloper_headers = fixtures.make_owner_headers(interloper["id"])

    archive_attempt = api.archive_listing(world.listing_id, interloper_headers)
    validate_error(archive_attempt, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    upload_attempt = api.create_vehicle_document(
        factories.inspection_photo_payload(
            world.listing_id,
            Zone.INTERIOR,
            before["version"],
            image_ref="s3://insp/interloper.jpg",
        ),
        interloper_headers,
    )
    validate_error(upload_attempt, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    approve_attempt = api.approve_booking(booking["id"], interloper_headers)
    validate_error(approve_attempt, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    after = validate_success(
        api.get_listing(world.listing_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert after["listing_status"] == ListingStatus.LISTED
    assert after["version"] == before["version"]
    assert _document_count(api, world.listing_id) == 8

    stored = validate_success(api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert stored["trip_status"] == TripStatus.REQUESTED


def test_metering_and_return_are_shared_between_the_two_parties(api):
    """PRD 3.7: "Metering and photography are recorded as evidence throughout the trip,
    by either the owning `Owner` or the booking's `Renter`." and "Return may be performed
    by either the booking's `Renter` or the owning `Owner`, and advances the trip
    dimension `IN_TRIP → RETURNED` with a `version` increment." Neither party is
    privileged over the other on those routes, so a renter-authored reading, an
    owner-authored reading and a renter-driven return all stand.

    Design: Corner/rbac/metering_and_return_are_genuinely_shared_between_owner_and_renter
    """
    world = fixtures.seed_marketplace(api)
    started = fixtures.seed_in_trip_booking(api, world)

    renter_reading = validate_success(
        api.create_meter_reading(
            factories.meter_reading_payload(started["id"], "MID_TRIP", *MID_TRIP_READING),
            world.renter_headers,
        ),
        201,
    )
    assert renter_reading["reading_type"] == "MID_TRIP"

    owner_reading = validate_success(
        api.create_meter_reading(
            factories.meter_reading_payload(started["id"], "POST_TRIP", *POST_TRIP_READING),
            world.owner_headers,
        ),
        201,
    )
    assert owner_reading["reading_type"] == "POST_TRIP"

    for zone in POST_TRIP_ZONES:
        fixtures.record_trip_photo(
            api,
            world,
            started["id"],
            PhotoPhase.POST_TRIP,
            zone,
            damage_flagged=zone == Zone.EXTERIOR_REAR,
        )

    returned = validate_success(api.return_booking(started["id"], world.renter_headers), 200)
    assert returned["trip_status"] == TripStatus.RETURNED
    assert returned["settlement_status"] == SettlementStatus.RECONCILING
    assert returned["final_total_cents"] == 151876

    assert _count(
        api.list_meter_readings(
            factories.page_params(booking_id=started["id"]), PLATFORM_ADMIN_HEADERS
        )
    ) == 3


def test_a_stale_booking_version_blocks_the_window_the_current_one_takes_it(api):
    """PRD 2.7: "Creating a delivery assignment requires `expected_booking_version` as a
    non-optional input field, carrying the client's last observed `version` of the
    `Booking` named by `booking_id`. If the booking's `version` has advanced since the
    client read it, the create is rejected with `ERR_STALE_PARENT_VERSION` (412). This
    guard is load-bearing precisely because a second assignment against the same booking
    is legitimate product behaviour" ... PRD 2.4 makes the counter the only signal:
    `version` is "an integer that starts at 1 and increments by one on every mutation of
    that resource."

    Design: Corner/cross-cutting complexity layers/stale_expected_booking_version_is_rejected_then_the_current_one_succeeds
    """
    world = fixtures.seed_marketplace(api)
    campground = fixtures.seed_campground(api)
    booking = fixtures.seed_requested_booking(
        api, world, delivery_option=DeliveryOption.CAMPGROUND_DROPOFF
    )
    stale_version = booking["version"]
    approved = fixtures.approve_booking(api, world, booking["id"])
    assert approved["version"] == stale_version + 1

    def _attempt(expected_version):
        return api.create_delivery_assignment(
            factories.delivery_assignment_payload(
                booking["id"],
                campground["id"],
                "2026-08-29T16:00:00Z",
                "2026-08-29T17:00:00Z",
                10,
                expected_version,
            ),
            world.owner_headers,
        )

    validate_error(_attempt(stale_version), ApiErrorId.STALE_PARENT_VERSION, 412)

    assert _count(
        api.list_delivery_assignments(
            factories.page_params(booking_id=booking["id"]), PLATFORM_ADMIN_HEADERS
        )
    ) == 0
    site = validate_success(
        api.get_campground(campground["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert site["scheduled_assignment_count"] == 0

    scheduled = validate_success(_attempt(stale_version + 1), 201)
    assert scheduled["status"] == AssignmentStatus.SCHEDULED
    assert scheduled["delivery_fee_cents"] == 15500

    billed = validate_success(api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert billed["quoted_total_cents"] == 157643
    assert billed["version"] == stale_version + 2


def test_a_consumed_listing_version_cannot_be_offered_twice(api):
    """PRD 2.7: "Uploading a vehicle document requires `expected_listing_version` as a
    non-optional input field, carrying the client's last observed `version` of the
    `Listing` named by `listing_id`. If the listing's `version` has advanced since the
    client read it, the upload is rejected with `ERR_STALE_PARENT_VERSION` (412). Here
    too the reason is that the operation is destructive in a way the payload hides: a
    replacement document of the same kind supersedes its predecessor and can flip the
    listing's `insurance_status`, so a client acting on a stale listing would silently
    retire a document it never saw."

    Design: Corner/cross-cutting complexity layers/reusing_a_consumed_expected_listing_version_is_rejected
    """
    world = fixtures.seed_configuration(api)
    listing = fixtures.create_draft_listing(api, world.owner_id)
    owner_headers = fixtures.make_owner_headers(world.owner_id)
    validate_success(
        api.create_vehicle_document(
            factories.title_document_payload(listing["id"], listing["version"]),
            owner_headers,
        ),
        201,
    )

    replay = api.create_vehicle_document(
        factories.registration_document_payload(
            listing["id"], listing["version"], image_ref="s3://docs/reg-race.pdf"
        ),
        owner_headers,
    )
    validate_error(replay, ApiErrorId.STALE_PARENT_VERSION, 412)

    assert _document_count(api, listing["id"]) == 1
    after_refusal = validate_success(
        api.get_listing(listing["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert after_refusal["version"] == 2

    accepted = validate_success(
        api.create_vehicle_document(
            factories.registration_document_payload(listing["id"], 2),
            owner_headers,
        ),
        201,
    )
    assert accepted["doc_type"] == DocType.REGISTRATION

    assert _document_count(api, listing["id"]) == 2
    after_upload = validate_success(
        api.get_listing(listing["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert after_upload["version"] == 3


def test_each_document_upload_bumps_the_listing_exactly_once(api):
    """PRD 2.4: "Most resources additionally carry `updated_at` — an ISO 8601 UTC
    timestamp refreshed on every mutation — and `version`, an integer that starts at 1
    and increments by one on every mutation of that resource. Owners, renters, listings,
    vehicle documents, protection plans, cancellation policies, pricing seasons,
    campgrounds, bookings, delivery assignments and damage claims all carry both
    fields." Reads are not mutations, and a fresh draft has photographed nothing, which
    PRD 3.2 counts on the listing itself: "`inspection_photo_zone_count` is the number of
    **distinct** `zone` values across the listing's non-superseded inspection
    photographs — so five photographs of the roof still count as one zone."

    Design: Corner/cross-cutting complexity layers/every_parent_write_increments_the_version_by_exactly_one
    """
    world = fixtures.seed_configuration(api)
    listing = fixtures.create_draft_listing(api, world.owner_id)
    owner_headers = fixtures.make_owner_headers(world.owner_id)

    fresh = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert fresh["version"] == 1
    assert fresh["inspection_photo_zone_count"] == 0

    validate_success(
        api.create_vehicle_document(
            factories.title_document_payload(listing["id"], 1), owner_headers
        ),
        201,
    )
    after_title = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert after_title["version"] == 2

    validate_success(
        api.create_vehicle_document(
            factories.registration_document_payload(listing["id"], 2), owner_headers
        ),
        201,
    )
    after_registration = validate_success(
        api.get_listing(listing["id"], owner_headers), 200
    )
    assert after_registration["version"] == 3
    assert _document_count(api, listing["id"]) == 2

    reread = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert reread["version"] == 3
