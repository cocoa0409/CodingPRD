"""Producer registry: creation defaults, required fields, uniqueness,
existence checks, pagination/filtering, and the authentication gate
(PRD sections 2.1, 2.3, 2.4, 2.5, 2.9, 3.1).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_producer,
    create_producer,
    create_producer_payload,
    validate_error,
    validate_paginated,
    validate_success,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]


def test_producer_creation_defaults():
    """PRD section 3.1: "A new producer starts `ACTIVE`, with both derived
    counters, `ytd_issued_premium_cents` and `commission_held_cents`, at zero."
    and "leaving `agency_id` null registers an independent producer".
    PRD section 2.5: "All deadlines, windows, and time-stamped transitions are
    evaluated against a logical clock whose startup value is exactly
    2026-08-01T00:00:00Z".

    Design: Corner/entities/producer_creation_required_fields_and_defaults
    """
    resp = api_client.create_producer(
        create_producer_payload(npn="NPN-3001", full_name="Default Check",
                                resident_state_code="CA"),
        LC,
    )
    data = validate_success(resp, 201)
    assert_producer(data)
    assert data["status"] == "ACTIVE"
    assert data["ytd_issued_premium_cents"] == 0
    assert data["commission_held_cents"] == 0
    assert data["agency_id"] is None
    assert_instant_equals(data["created_at"], DEFAULT_CLOCK_ISO, "created_at")


def test_producer_missing_npn_rejected():
    """PRD section 3.1: "A `LicensingCoordinator` creates a producer with the
    producer's National Producer Number in `npn`". PRD section 2.9: "any
    request that is malformed in itself — a missing required field, an invalid
    enum value, a malformed datetime, a non-positive `credit_hours`, an
    `expiration_date` not strictly after `issue_date`, or a uniqueness
    collision on a producer's `npn` or an inquiry's `reference_number` — is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/producer_missing_required_field_returns_invalid_request
    """
    resp = api_client.create_producer(
        {"full_name": "No Npn", "resident_state_code": "CA"}, LC
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_producer_get_not_found():
    """PRD section 2.9: "path identifiers and body foreign-key references
    (`producer_id`, `agency_id`, `license_id`, `application_id`) resolved, left
    to right, with the first missing reference producing `ERR_NOT_FOUND`
    (HTTP 404)".

    Design: Corner/entities/producer_get_not_found_returns_404
    """
    resp = api_client.get_producer(NON_EXISTENT_UUID, LC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_producer_list_pagination_and_status_filter():
    """PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope." PRD section 3.1: "The producer list may be filtered by
    `agency_id` and `status`."

    Design: Corner/entities/producer_list_pagination_and_filter
    """
    for npn, name in (("NPN-3003", "P1"), ("NPN-3004", "P2"), ("NPN-3005", "P3")):
        create_producer(npn=npn, full_name=name)

    page1, meta1 = validate_paginated(
        api_client.list_producers(LC, params={"status": "ACTIVE", "limit": 2, "offset": 0})
    )
    assert len(page1) == 2, f"page 1 should hold 2 items, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api_client.list_producers(LC, params={"status": "ACTIVE", "limit": 2, "offset": 2})
    )
    assert len(page2) == 1, f"page 2 should hold 1 item, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2

    ids = {p["id"] for p in page1} | {p["id"] for p in page2}
    assert len(ids) == 3, "pages must partition the three producers without overlap"


def test_duplicate_npn_rejected():
    """PRD section 3.1: "A `LicensingCoordinator` creates a producer with the
    producer's National Producer Number in `npn` — unique across all producers,
    with a collision rejected as `ERR_INVALID_REQUEST`".

    Design: Corner/validations/duplicate_npn_rejected
    """
    create_producer(npn="NPN-3027", full_name="First")
    resp = api_client.create_producer(
        create_producer_payload(npn="NPN-3027", full_name="Second",
                                resident_state_code="TX"),
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_missing_auth_headers_unauthenticated():
    """PRD section 2.1: "A request that is missing either header, or that names
    a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/missing_auth_headers_unauthenticated
    """
    resp = api_client.create_producer(
        create_producer_payload(npn="NPN-3029", full_name="No Auth"),
        headers=None,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
