"""Listing CRUD and defaults, RBAC and ownership, authentication, body
validation, and the validation-priority-pair conflicts.

Covers difficulty rule priority_pair_validation_conflict (both halves) plus
corner entities / rbac instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    make_host_headers, make_guest_headers, admin_headers, anonymous_headers, TEST_USERS,
    create_host, create_guest, create_draft_listing, create_listed_listing,
    add_rate_plan, get_calendar_version, create_booking,
    create_listing_payload, create_booking_payload, setup_approved_booking,
    setup_completed_booking, setup_screening_booking,
)


# ==========================================================================
# Difficulty: priority_pair_validation_conflict
# ==========================================================================
def test_cancel_completed_booking_state_error(api):
    """PRD §2.9: "then whether the requested state transition is defined from the
    resource's current state (`ERR_INVALID_STATE`). Domain-specific business
    checks are evaluated only after all of the foregoing pass."
    PRD §3.9: "A guest may cancel their own booking from either `REQUESTED` or
    `CONFIRMED`, both leading to the terminal `CANCELLED`."

    A COMPLETED booking is not a defined cancel from-state, so the state check
    fires with ERR_INVALID_STATE before any temporal check.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_cancel_completed_booking
    """
    ctx = setup_completed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "security_deposit_cents": 0, "payout_delay_days": 1},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
        check_in_clock="2026-07-10T12:00:00Z", check_out_clock="2026-07-13T12:00:00Z",
    )
    guest, booking = ctx["guest"], ctx["booking"]
    assert booking["status"] == "COMPLETED"
    resp = api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_completed_booking_leaves_state_unchanged(api):
    """PRD §2.9: "then whether the requested state transition is defined from the
    resource's current state (`ERR_INVALID_STATE`). Domain-specific business
    checks are evaluated only after all of the foregoing pass."
    PRD §3.6: "The owning host completes the stay, advancing `IN_STAY` to
    `COMPLETED` (terminal)."

    Second test of the state-beats-temporal pair: the rejected cancel must not
    mutate the COMPLETED booking (the state guard short-circuits before any
    refund/temporal logic could run).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_cancel_completed_booking
    """
    ctx = setup_completed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "security_deposit_cents": 0, "payout_delay_days": 1},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
        check_in_clock="2026-07-10T12:00:00Z", check_out_clock="2026-07-13T12:00:00Z",
    )
    host, guest, booking = ctx["host"], ctx["guest"], ctx["booking"]
    resp = api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_booking(booking["id"], headers=make_host_headers(host["id"])))
    assert after["status"] == "COMPLETED", \
        f"rejected cancel must leave booking COMPLETED, got {after['status']}"
    assert after["refund_cents"] == 0, \
        f"rejected cancel must not write a refund, got {after['refund_cents']}"


def test_approve_failed_screen_safety_error(api):
    """PRD §3.5: "the host may approve, advancing `SCREENING` to `APPROVED`, but
    approval is gated on the booking's latest screening result being `PASSED`; an
    approve attempt while the latest result is not `PASSED` is rejected with
    `ERR_SCREENING_NOT_PASSED` (HTTP 409)."

    The booking is in SCREENING (a valid approve from-state) so the state
    precondition holds; the business_safety screening check is what fires.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_approve_unscreened_path
    """
    ctx = setup_screening_booking(guest_overrides={"govt_id_verified": False})
    host, booking = ctx["host"], ctx["booking"]
    assert booking["status"] == "SCREENING"
    resp = api.approve_booking(booking["id"], headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_PASSED.value)


def test_approve_chargeback_screen_safety_error(api):
    """PRD §3.5: "an approve attempt while the latest result is not `PASSED` is
    rejected with `ERR_SCREENING_NOT_PASSED` (HTTP 409)."
    PRD §3.5: "The screening result resolves to `PASSED` only when all three
    conditions hold: the guest's `govt_id_verified` is true, the guest's
    `chargeback_flag` is false, and the computed risk score is strictly less than
    50."

    Second test of the safety-beats-constraint pair, via the chargeback
    disqualifier: the booking is still in the valid SCREENING from-state, so the
    safety check fires rather than ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_approve_unscreened_path
    """
    ctx = setup_screening_booking(
        guest_overrides={"govt_id_verified": True, "prior_cancellations": 0,
                         "chargeback_flag": True})
    host, booking = ctx["host"], ctx["booking"]
    assert booking["status"] == "SCREENING"
    resp = api.approve_booking(booking["id"], headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_PASSED.value)


# ==========================================================================
# Corner: entities (listing CRUD, defaults, enum, required)
# ==========================================================================
def test_create_listing_returns_201_in_draft(api):
    """PRD §3.1: "A new listing is created in `DRAFT` with its `calendar_version`
    initialized to 1."
    PRD §2.4: "an integer `version` that begins at 1 on creation."

    Design: Corner/entities/create_listing_returns_201_with_all_fields
    """
    host = create_host()
    resp = api.create_listing(
        create_listing_payload(host["id"], title="L", base_nightly_rate_cents=20000,
                               cleaning_fee_cents=5000),
        headers=make_host_headers(host["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"new listing should be DRAFT, got {data['status']}"
    assert data["calendar_version"] == 1, f"calendar_version should init to 1, got {data['calendar_version']}"
    assert data["version"] == 1, f"version should init to 1, got {data['version']}"


def test_get_listing_returns_stored_entity(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/get_listing_returns_stored_entity
    """
    host = create_host()
    _, listing = create_draft_listing(host=host,
                                      listing_overrides={"base_nightly_rate_cents": 25000})
    resp = api.get_listing(listing["id"], headers=make_host_headers(host["id"]))
    data = validate_success(resp)
    assert data["base_nightly_rate_cents"] == 25000, \
        f"GET should return stored base_nightly_rate_cents 25000, got {data['base_nightly_rate_cents']}"


def test_list_listings_paginated_envelope(api):
    """PRD §2.3: "For every list response, the `meta` object carries `limit`,
    `offset`, `total_count` (the number of records matching the query before
    pagination), and `has_more` (true when records remain beyond the current
    page)."

    Design: Corner/entities/list_listings_paginated_envelope
    """
    host = create_host()
    create_draft_listing(host=host)
    resp = api.list_listings(headers=make_host_headers(host["id"]),
                             params={"host_id": host["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1, f"total_count should be >= 1, got {meta['total_count']}"
    assert isinstance(meta["has_more"], bool)


def test_get_listing_not_found(api):
    """PRD §2.8: "Path parameters are validated left to right: the parent id is
    resolved first, and if any path-referenced resource does not exist the
    request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any deeper
    validation runs."

    Design: Corner/entities/get_listing_not_found_returns_404
    """
    host = create_host()
    resp = api.get_listing(NON_EXISTENT_UUID, headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_listing_missing_required_field(api):
    """PRD §2.9: "generic structural problems — a missing required field, a wrong
    type, or an unrecognized enum value — are reported as `ERR_VALIDATION`
    (HTTP 422)."
    PRD §3.1: "A host creates a `Listing` by supplying its `host_id`, a `title`,
    a `base_nightly_rate_cents` (which must be strictly greater than zero), and a
    `cleaning_fee_cents` (which must be zero or greater)."

    Design: Corner/entities/create_listing_missing_required_field_returns_422
    """
    host = create_host()
    resp = api.create_listing(
        {"host_id": host["id"], "title": "L5", "cleaning_fee_cents": 5000},
        headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_listing_default_cancellation_tier_moderate(api):
    """PRD §3.1: "`cancellation_tier` defaults to `MODERATE` and must be one of
    `FLEXIBLE`, `MODERATE`, or `STRICT`."

    Design: Corner/entities/listing_default_cancellation_tier_applied
    """
    host = create_host()
    _, listing = create_draft_listing(host=host)
    assert listing["cancellation_tier"] == "MODERATE", \
        f"default cancellation_tier should be MODERATE, got {listing['cancellation_tier']}"


def test_invalid_enum_cancellation_tier_rejected(api):
    """PRD §2.9: "generic structural problems — a missing required field, a wrong
    type, or an unrecognized enum value — are reported as `ERR_VALIDATION`
    (HTTP 422)."
    PRD §3.1: "`cancellation_tier` defaults to `MODERATE` and must be one of
    `FLEXIBLE`, `MODERATE`, or `STRICT`."

    Design: Corner/entities/invalid_enum_cancellation_tier_rejected
    """
    host = create_host()
    resp = api.create_listing(
        create_listing_payload(host["id"], cancellation_tier="PREMIUM"),
        headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ==========================================================================
# Corner: rbac
# ==========================================================================
def test_guest_cannot_publish_listing(api):
    """PRD §2.1: "If both headers are present and well-formed but the named role
    is not permitted to perform the requested operation, the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Per PRD §4, POST /listings/{id}/publish is a Host-only operation.

    Design: Corner/rbac/guest_cannot_publish_listing
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True)
    _, listing = create_draft_listing(host=host)
    add_rate_plan(host, listing)
    resp = api.publish_listing(listing["id"], headers=make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_host_cannot_confirm_booking(api):
    """PRD §2.1: "If both headers are present and well-formed but the named role
    is not permitted to perform the requested operation, the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Per PRD §4, POST /bookings/{id}/confirm is a Guest-only operation.

    Design: Corner/rbac/host_cannot_confirm_booking
    """
    ctx = setup_approved_booking()
    host, booking = ctx["host"], ctx["booking"]
    resp = api.confirm_booking(booking["id"], headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_host_not_owner_cannot_snooze(api):
    """PRD §2.1: "When an entity-backed caller is authenticated and authorized for
    the operation's role but is acting on a resource they do not own — a host on
    a listing whose `host_id` is not their `id`, or a guest on a booking whose
    `guest_id` is not their `id` — the request is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/host_not_owner_cannot_snooze_other_listing
    """
    host_a = create_host(email="a@x.com")
    host_b = create_host(email="b@x.com")
    _, listing = create_listed_listing(host=host_a)
    resp = api.snooze_listing(listing["id"], headers=make_host_headers(host_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unauthenticated_create_listing_rejected(api):
    """PRD §2.1: "Every request other than the open registration and clock
    endpoints must carry two headers: `X-User-ID`, identifying the calling
    principal, and `X-User-Role`, naming the principal's role. ... If either
    header is missing or malformed on a protected endpoint, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_create_listing_rejected
    """
    host = create_host()
    resp = api.create_listing(
        create_listing_payload(host["id"]),
        headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
