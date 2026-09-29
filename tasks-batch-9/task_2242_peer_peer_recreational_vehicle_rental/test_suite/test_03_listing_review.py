"""Onboarding culminates in review: the preconditions that guard
submit-for-review, the approval fork, and the parent-state gate that approval
opens for bookings."""

from test_helpers import (
    ApiErrorId,
    InsuranceStatus,
    ListingStatus,
    OwnerStatus,
    PLATFORM_ADMIN_HEADERS,
    SettlementStatus,
    TripStatus,
    VehicleClass,
    Zone,
    factories,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# The five zones minus the undercarriage: one short of the collective gate.
FOUR_ZONES = (Zone.EXTERIOR_FRONT, Zone.EXTERIOR_REAR, Zone.INTERIOR, Zone.ROOF)


def test_submitting_a_fully_documented_draft_moves_it_into_review(api):
    """PRD 3.2: "An `Owner` submits a `DRAFT` listing, advancing `listing_status`
    from `DRAFT` to `IN_REVIEW`, and three preconditions guard the move." With all
    three satisfied, "The successful submission recomputes `insurance_status` and
    `inspection_photo_zone_count`, sets `listing_status` to `IN_REVIEW`,
    increments the listing's `version` and refreshes its `updated_at`."

    Design: Corner/state_machines/submit_for_review_moves_listing_draft_to_in_review
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    listing, _documents, version_after_uploads = fixtures.seed_documented_listing(
        api, owner["id"]
    )

    response = api.submit_listing_for_review(
        listing["id"], make_owner_headers(owner["id"])
    )
    submitted = validate_success(response, 200)

    assert submitted["listing_status"] == ListingStatus.IN_REVIEW
    assert submitted["insurance_status"] == InsuranceStatus.VERIFIED
    assert submitted["inspection_photo_zone_count"] == 5
    # Eight uploads and three verifications each bumped the parent once.
    assert version_after_uploads == 9
    assert submitted["version"] == 13


def test_four_photographed_zones_do_not_satisfy_the_five_zone_gate(api):
    """PRD 3.2: "the listing's `inspection_photo_zone_count` must equal five —
    that is, all five rig zones must be photographed, with nothing missing and
    nothing extra to count — or the submission is refused with
    `ERR_INSPECTION_PHOTOS_INCOMPLETE`". PRD 2.8 step 28 places that check ahead
    of the document and owner gates.

    Design: Corner/validations/four_valid_inspection_photos_still_fail_the_collective_gate
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])
    listing = fixtures.create_draft_listing(
        api,
        owner["id"],
        nickname="Half Documented Class C",
        vehicle_class=VehicleClass.CLASS_C,
        gvwr_lbs=12000,
        length_ft=28,
        base_nightly_rate_cents=22000,
    )
    documents, _version = fixtures.upload_listing_documents(
        api,
        listing["id"],
        owner["id"],
        listing["version"],
        doc_suffix="agg",
        inspection_prefix="insp-agg",
        zones=FOUR_ZONES,
    )
    fixtures.verify_core_documents(api, documents)

    response = api.submit_listing_for_review(listing["id"], owner_headers)
    validate_error(response, ApiErrorId.INSPECTION_PHOTOS_INCOMPLETE, 422)

    unchanged = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert unchanged["listing_status"] == ListingStatus.DRAFT
    assert unchanged["inspection_photo_zone_count"] == 4
    assert unchanged["insurance_status"] == InsuranceStatus.VERIFIED


def test_an_unverified_insurance_policy_blocks_the_submission(api):
    """PRD 3.2: "For each of `TITLE`, `REGISTRATION` and `INSURANCE_POLICY` there
    must exist a document on the listing of that type whose `verification_status`
    is `VERIFIED`, whose `superseded` is false and whose `expires_on` is on or
    after the clock date; a missing, unverified, superseded or lapsed document of
    any of the three types yields `ERR_REQUIRED_DOCUMENT_MISSING`."

    Design: Corner/errors/unverified_insurance_document_blocks_submit_for_review
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])
    listing = fixtures.create_draft_listing(api, owner["id"])
    documents, _version = fixtures.upload_listing_documents(
        api, listing["id"], owner["id"], listing["version"]
    )
    for key in ("TITLE", "REGISTRATION"):
        get_success_data(
            api.verify_vehicle_document(documents[key], PLATFORM_ADMIN_HEADERS)
        )

    response = api.submit_listing_for_review(listing["id"], owner_headers)
    validate_error(response, ApiErrorId.REQUIRED_DOCUMENT_MISSING, 422)

    unchanged = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert unchanged["listing_status"] == ListingStatus.DRAFT
    assert unchanged["insurance_status"] == InsuranceStatus.PENDING

    policy = validate_success(
        api.get_vehicle_document(documents["INSURANCE_POLICY"], owner_headers), 200
    )
    assert policy["verification_status"] == "PENDING"


def test_a_suspended_owner_cannot_submit_even_a_complete_listing(api):
    """PRD 3.2: "The owner's `status` must be `ACTIVE`, or the submission is
    refused with `ERR_OWNER_SUSPENDED`." PRD 3.1 puts the owner there: "If the
    resulting total reaches or exceeds twelve points, the owner's `status` becomes
    `SUSPENDED`". PRD 2.8 ranks the gate last of the three, at step 30: "**Owner
    in good standing** — the owner's `status` is `ACTIVE`, otherwise
    `ERR_OWNER_SUSPENDED` (422)."

    Design: Corner/errors/suspended_owner_cannot_submit_a_fully_documented_listing
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    owner_headers = make_owner_headers(owner["id"])
    listing, _documents, _version = fixtures.seed_documented_listing(api, owner["id"])
    fixtures.adjust_owner_points(api, owner["id"], 12, "repeat owner cancellations")

    response = api.submit_listing_for_review(listing["id"], owner_headers)
    validate_error(response, ApiErrorId.OWNER_SUSPENDED, 422)

    suspended = validate_success(api.get_owner(owner["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert suspended["status"] == OwnerStatus.SUSPENDED
    assert suspended["owner_penalty_points"] == 12

    unchanged = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert unchanged["listing_status"] == ListingStatus.DRAFT
    assert unchanged["inspection_photo_zone_count"] == 5


def test_approval_moves_the_listing_to_listed_and_counts_it_on_the_owner(api):
    """PRD 3.2: "On `APPROVE`, the listing moves `IN_REVIEW → LISTED`, the owner's
    `listed_listing_count` increases by one, the listing's `version` increments and
    the owner's `version` increments; approval additionally requires that the
    listing's `insurance_status` be `VERIFIED` at that moment".

    Design: Corner/state_machines/listing_approval_increments_the_owners_listed_count
    """
    fixtures.set_clock(api)
    owner = fixtures.create_owner(api)
    listing, _documents, _version = fixtures.seed_documented_listing(api, owner["id"])
    fixtures.submit_listing(api, listing["id"], owner["id"])

    response = api.decide_listing(
        listing["id"], factories.listing_decision_payload("APPROVE"), PLATFORM_ADMIN_HEADERS
    )
    listed = validate_success(response, 200)

    assert listed["listing_status"] == ListingStatus.LISTED
    assert listed["insurance_status"] == InsuranceStatus.VERIFIED
    assert listed["version"] == 14

    counted = validate_success(api.get_owner(owner["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert counted["listed_listing_count"] == 1
    assert counted["version"] == 2


def test_insurance_that_lapses_after_approval_stops_new_bookings(api):
    """PRD 3.2 derives the field from the clock rather than freezing it: insurance
    "is `EXPIRED` when such a verified, non-superseded insurance document exists
    but its `expires_on` falls before the clock date". PRD 2.8 step 22 then bites
    at booking request: "**Listing insurance verified** — the listing's
    `insurance_status` is `VERIFIED`, otherwise
    `ERR_LISTING_INSURANCE_NOT_VERIFIED` (422)."

    Design: Corner/errors/insurance_that_expired_after_approval_blocks_new_bookings
    """
    world = fixtures.seed_configuration(api)
    owner_headers = world.owner_headers
    listing = fixtures.create_draft_listing(api, world.owner_id)
    version = listing["version"]

    title = get_success_data(
        api.create_vehicle_document(
            factories.title_document_payload(listing["id"], version), owner_headers
        )
    )
    version += 1
    registration = get_success_data(
        api.create_vehicle_document(
            factories.registration_document_payload(listing["id"], version), owner_headers
        )
    )
    version += 1
    short_policy = get_success_data(
        api.create_vehicle_document(
            factories.insurance_document_payload(
                listing["id"],
                version,
                expires_on="2026-08-15",
                image_ref="s3://docs/ins-short.pdf",
            ),
            owner_headers,
        )
    )
    version += 1
    for zone in factories.all_inspection_zones():
        get_success_data(
            api.create_vehicle_document(
                factories.inspection_photo_payload(listing["id"], zone, version),
                owner_headers,
            )
        )
        version += 1
    for document_id in (title["id"], registration["id"], short_policy["id"]):
        get_success_data(api.verify_vehicle_document(document_id, PLATFORM_ADMIN_HEADERS))
    fixtures.submit_listing(api, listing["id"], world.owner_id)
    fixtures.approve_listing(api, listing["id"])
    fixtures.fund_renter(api, world.renter_id)

    fixtures.set_clock(api, "2026-08-20T00:00:00Z")

    response = api.create_booking(
        factories.booking_payload(
            listing["id"], world.renter_id, world.plan_id, world.policy_id
        ),
        world.renter_headers,
    )
    validate_error(response, ApiErrorId.LISTING_INSURANCE_NOT_VERIFIED, 422)

    lapsed = validate_success(api.get_listing(listing["id"], owner_headers), 200)
    assert lapsed["insurance_status"] == InsuranceStatus.EXPIRED
    assert lapsed["listing_status"] == ListingStatus.LISTED

    _rows, meta = validate_paginated(
        api.list_bookings(factories.page_params(), PLATFORM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_listing_still_in_review_cannot_be_booked(api):
    """PRD 2.8 step 14: "**Listing bookable** — the listing referenced by the
    request has `listing_status` equal to `LISTED`, otherwise
    `ERR_LISTING_NOT_BOOKABLE` (409). Applies to booking request, owner approval
    and renter confirmation." `IN_REVIEW` is a state PRD 3.2 puts on the happy
    path, yet it is not `LISTED`.

    Design: Difficulty/cross_entity_state_dependency/booking_creation_is_gated_by_the_parent_listings_review_state
    """
    world = fixtures.seed_configuration(api)
    listing, _documents, _version = fixtures.seed_documented_listing(api, world.owner_id)
    fixtures.submit_listing(api, listing["id"], world.owner_id)
    fixtures.fund_renter(api, world.renter_id)

    response = api.create_booking(
        factories.booking_payload(
            listing["id"], world.renter_id, world.plan_id, world.policy_id
        ),
        world.renter_headers,
    )
    validate_error(response, ApiErrorId.LISTING_NOT_BOOKABLE, 409)

    _rows, meta = validate_paginated(
        api.list_bookings(
            factories.page_params(listing_id=listing["id"]), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 0


def test_the_same_booking_body_is_accepted_once_the_platform_approves(api):
    """PRD 3.2: "On `APPROVE`, the listing moves `IN_REVIEW → LISTED`". PRD 2.8
    step 14 then stops objecting, and PRD 3.4 pins what the accepted booking
    freezes: `renter_record_points_snapshot` "reads only the **single newest**
    driving-record check — the same selector that `driving_record_status` uses,
    descending `checked_at` with descending `created_at` as tie-break — taking that
    one check's `violation_points`".

    Design: Difficulty/cross_entity_state_dependency/booking_creation_is_gated_by_the_parent_listings_review_state
    """
    world = fixtures.seed_configuration(api)
    listing, _documents, _version = fixtures.seed_documented_listing(api, world.owner_id)
    fixtures.submit_listing(api, listing["id"], world.owner_id)
    fixtures.fund_renter(api, world.renter_id)
    payload = factories.booking_payload(
        listing["id"], world.renter_id, world.plan_id, world.policy_id
    )
    validate_error(
        api.create_booking(payload, world.renter_headers),
        ApiErrorId.LISTING_NOT_BOOKABLE,
        409,
    )

    listed = validate_success(
        api.decide_listing(
            listing["id"],
            factories.listing_decision_payload("APPROVE"),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )
    assert listed["listing_status"] == ListingStatus.LISTED
    assert listed["insurance_status"] == InsuranceStatus.VERIFIED

    booking = validate_success(api.create_booking(payload, world.renter_headers), 201)
    assert booking["trip_status"] == TripStatus.REQUESTED
    assert booking["settlement_status"] == SettlementStatus.NONE
    assert booking["nights"] == 4
    assert booking["renter_age_years_at_start"] == 32
    assert booking["renter_record_points_snapshot"] == 2

    _rows, meta = validate_paginated(
        api.list_bookings(
            factories.page_params(listing_id=listing["id"]), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 1
