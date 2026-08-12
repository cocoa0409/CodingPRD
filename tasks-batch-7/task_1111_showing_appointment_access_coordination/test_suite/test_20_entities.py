"""Entity corner cases: defaults, initial state, computed-field rejection, 404s, pagination, system-stamped fields."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_agent_payload,
    create_listing_payload,
    create_seller_payload,
    create_showing_request,
    is_valid_uuid,
    make_admin_headers,
    make_anonymous_headers,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    register_agent,
    setup_vacant_auto_world,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_seller_creation_defaults_applied(api):
    """PRD §3.1: "The `approval_timeout_minutes` field sets how long a showing
    request may await the occupant's decision before it becomes eligible to
    expire; it defaults to 240 minutes (four hours)" and "The `auto_approve`
    flag defaults to false."

    Design: Corner/entities/seller_creation_defaults_applied
    """
    resp = api_client.create_seller(
        create_seller_payload(full_name="D S", contact_email="ds@x.com"),
        make_admin_headers(),
    )
    seller = validate_success(resp, expected_status=201)
    assert seller["approval_timeout_minutes"] == 240, seller
    assert seller["auto_approve"] is False, seller
    assert seller["version"] == 1, seller
    assert is_valid_uuid(seller["id"]), seller

    fetched = validate_success(api_client.get_seller(seller["id"], make_admin_headers()))
    assert fetched["approval_timeout_minutes"] == 240
    assert fetched["auto_approve"] is False


def test_agent_registration_initial_state(api):
    """PRD §3.1: "A newly registered agent is born with `verification_status`
    of UNVERIFIED, `standing` of GOOD_STANDING, and `active_strike_points` of
    zero."

    Design: Corner/entities/agent_registration_initial_state
    """
    agent = register_agent(name="New Agent", license_number="LIC-NEW")
    assert agent["verification_status"] == "UNVERIFIED", agent
    assert agent["standing"] == "GOOD_STANDING", agent
    assert agent["active_strike_points"] == 0, agent
    assert agent["version"] == 1, agent

    fetched = validate_success(api_client.get_agent(agent["id"], make_admin_headers()))
    assert fetched["verification_status"] == "UNVERIFIED"
    assert fetched["standing"] == "GOOD_STANDING"
    assert fetched["active_strike_points"] == 0


def test_listing_create_rejected_with_computed_field_input(api):
    """PRD §2.7 stage 2: "Request shape: required fields are present, types are
    correct, enum values are valid, and unknown fields are rejected, else
    `ERR_INVALID_REQUEST`."

    confirmed_showing_count is a computed field and never client-settable;
    sending it in the create payload is an unknown field.

    Design: Corner/entities/listing_create_rejected_with_computed_field_input
    """
    seller = validate_success(api_client.create_seller(
        create_seller_payload(full_name="CF S", contact_email="cfs@x.com"),
        make_admin_headers()), expected_status=201)
    la = register_agent(name="CF LA", license_number="LIC-CF-LA")

    payload = create_listing_payload(seller["id"], occupancy_type="VACANT")
    payload["confirmed_showing_count"] = 99
    resp = api_client.create_listing(payload, make_listing_agent_headers(la["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_listing_get_not_found_returns_404(api):
    """PRD §2.6: "The server confirms each path identifier in sequence and
    rejects the request immediately with the 404 error corresponding to the
    first identifier that does not resolve: `ERR_SELLER_NOT_FOUND`,
    `ERR_AGENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, ..."

    Design: Corner/entities/listing_get_not_found_returns_404
    """
    la = register_agent(name="NF LA", license_number="LIC-NF-LA")
    resp = api_client.get_listing(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", make_listing_agent_headers(la["id"]))
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_FOUND)


def test_listings_pagination_and_seller_filter(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum
    of 100. The `offset` parameter sets how many items to skip and defaults to
    0. ... List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the response envelope." PRD §3.2:
    "Sellers and agents browsing their portfolios can filter the listing
    collection by `seller_id`, `listing_agent_id`, or `status`."

    Design: Corner/entities/listings_pagination_and_seller_filter
    """
    seller = validate_success(api_client.create_seller(
        create_seller_payload(full_name="PG S", contact_email="pg@x.com"),
        make_admin_headers()), expected_status=201)
    la = register_agent(name="PG LA", license_number="LIC-PG-LA")
    la_headers = make_listing_agent_headers(la["id"])
    for addr in ("1 Page St", "2 Page St", "3 Page St"):
        validate_success(api_client.create_listing(
            create_listing_payload(seller["id"], address=addr, occupancy_type="VACANT"),
            la_headers), expected_status=201)

    page1, meta1 = validate_paginated(api_client.list_listings(
        la_headers, params={"seller_id": seller["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2, (page1, meta1)
    assert meta1["total_count"] == 3 and meta1["has_more"] is True, meta1

    page2, meta2 = validate_paginated(api_client.list_listings(
        la_headers, params={"seller_id": seller["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1, (page2, meta2)
    assert meta2["total_count"] == 3 and meta2["has_more"] is False, meta2


def test_showing_request_buyer_agent_id_from_caller(api):
    """PRD §3.3: "The platform does not accept an agent identifier in the
    payload: `buyer_agent_id` is taken from the caller's `X-User-ID` at
    creation, binding the request to the acting agent."

    Design: Corner/entities/showing_request_buyer_agent_id_from_caller
    """
    world = setup_vacant_auto_world()
    ba_id = world["buyer_agent"]["id"]
    req = create_showing_request(world["listing"]["id"], ba_id,
                                 "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    assert req["buyer_agent_id"] == ba_id, req
