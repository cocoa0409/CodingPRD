"""Entity creation, retrieval, listing, defaults, system/computed fields, FK
integrity.

Corner queue B: section entities.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_borrower_headers,
    assert_borrower,
    assert_rate_grid_entry,
    create_borrower_payload,
    create_abs_pool_payload,
    create_rate_grid_entry_payload,
    create_application_payload,
    create_cosigner_payload,
    create_borrower,
    create_application,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BORROWER = TEST_USERS["borrower_headers"]


def test_create_borrower_returns_201_with_defaults(api):
    """PRD 3.1: "Every new borrower starts at member_tier NONE"
    PRD 2.4: "version, an integer that begins at 1 on creation"

    Design: Corner/entities/create_borrower_returns_201_with_defaults
    """
    resp = api.create_borrower(create_borrower_payload(
        email="corner.b1@x.com", full_name="Corner B1", annual_income_cents=9_000_000,
        fico_band="PRIME"), BORROWER)
    data = validate_success(resp, 201)
    assert data["member_tier"] == "NONE", f"member_tier should default to NONE, got {data['member_tier']}"
    assert data["version"] == 1, f"version should begin at 1, got {data['version']}"
    for field in ("email", "full_name", "annual_income_cents", "fico_band", "id", "created_at", "updated_at"):
        assert field in data, f"response must include {field}"
    assert_borrower(data)


def test_get_borrower_returns_stored_entity(api):
    """PRD 3.1: "A borrower is registered with an email, a full_name, a
    self-reported annual_income_cents, and a self-reported fico_band."

    Design: Corner/entities/get_borrower_returns_stored_entity
    """
    created = create_borrower(email="corner.b2@x.com", full_name="Corner B2",
                              annual_income_cents=5_000_000, fico_band="NEAR_PRIME")
    resp = api.get_borrower(created["id"], ADMIN)
    data = validate_success(resp, 200)
    assert data["email"] == "corner.b2@x.com"
    assert data["full_name"] == "Corner B2"


def test_list_rate_grid_entries_paginated_envelope(api):
    """PRD 2.3: "Every list response surfaces limit, offset, total_count, and
    has_more in the meta object, where total_count is the number of matching
    records before paging and has_more indicates whether records remain beyond
    the returned page."

    Design: Corner/entities/list_rate_grid_entries_paginated_envelope
    """
    get_success_data(api.create_rate_grid_entry(create_rate_grid_entry_payload(
        rate_type="FIXED", term_months=60, min_fico_band="NEAR_PRIME", base_apr_bps=700, index_apr_bps=0), ADMIN))
    get_success_data(api.create_rate_grid_entry(create_rate_grid_entry_payload(
        rate_type="VARIABLE", term_months=84, min_fico_band="PRIME", base_apr_bps=500, index_apr_bps=120), ADMIN))
    resp = api.list_rate_grid_entries(ADMIN, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is False


def test_get_borrower_not_found_returns_404(api):
    """PRD 2.5: "the first reference that fails to resolve yields ERR_NOT_FOUND
    (HTTP 404)."

    Design: Corner/entities/get_borrower_not_found_returns_404
    """
    resp = api.get_borrower("00000000-0000-4000-8000-0000000000aa", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_application_missing_required_field_invalid_request(api):
    """PRD 2.6: "Malformed bodies — a missing required field, a wrong type, an
    invalid enum value, or a non-positive amount where a positive one is required
    — are rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_application_missing_required_field_invalid_request
    """
    borrower = create_borrower(email="corner.b3@x.com", full_name="Corner B3",
                               annual_income_cents=5_000_000, fico_band="PRIME")
    resp = api.create_application(
        {"borrower_id": borrower["id"], "requested_term_months": 60, "requested_rate_type": "FIXED"},
        make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_application_non_positive_principal_invalid_request(api):
    """PRD 3.2: "the requested_principal_cents it wants to refinance (which must
    be greater than 0)"
    PRD 2.6: "a non-positive amount where a positive one is required — are
    rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_application_non_positive_principal_invalid_request
    """
    borrower = create_borrower(email="corner.b4@x.com", full_name="Corner B4",
                               annual_income_cents=5_000_000, fico_band="PRIME")
    resp = api.create_application(
        create_application_payload(borrower_id=borrower["id"], requested_principal_cents=0,
                                   requested_term_months=60, requested_rate_type="FIXED"),
        make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_application_invalid_enum_term_invalid_request(api):
    """PRD 3.2: "a requested_term_months (one of 60, 84, 120, 180, or 240)"
    PRD 2.6: "Malformed bodies — a missing required field, a wrong type, an
    invalid enum value, or a non-positive amount where a positive one is required
    — are rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_application_invalid_enum_term_invalid_request
    """
    borrower = create_borrower(email="corner.b5@x.com", full_name="Corner B5",
                               annual_income_cents=5_000_000, fico_band="PRIME")
    resp = api.create_application(
        create_application_payload(borrower_id=borrower["id"], requested_principal_cents=4_000_000,
                                   requested_term_months=72, requested_rate_type="FIXED"),
        make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_rate_grid_entry_index_apr_default_zero_when_omitted(api):
    """PRD 3.1: "for fixed rows it is 0 and may be omitted on creation, defaulting
    to 0."

    Design: Corner/entities/rate_grid_entry_index_apr_default_zero_when_omitted
    """
    resp = api.create_rate_grid_entry(
        {"rate_type": "FIXED", "term_months": 120, "min_fico_band": "PRIME", "base_apr_bps": 600}, ADMIN)
    data = validate_success(resp, 201)
    assert data["index_apr_bps"] == 0, f"index_apr_bps should default to 0, got {data['index_apr_bps']}"


def test_abs_pool_system_fields_committed_zero_status_open(api):
    """PRD 3.1: "On creation, a pool's committed_principal_cents — the running sum
    of the original principal of every loan tagged into it — is initialized to 0,
    and its status is OPEN."

    Design: Corner/entities/abs_pool_system_fields_committed_zero_status_open
    """
    resp = api.create_abs_pool(create_abs_pool_payload(
        pool_code="CORNER-POOL-1", max_principal_cents=10_000_000, min_fico_band="SUBPRIME",
        allowed_rate_type="ANY"), ADMIN)
    data = validate_success(resp, 201)
    assert data["committed_principal_cents"] == 0
    assert data["status"] == "OPEN"


def test_rate_grid_entry_immutable_no_version_field(api):
    """PRD 2.4: "A RateGridEntry and an AuditEvent are append-style records that
    carry only id and created_at; they have no updated_at and no version, because
    they are never mutated after creation."

    Design: Corner/entities/rate_grid_entry_immutable_no_version_field
    """
    resp = api.create_rate_grid_entry(create_rate_grid_entry_payload(
        rate_type="FIXED", term_months=180, min_fico_band="NEAR_PRIME", base_apr_bps=800,
        index_apr_bps=0), ADMIN)
    data = validate_success(resp, 201)
    assert "id" in data and "created_at" in data
    assert "version" not in data, "RateGridEntry must not expose version"
    assert "updated_at" not in data, "RateGridEntry must not expose updated_at"
    assert_rate_grid_entry(data)


def test_application_borrower_fk_nonexistent_returns_404(api):
    """PRD 2.5: "When a request names a resource through a path identifier or
    through a foreign-key field in the body, each referenced resource must resolve
    to an existing record, checked in order of appearance; the first reference
    that fails to resolve yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/application_borrower_fk_nonexistent_returns_404
    """
    resp = api.create_application(
        create_application_payload(borrower_id="00000000-0000-4000-8000-0000000000bb",
                                   requested_principal_cents=4_000_000, requested_term_months=60,
                                   requested_rate_type="FIXED"),
        make_borrower_headers("00000000-0000-4000-8000-0000000000bb"))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_cosigner_consent_status_initial_invited(api):
    """PRD 3.3: "The cosigner begins in consent_status INVITED"
    PRD 3.3: "Its on_time_streak — the count of consecutive on-time payments on
    the eventual funded loan — starts at 0."

    Design: Corner/entities/cosigner_consent_status_initial_invited
    """
    borrower = create_borrower(email="corner.b6@x.com", full_name="Corner B6",
                               annual_income_cents=5_000_000, fico_band="PRIME")
    application = create_application(borrower, requested_principal_cents=4_000_000,
                                     requested_term_months=60, requested_rate_type="FIXED")
    resp = api.create_cosigner(
        create_cosigner_payload(application_id=application["id"], cosigner_email="corner.c6@x.com",
                                cosigner_annual_income_cents=3_000_000),
        make_borrower_headers(borrower["id"]))
    data = validate_success(resp, 201)
    assert data["consent_status"] == "INVITED"
    assert data["on_time_streak"] == 0
