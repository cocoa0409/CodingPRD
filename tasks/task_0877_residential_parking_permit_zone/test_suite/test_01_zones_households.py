"""Zone and household creation, system fields, and input validation.

Translates Corner/entities instances. Every test starts from an empty database.
"""
from test_helpers import (
    validate_success, validate_error,
    assert_zone, assert_household,
    create_zone_payload, create_household_payload, create_proof_submission_payload,
    make_resident_headers,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import set_clock, create_zone, register_household


def test_create_zone_returns_201_active_and_zeroed(api, supervisor_headers):
    """PRD §3.1: "A new zone opens in status `ACTIVE` with its `active_permit_count`,
    `waitlist_count`, `fees_collected_cents`, and `fees_refunded_cents` all at zero
    and `version` at 1."

    Design: Corner/entities/create_zone_success_returns_201
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    resp = api.create_zone(create_zone_payload(name="New RPZ", permit_capacity=3), supervisor_headers)
    data = validate_success(resp, 201)
    assert_zone(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["active_permit_count"] == 0
    assert data["waitlist_count"] == 0
    assert data["fees_collected_cents"] == 0
    assert data["fees_refunded_cents"] == 0


def test_get_unknown_zone_returns_not_found(api, supervisor_headers):
    """PRD §2.5: "each referenced resource must exist before the next is considered,
    and any missing resource yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/zone_not_found_returns_404
    """
    resp = api.get_zone(NON_EXISTENT_UUID, supervisor_headers)
    validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


def test_household_missing_contact_email_rejected(api, anonymous_headers):
    """PRD §2.7: "A body that is malformed, omits a required field, carries a bad
    enum value, sets a visitor pass's `valid_until` at or before its `valid_from`,
    or supplies a negative amount is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/household_missing_required_field_returns_invalid_request
    """
    zone = create_zone(api)
    payload = create_household_payload(zone["id"])
    del payload["contact_email"]
    resp = api.create_household(payload, anonymous_headers)
    validate_error(resp, "ERR_VALIDATION", expected_status=400)


def test_new_household_version_one_and_unverified(api, anonymous_headers):
    """PRD §3.2: "It opens `ACTIVE` with `proof_status` `UNVERIFIED`, with
    `proof_verified_at` and `proof_expires_at` both null and `active_permit_count` zero."

    Design: Corner/entities/version_system_field_starts_at_one
    """
    zone = create_zone(api)
    resp = api.create_household(create_household_payload(zone["id"]), anonymous_headers)
    data = validate_success(resp, 201)
    assert_household(data)
    assert data["version"] == 1
    assert data["proof_status"] == "UNVERIFIED"
    assert data["active_permit_count"] == 0


def test_proof_submission_bad_document_type_rejected(api):
    """PRD §2.7: "A body that is malformed, omits a required field, carries a bad
    enum value, sets a visitor pass's `valid_until` at or before its `valid_from`,
    or supplies a negative amount is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/proof_submission_invalid_enum_returns_invalid_request
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    resp = api.create_proof_submission(
        hh["id"], create_proof_submission_payload(document_type="PASSPORT"),
        make_resident_headers(hh["id"]),
    )
    validate_error(resp, "ERR_VALIDATION", expected_status=400)
