"""Entity creation/field invariants, immutability, reverse-reachability listing,
pagination envelope, and the duplicate/stale-version error paths.

Queue B (corner) instances exercised here:
  entities / create_session_package_returns_201_with_fields
  entities / get_booking_not_found_returns_404
  entities / create_booking_missing_required_field_returns_invalid_request
  entities / booking_computed_fields_ignore_client_supplied_values
  entities / create_booking_invalid_enum_session_package_rejected
  entities / proof_selection_immutable_no_version_field
  endpoints / list_bookings_pagination_envelope
  endpoints / list_addon_orders_reverse_reachability_for_booking
  errors / duplicate_gallery_per_booking_returns_duplicate_resource
  errors / stale_booking_version_on_addon_returns_stale_booking_version
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    make_client_headers, make_photographer_headers, assert_session_package,
    assert_proof_selection,
    # fixtures
    setup_draft_booking, setup_shot_booking, create_gallery_in_proofing,
    # factories
    create_session_package_payload, create_booking_payload, add_on_order_payload,
    proof_selection_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# entities / create_session_package_returns_201_with_fields
# ===========================================================================
def test_create_session_package_returns_201_with_defaults(api):
    """PRD §3.1: "Two booleans round out the package: requires_model_release, defaulting
    to false ... and active, defaulting to true."

    POST /studio/session-packages without the two optional booleans -> 201 with
    active=true and requires_model_release=false.

    Design: Corner/entities/create_session_package_returns_201_with_fields
    """
    payload = create_session_package_payload(
        name="Event Premium", session_type="EVENT", tier="PREMIUM", base_fee_cents=400000,
        included_shoot_hours=8, overage_hourly_rate_cents=25000, included_edited_images=200,
        deposit_pct=0.40,
    )
    package = validate_success(api.create_session_package(payload, ADMIN), expected_status=201)
    assert_session_package(package)
    assert package["active"] is True
    assert package["requires_model_release"] is False


# ===========================================================================
# entities / get_booking_not_found_returns_404
# ===========================================================================
def test_get_unknown_booking_returns_not_found(api):
    """PRD §2.7: "Existence of every resource named in the URL path is checked third, left
    to right (ERR_NOT_FOUND)."

    GET /studio/bookings/{random-uuid} -> ERR_NOT_FOUND.

    Design: Corner/entities/get_booking_not_found_returns_404
    """
    validate_error(
        api.get_booking(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_NOT_FOUND.value,
    )


# ===========================================================================
# entities / create_booking_missing_required_field_returns_invalid_request
# ===========================================================================
def test_create_booking_missing_requested_hours_rejected(api):
    """PRD §2.7: "any create or update whose body omits a required field, carries an enum
    value outside its permitted set, or violates a numeric constraint ... is rejected with
    ERR_INVALID_REQUEST." PRD §3.2: "a requested_shoot_hours desired, which must be
    strictly positive."

    POST /studio/bookings omitting requested_shoot_hours -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_booking_missing_required_field_returns_invalid_request
    """
    client = get_success_data(api.create_client(
        {"email": "miss-c@studio.test", "full_name": "C", "phone": "1"}, ADMIN))
    photographer = get_success_data(api.create_photographer(
        {"email": "miss-p@studio.test", "full_name": "P", "skills": ["PHOTO"],
         "hourly_rate_cents": 7000}, ADMIN))
    package = get_success_data(api.create_session_package(
        create_session_package_payload(name="PB Miss"), ADMIN))
    validate_error(
        api.create_booking(
            {"client_id": client["id"], "package_id": package["id"],
             "lead_photographer_id": photographer["id"]},
            make_client_headers(client["id"]),
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# ===========================================================================
# entities / booking_computed_fields_ignore_client_supplied_values
# ===========================================================================
def test_new_booking_starts_draft_unpaid_zero_paid(api):
    """PRD §3.2: "The booking is born in DRAFT workflow_status and UNPAID payment_status,
    with amount_paid_cents, balance_due_cents, and cancellation_fee_cents all initialized
    to zero." PRD §2.4: "a version, an integer that begins at its initial value on creation."

    A freshly created booking has workflow_status DRAFT, payment_status UNPAID,
    amount_paid_cents 0, and version 1.

    Design: Corner/entities/booking_computed_fields_ignore_client_supplied_values
    """
    base = setup_draft_booking()
    booking = base["booking"]
    assert booking["workflow_status"] == "DRAFT"
    assert booking["payment_status"] == "UNPAID"
    assert booking["amount_paid_cents"] == 0
    assert booking["version"] == 1


# ===========================================================================
# entities / create_booking_invalid_enum_session_package_rejected
# ===========================================================================
def test_create_session_package_invalid_tier_rejected(api):
    """PRD §3.1: "a tier (one of BASIC, STANDARD, or PREMIUM)." PRD §2.7: "any create or
    update whose body ... carries an enum value outside its permitted set ... is rejected
    with ERR_INVALID_REQUEST."

    POST /studio/session-packages with tier='GOLD' (outside {BASIC,STANDARD,PREMIUM}) ->
    ERR_INVALID_REQUEST.

    Design: Corner/entities/create_booking_invalid_enum_session_package_rejected
    """
    payload = create_session_package_payload(name="Bad Tier", tier="GOLD")
    validate_error(
        api.create_session_package(payload, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# ===========================================================================
# entities / proof_selection_immutable_no_version_field
# ===========================================================================
def test_proof_selection_has_no_version_field(api):
    """PRD §2.4: "A ProofSelection is immutable once recorded, so it carries only an id and
    a created_at - it has neither an updated_at field nor a version field." PRD §3.7:
    "each selection captures the gallery's current revision_round into its own round_index
    and is immutable thereafter."

    Recording a proof selection on a PROOFING gallery -> 201, round_index 0, no version/
    updated_at fields.

    Design: Corner/entities/proof_selection_immutable_no_version_field
    """
    ctx = setup_shot_booking(
        start_utc="2026-07-01T10:00:00Z", end_utc="2026-07-01T12:00:00Z",
        complete_clock="2026-07-01T12:30:00Z",
    )
    booking, client, photographer = ctx["booking"], ctx["client"], ctx["photographer"]
    gallery = create_gallery_in_proofing(booking["id"], photographer["id"],
                                         delivered_image_count=30)
    selection = validate_success(
        api.create_proof_selection(
            gallery["id"], proof_selection_payload(12), make_client_headers(client["id"])
        ),
        expected_status=201,
    )
    assert_proof_selection(selection)
    assert selection["round_index"] == 0


# ===========================================================================
# endpoints / list_bookings_pagination_envelope
# ===========================================================================
def test_list_bookings_pagination_envelope(api):
    """PRD §2.3: "Every list response reports limit, offset, total_count, and has_more
    inside the meta object of the envelope, where total_count is the count of all matching
    resources before pagination and has_more indicates whether records remain beyond the
    current page."

    A client with two bookings -> response_type array, total_count 2, has_more false.

    Design: Corner/endpoints/list_bookings_pagination_envelope
    """
    base = setup_draft_booking()
    client, package, photographer = base["client"], base["package"], base["photographer"]
    client_h = make_client_headers(client["id"])
    # base already created one booking for this client; add a second.
    get_success_data(api.create_booking(create_booking_payload(
        client["id"], package["id"], photographer["id"], requested_shoot_hours=3), client_h))
    data, meta = validate_paginated(
        api.list_bookings(client_h, params={"client_id": client["id"]})
    )
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert len(data) == 2


# ===========================================================================
# endpoints / list_addon_orders_reverse_reachability_for_booking
# ===========================================================================
def test_list_addon_orders_for_booking(api):
    """PRD §3.8: "Add-on orders can be listed under their booking." PRD §3.8: "For a PRINT
    order the per-unit price earns a marginal volume discount ... the first ten units price
    at the full unit_price_cents."

    A booking with one ORDERED PRINT add-on (10@500 -> 5000) -> GET
    /studio/bookings/{id}/add-on-orders returns it with line_total_cents 5000.

    Design: Corner/endpoints/list_addon_orders_reverse_reachability_for_booking
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    client_h = make_client_headers(client["id"])
    get_success_data(
        api.create_add_on_order(
            booking["id"], add_on_order_payload("PRINT", 10, 500, booking["version"]), client_h
        )
    )
    data, _meta = validate_paginated(api.list_add_on_orders(booking["id"], client_h))
    assert len(data) == 1
    assert data[0]["line_total_cents"] == 5000


# ===========================================================================
# errors / duplicate_gallery_per_booking_returns_duplicate_resource
# ===========================================================================
def test_duplicate_gallery_rejected(api):
    """PRD §3.7: "A Photographer or StudioAdmin creates one Gallery per booking from its
    booking_id - a second gallery on the same booking is rejected with
    ERR_DUPLICATE_RESOURCE."

    A SHOT booking already has one Gallery; a second create -> ERR_DUPLICATE_RESOURCE.

    Design: Corner/errors/duplicate_gallery_per_booking_returns_duplicate_resource
    """
    ctx = setup_shot_booking(
        start_utc="2026-07-01T10:00:00Z", end_utc="2026-07-01T12:00:00Z",
        complete_clock="2026-07-01T12:30:00Z",
    )
    booking, photographer = ctx["booking"], ctx["photographer"]
    photog_h = make_photographer_headers(photographer["id"])
    get_success_data(api.create_gallery({"booking_id": booking["id"]}, photog_h))
    validate_error(
        api.create_gallery({"booking_id": booking["id"]}, photog_h),
        ApiErrorId.ERR_DUPLICATE_RESOURCE.value,
    )


# ===========================================================================
# errors / stale_booking_version_on_addon_returns_stale_booking_version
# ===========================================================================
def test_addon_with_stale_booking_version_rejected(api):
    """PRD §2.6: "Ordering an add-on against a booking requires expected_booking_version in
    the request body, carrying the version of the Booking the client last observed. If the
    booking's current version has moved on since then - because some other writer already
    applied an add-on, a settlement, or another mutation that bumped it - the request is
    rejected with ERR_STALE_BOOKING_VERSION (HTTP 412)."

    One add-on advances the booking version; a second add-on carrying the pre-first-order
    version -> ERR_STALE_BOOKING_VERSION.

    Design: Corner/errors/stale_booking_version_on_addon_returns_stale_booking_version
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    client_h = make_client_headers(client["id"])
    stale_version = booking["version"]
    get_success_data(
        api.create_add_on_order(
            booking["id"], add_on_order_payload("PRINT", 5, 500, stale_version), client_h
        )
    )
    validate_error(
        api.create_add_on_order(
            booking["id"], add_on_order_payload("PRINT", 5, 500, stale_version), client_h
        ),
        ApiErrorId.ERR_STALE_BOOKING_VERSION.value,
    )
