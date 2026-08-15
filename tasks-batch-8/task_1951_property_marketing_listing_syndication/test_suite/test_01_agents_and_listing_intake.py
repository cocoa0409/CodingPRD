"""Agents and listing intake: creation defaults, required fields, FK resolution,
server-minted identity, license uniqueness, and the logical clock default."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    assert_agent, assert_listing,
    create_agent_payload, create_listing_payload,
    TEST_USERS, make_listing_agent_headers,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]
MD = TEST_USERS["marketing_director_headers"]


def test_create_listing_defaults_and_initial_state(api, marketing_director_headers):
    """PRD §2.6: "A freshly created listing starts in lifecycle `DRAFT` with posture
    `NOT_SYNDICATED`, both scores null, and both breach counters at zero."
    PRD §3.1: "A new listing begins with `lifecycle_status` `DRAFT`, posture
    `NOT_SYNDICATED`, and `relist_count` zero."

    Design: Corner/entities/create_listing_defaults_and_initial_state
    """
    agent = validate_success(
        api.create_agent(create_agent_payload(license_number="LIC-1"), marketing_director_headers), 201)
    payload = create_listing_payload(agent["id"], complete=False)
    res = api.create_listing(payload, make_listing_agent_headers(agent["id"]))
    listing = validate_success(res, 201)
    assert_listing(listing)
    assert listing["lifecycle_status"] == "DRAFT"
    assert listing["syndication_posture"] == "NOT_SYNDICATED"
    assert listing["relist_count"] == 0
    assert listing["feedback_score_raw"] is None
    assert listing["feedback_score_weighted"] is None
    assert listing["audited_breach_count"] == 0
    assert listing["provisional_breach_count"] == 0
    # Fields optional at intake (PRD §3.1) remain unset.
    for field in ("bedrooms", "bathrooms", "square_feet", "marketing_remarks", "mls_number"):
        assert listing.get(field) is None, f"{field} should be unset when omitted at intake"


def test_create_listing_missing_required_field_returns_invalid_request(api, marketing_director_headers):
    """PRD §2.9: "Field validity — required fields present, types correct, enum
    membership, and ranges, else `ERR_INVALID_REQUEST`."
    PRD §3.1: "The intake payload carries the property's address — `address_line1`,
    `city`, the two-letter `state_code`, and `postal_code` — together with the
    `property_type`, which must be one of `SINGLE_FAMILY`, `CONDO`, `TOWNHOUSE`,
    `MULTI_FAMILY`, or `LAND`, the asking price `list_price_cents`, and the listing
    agreement's expiry instant `listing_expires_on`."

    Design: Corner/entities/create_listing_missing_required_field_returns_invalid_request
    """
    agent = validate_success(
        api.create_agent(create_agent_payload(license_number="LIC-1"), marketing_director_headers), 201)
    payload = create_listing_payload(agent["id"], complete=False)
    del payload["list_price_cents"]
    res = api.create_listing(payload, make_listing_agent_headers(agent["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_get_listing_not_found_returns_404(api, marketing_coordinator_headers):
    """PRD §2.9: "Existence — every identifier resolves, else `ERR_NOT_FOUND`."

    Design: Corner/entities/get_listing_not_found_returns_404
    """
    res = api.get_listing(NON_EXISTENT_UUID, marketing_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_system_fields_client_input_ignored_on_create(api, marketing_director_headers):
    """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as a
    UUID, with no type prefix."
    PRD §2.5: "`version` (integer): a system-managed counter that increments by one
    on every mutation of the resource."

    Design: Corner/entities/system_fields_client_input_ignored_on_create
    """
    payload = create_agent_payload(license_number="LIC-9")
    payload["id"] = "client-supplied"
    payload["version"] = 99
    agent = validate_success(api.create_agent(payload, marketing_director_headers), 201)
    assert_agent(agent)
    assert is_valid_uuid(agent["id"]), "server must mint its own UUID id"
    assert agent["id"] != "client-supplied"
    assert isinstance(agent["version"], int) and agent["version"] != 99, (
        "client-supplied version must be ignored in favor of the system-managed counter"
    )


def test_agent_license_uniqueness_enforced(api, marketing_director_headers):
    """PRD §3.1: "The `license_number` must be unique across all agents; a duplicate
    is rejected with `ERR_DUPLICATE_LICENSE`."

    Design: Corner/entities/agent_license_uniqueness_enforced
    """
    first = create_agent_payload(full_name="Ann Agent", license_number="LIC-1", email="a@x.com")
    validate_success(api.create_agent(first, marketing_director_headers), 201)
    second = create_agent_payload(full_name="Bob Broker", license_number="LIC-1", email="b@x.com")
    res = api.create_agent(second, marketing_director_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_LICENSE, expected_status=409)


def test_create_listing_with_unknown_agent_returns_not_found(api):
    """PRD §2.9: "The same rule applies to foreign-key references in a request body,
    such as `agent_id` or `portal_account_id`."
    PRD §2.9: "Existence — every identifier resolves, else `ERR_NOT_FOUND`."

    Design: Corner/entities/create_listing_with_unknown_agent_returns_not_found
    """
    payload = create_listing_payload(NON_EXISTENT_UUID, complete=False)
    res = api.create_listing(payload, make_listing_agent_headers(NON_EXISTENT_UUID))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_server_clock_defaults_to_fixed_epoch(api, marketing_director_headers):
    """PRD §2.4: "On server startup the logical clock is exactly
    `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time on its own."
    PRD §2.4: "Timestamps such as `created_at`, `decided_at`, `dispatched_at`, and
    `terminal_entered_at` are always stamped from this clock."

    Design: Corner/entities/server_clock_defaults_to_fixed_epoch
    """
    agent = validate_success(
        api.create_agent(create_agent_payload(license_number="LIC-1"), marketing_director_headers), 201)
    assert is_iso8601_timestamp(agent["created_at"])
    assert agent["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at must be stamped from the logical clock default, got {agent['created_at']!r}"
    )
