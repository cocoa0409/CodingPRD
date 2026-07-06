"""Roster creation, reference-data existence, and request-body validation.

Covers officiant creation defaults, missing/out-of-range field validation, and the
left-to-right not-found resolution (PRD Sections 2.10, 3.1, 3.2).
"""
from test_helpers import (
    fixtures as fx,
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    make_coordinator_headers, make_couple_headers,
    create_officiant_payload, create_booking_payload,
    assert_officiant,
)

COORD = make_coordinator_headers()


def test_create_officiant_starts_pending_with_computed_defaults(api):
    """PRD §3.1: "A newly registered officiant begins in status `PENDING_REVIEW`
    with `active_hold_count` at 0, `escrow_balance_cents` at 0, `displayed_rating`
    and `internal_rating` at `null`, and `published_review_count` at 0."
    PRD §2.4: "`version` is an integer that begins at creation and increments by
    one on every mutation of the resource, including mutations to its computed fields."

    Design: Corner/entities/create_officiant_returns_201_with_computed_defaults
    """
    resp = api.create_officiant(
        create_officiant_payload(full_name="Ada Noe", email="ada@x.com"), COORD
    )
    data = validate_success(resp, 201)
    assert_officiant(data)
    assert data["status"] == "PENDING_REVIEW"
    assert data["active_hold_count"] == 0
    assert data["escrow_balance_cents"] == 0
    assert data["displayed_rating"] is None
    assert data["internal_rating"] is None
    assert data["published_review_count"] == 0
    assert data["version"] == 1


def test_create_booking_missing_required_style_rejected(api):
    """PRD §2.10: "the body's shape is validated (`ERR_VALIDATION`): required
    fields present, enum values within their allowed sets, `rating` an integer
    from 1 through 5, `ceremony_end` strictly after `ceremony_start`, and
    `expiry_date` strictly after `issued_date`."

    Design: Corner/entities/create_booking_missing_required_field_returns_validation
    """
    ref = fx.setup_reference(api)
    payload = create_booking_payload(
        ref.officiant["id"], ref.couple["id"], ref.package["id"], ref.venue["id"]
    )
    payload.pop("required_style")
    resp = api.create_booking(payload, make_couple_headers(ref.couple["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_review_rating_out_of_range_rejected(api):
    """PRD §2.10: "the body's shape is validated (`ERR_VALIDATION`): required
    fields present, enum values within their allowed sets, `rating` an integer
    from 1 through 5, `ceremony_end` strictly after `ceremony_start`, and
    `expiry_date` strictly after `issued_date`."

    Design: Corner/entities/create_review_rating_out_of_range_returns_validation
    """
    ctx = fx.setup_completed_booking(api)
    resp = api.create_review(
        {"booking_id": ctx.booking["id"], "rating": 6, "text": "Too high"},
        make_couple_headers(ctx.couple["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# --- Not found on GET by unknown id (PRD §2.10) ---

def test_get_booking_nonexistent_returns_not_found(api):
    """PRD §2.10: "returning the corresponding not-found error for the first
    missing reference: `ERR_OFFICIANT_NOT_FOUND`, `ERR_COUPLE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, `ERR_SCRIPT_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`."

    Design: Corner/entities/get_booking_nonexistent_returns_not_found
    """
    resp = api.get_booking(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND.value)


def test_get_date_hold_nonexistent_returns_not_found(api):
    """PRD §2.10: "returning the corresponding not-found error for the first
    missing reference: `ERR_OFFICIANT_NOT_FOUND`, `ERR_COUPLE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, `ERR_SCRIPT_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`."

    Design: Corner/entities/get_date_hold_nonexistent_returns_not_found
    """
    resp = api.get_date_hold(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_HOLD_NOT_FOUND.value)


def test_get_ceremony_script_nonexistent_returns_not_found(api):
    """PRD §2.10: "returning the corresponding not-found error for the first
    missing reference: `ERR_OFFICIANT_NOT_FOUND`, `ERR_COUPLE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, `ERR_SCRIPT_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`."

    Design: Corner/entities/get_ceremony_script_nonexistent_returns_not_found
    """
    resp = api.get_ceremony_script(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_SCRIPT_NOT_FOUND.value)


def test_get_rehearsal_nonexistent_returns_not_found(api):
    """PRD §2.10: "returning the corresponding not-found error for the first
    missing reference: `ERR_OFFICIANT_NOT_FOUND`, `ERR_COUPLE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, `ERR_SCRIPT_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`."

    Design: Corner/entities/get_rehearsal_nonexistent_returns_not_found
    """
    resp = api.get_rehearsal(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_REHEARSAL_NOT_FOUND.value)


def test_get_marriage_license_nonexistent_returns_not_found(api):
    """PRD §2.10: "returning the corresponding not-found error for the first
    missing reference: `ERR_OFFICIANT_NOT_FOUND`, `ERR_COUPLE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, `ERR_SCRIPT_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`."

    Design: Corner/entities/get_marriage_license_nonexistent_returns_not_found
    """
    resp = api.get_marriage_license(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_FOUND.value)


def test_get_review_nonexistent_returns_not_found(api):
    """PRD §2.10: "returning the corresponding not-found error for the first
    missing reference: `ERR_OFFICIANT_NOT_FOUND`, `ERR_COUPLE_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, `ERR_SCRIPT_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`."

    Design: Corner/entities/get_review_nonexistent_returns_not_found
    """
    resp = api.get_review(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_FOUND.value)


# --- Not found on booking foreign keys, resolved left-to-right (PRD §2.10) ---

def test_create_booking_unknown_officiant_returns_not_found(api):
    """PRD §2.10: "resolving references left to right in the order officiant,
    couple, package, venue, booking, hold, script, rehearsal, license, review,
    and returning the corresponding not-found error for the first missing
    reference: `ERR_OFFICIANT_NOT_FOUND`, ..."

    Design: Corner/entities/create_booking_unknown_officiant_returns_not_found
    """
    couple = fx.create_couple(api)
    package = fx.create_package(api)
    venue = fx.create_venue(api, jurisdiction="CA")
    payload = create_booking_payload(NON_EXISTENT_UUID, couple["id"], package["id"], venue["id"])
    resp = api.create_booking(payload, make_couple_headers(couple["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFICIANT_NOT_FOUND.value)


def test_create_booking_unknown_couple_returns_not_found(api):
    """PRD §2.10: "resolving references left to right in the order officiant,
    couple, package, venue, booking, hold, script, rehearsal, license, review,
    and returning the corresponding not-found error for the first missing
    reference: ... `ERR_COUPLE_NOT_FOUND`, ..."

    Design: Corner/entities/create_booking_unknown_couple_returns_not_found
    """
    officiant = fx.create_active_officiant(api)
    package = fx.create_package(api)
    venue = fx.create_venue(api, jurisdiction="CA")
    payload = create_booking_payload(officiant["id"], NON_EXISTENT_UUID, package["id"], venue["id"])
    # Coordinator caller: opaque, so the missing-couple existence check is reached
    # (a Couple caller would fail the ownership check first).
    resp = api.create_booking(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_COUPLE_NOT_FOUND.value)


def test_create_booking_unknown_package_returns_not_found(api):
    """PRD §2.10: "resolving references left to right in the order officiant,
    couple, package, venue, booking, hold, script, rehearsal, license, review,
    and returning the corresponding not-found error for the first missing
    reference: ... `ERR_PACKAGE_NOT_FOUND`, ..."

    Design: Corner/entities/create_booking_unknown_package_returns_not_found
    """
    officiant = fx.create_active_officiant(api)
    couple = fx.create_couple(api)
    venue = fx.create_venue(api, jurisdiction="CA")
    payload = create_booking_payload(officiant["id"], couple["id"], NON_EXISTENT_UUID, venue["id"])
    resp = api.create_booking(payload, make_couple_headers(couple["id"]))
    validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_FOUND.value)


def test_create_booking_unknown_venue_returns_not_found(api):
    """PRD §2.10: "resolving references left to right in the order officiant,
    couple, package, venue, booking, hold, script, rehearsal, license, review,
    and returning the corresponding not-found error for the first missing
    reference: ... `ERR_VENUE_NOT_FOUND`, ..."

    Design: Corner/entities/create_booking_unknown_venue_returns_not_found
    """
    officiant = fx.create_active_officiant(api)
    couple = fx.create_couple(api)
    package = fx.create_package(api)
    payload = create_booking_payload(officiant["id"], couple["id"], package["id"], NON_EXISTENT_UUID)
    resp = api.create_booking(payload, make_couple_headers(couple["id"]))
    validate_error(resp, ApiErrorId.ERR_VENUE_NOT_FOUND.value)
