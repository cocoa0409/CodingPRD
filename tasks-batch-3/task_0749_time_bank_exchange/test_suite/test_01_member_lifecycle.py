"""Member creation, retrieval, listing, defaults, computed and system fields."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    NON_EXISTENT_UUID,
    TEST_USERS, make_member_headers,
    member_payload,
    ApiErrorId,
)


def test_create_member_returns_seeded_defaults(api):
    """PRD §3.1: "The server creates the Member row with trust_tier at UNVERIFIED;
    chronological_balance_minutes, forward_looking_balance_minutes,
    lifetime_earned_minutes, lifetime_redeemed_minutes, verified_credential_count,
    completed_exchange_count, and no_show_strikes all at zero; is_suspended at
    false; and version at 1."

    Design: Corner/entities/creation_member_returns_all_fields
    """
    resp = api.create_member(
        member_payload(),
        headers=TEST_USERS["anonymous_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1
    assert data["trust_tier"] == "UNVERIFIED"
    assert data["chronological_balance_minutes"] == 0
    assert data["forward_looking_balance_minutes"] == 0
    assert data["lifetime_earned_minutes"] == 0
    assert data["lifetime_redeemed_minutes"] == 0
    assert data["verified_credential_count"] == 0
    assert data["completed_exchange_count"] == 0
    assert data["no_show_strikes"] == 0
    assert data["is_suspended"] is False


def test_get_member_returns_persisted_email_and_neighborhood(api):
    """PRD §3.1: "A new member joins the platform anonymously by supplying an
    email, a display_name, and a home_neighborhood code such as NW-01."

    Design: Corner/entities/retrieval_member_by_id
    """
    payload = member_payload(home_neighborhood="NW-02")
    persisted_email = payload["email"]
    create = get_success_data(api.create_member(payload, headers=TEST_USERS["anonymous_headers"]))

    resp = api.get_member(create["id"], headers=make_member_headers(create["id"]))
    data = validate_success(resp)
    assert data["email"] == persisted_email
    assert data["home_neighborhood"] == "NW-02"


def test_list_members_returns_paginated_envelope_with_default_limit_10(api):
    """PRD §2.3: "The default limit is 10, the minimum accepted value is 1,
    and the maximum is 100; the default offset is 0."
    PRD §2.3: "The pagination echo in the response meta block carries limit,
    offset, total_count, and has_more; total_count is the size of the filtered
    result set before the window is applied, and has_more is true whenever
    offset + limit is smaller than total_count."

    Design: Corner/entities/listing_members_pagination_defaults
    """
    for _ in range(12):
        get_success_data(api.create_member(member_payload(), headers=TEST_USERS["anonymous_headers"]))

    resp = api.list_members(headers=TEST_USERS["admin_headers"])
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 12
    assert len(data) == 10
    assert meta["has_more"] is True


def test_get_member_missing_returns_resource_not_found(api):
    """PRD §2.11: "then left-to-right existence of every path-referenced resource
    (a missing resource is rejected with ERR_RESOURCE_NOT_FOUND)"

    Design: Corner/entities/not_found_member_by_bogus_id
    """
    resp = api.get_member(NON_EXISTENT_UUID, headers=TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_create_member_missing_email_returns_invalid_request(api):
    """PRD §2.11: "Schema-shape validation — required fields present, enum values
    in the allowed set, minute inputs as integer multiples of 15 in the closed
    interval from 15 to 480, latest_start_utc strictly greater than
    earliest_start_utc, window_end_utc strictly greater than window_start_utc,
    ISO 8601 UTC datetimes — runs as the last band of checks and produces
    ERR_INVALID_REQUEST."

    Design: Corner/entities/required_field_missing_email_on_member_create
    """
    resp = api.create_member(
        {"display_name": "N", "home_neighborhood": "NW-01"},
        headers=TEST_USERS["anonymous_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_verified_credential_count_defaults_to_zero_on_create(api):
    """PRD §2.7: "Member.trust_tier is a computed enumeration derived from two
    counters: verified_credential_count, the count of VerificationCredential
    rows whose subject is the member and whose status is VERIFIED"

    Design: Corner/entities/computed_field_verified_credential_count_ignores_input
    """
    resp = api.create_member(
        member_payload(),
        headers=TEST_USERS["anonymous_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["verified_credential_count"] == 0, \
        "verified_credential_count is server-computed; must start at 0"


def test_created_at_and_version_are_system_generated_on_create(api):
    """PRD §2.4: "Every resource that participates in mutation flows carries
    created_at and updated_at timestamps in ISO 8601 UTC with three fractional
    digits, plus an integer version that starts at 1 on creation and is
    incremented on every mutation that alters the resource."

    Design: Corner/entities/system_field_created_at_and_version_generated
    """
    resp = api.create_member(
        member_payload(),
        headers=TEST_USERS["anonymous_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
