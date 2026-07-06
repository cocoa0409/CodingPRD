"""Onboarding, resource creation, read-back, listing, and body validation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    make_coordinator_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


def test_register_property_computes_available_key_copies(api):
    """PRD 3.1: "At registration the derived available_key_copies equals key_copies_total,
    since no copies are yet out or lost."
    PRD 2.4: "On creation, version is 1 and updated_at equals created_at; on every mutation
    that changes the resource, updated_at is refreshed to the current clock instant and version
    is incremented by one."

    Design: Corner/entities/create_property_success_computes_available_copies
    """
    client = fx.create_client(api)
    resp = api.create_property(
        f.create_property_payload(client["id"], size_tier="MEDIUM", has_pets=False,
                                  checklist_config=["MAIL", "PLANTS"], key_copies_total=2), COORD)
    prop = validate_success(resp, expected_status=201)
    assert prop["available_key_copies"] == 2, prop
    assert prop["version"] == 1, prop


def test_get_unknown_booking_returns_not_found(api):
    """PRD 2.5: "the first one that does not correspond to a stored resource fails the request
    with the corresponding not-found error (for example ERR_CLIENT_NOT_FOUND, ERR_PROPERTY_NOT_FOUND,
    ERR_SITTER_NOT_FOUND, ERR_BGCHECK_NOT_FOUND, ERR_COVERAGE_NOT_FOUND, ERR_BOOKING_NOT_FOUND,
    ERR_VISIT_NOT_FOUND, ERR_VISITLOG_NOT_FOUND, ERR_KEY_NOT_FOUND, ERR_INCIDENT_NOT_FOUND, or
    ERR_INVOICE_NOT_FOUND), each returned with HTTP 404."

    Design: Corner/entities/get_booking_not_found_returns_404
    """
    resp = api.get_booking(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND.value, expected_status=404)


def test_create_booking_missing_base_rate_rejected(api):
    """PRD 2.8: "then well-formedness of the request body — required fields present, enumerations
    valid, and the recurring/vacation frequency rule satisfied (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_booking_missing_required_base_rate_returns_422
    """
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"])
    resp = api.create_booking({
        "property_id": prop["id"], "booking_type": "VACATION",
        "start_date": "2026-06-01T00:00:00Z", "end_date": "2026-06-01T00:00:00Z",
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_create_booking_invalid_type_enum_rejected(api):
    """PRD 2.8: "then well-formedness of the request body — required fields present, enumerations
    valid, and the recurring/vacation frequency rule satisfied (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_booking_invalid_enum_type_returns_422
    """
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"])
    resp = api.create_booking(
        f.create_booking_payload(prop["id"], booking_type="WEEKENDS"), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_recurring_booking_without_frequency_rejected(api):
    """PRD 3.3: "A body that violates this pairing — a recurring booking with no frequency, or a
    vacation booking that carries one — is malformed and is rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/recurring_booking_without_frequency_returns_422
    """
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"])
    resp = api.create_booking(
        f.create_booking_payload(prop["id"], booking_type="RECURRING",
                                 start_date="2026-06-01T00:00:00Z",
                                 end_date="2026-06-05T00:00:00Z"), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_created_client_is_immediately_readable(api):
    """PRD 3.1: "A newly created client is initialised with status equal to ACTIVE."
    PRD 3.1: "supplying the client's full_name, email, and optionally a billing_tier of either
    STANDARD or PREMIUM; when omitted, the billing tier defaults to STANDARD."

    Design: Corner/consistency_model/immediate_read_after_create_client
    """
    created = fx.create_client(api, billing_tier="PREMIUM")
    resp = api.get_client(created["id"], COORD)
    got = validate_success(resp)
    assert got["billing_tier"] == "PREMIUM", got
    assert got["status"] == "ACTIVE", got


def test_list_bookings_carries_pagination_envelope(api):
    """PRD 2.3: "The meta block of a list response carries the pagination fields limit, offset,
    total_count, and has_more, where total_count is the size of the full filtered collection and
    has_more is true when records remain beyond the current page."

    Design: Corner/endpoints/list_bookings_returns_pagination_envelope
    """
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"])
    fx.create_booking(api, prop["id"])
    resp = api.list_bookings(COORD, params={"property_id": prop["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta
