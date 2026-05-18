"""Auth, RBAC, response envelope, and agent CRUD basics.

Cites PRD §2.1 (RBAC), §2.2 (Response envelope), §2.3 (Pagination),
§2.4 (Common resource properties), §3.1 (Agent onboarding).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    AGENT_SPLIT_DEFAULT,
    TEST_USERS,
    api_client,
    assert_agent,
    build_user_headers,
    create_agent_payload,
    create_buyer_payload,
    create_listing_payload,
    create_listing_agent,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    patch_agent_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# §2.1 — Authentication headers
# ---------------------------------------------------------------------------
class TestAuthHeaders:
    """PRD §2.1: 'Every request must carry two headers: X-User-Role
    identifies the caller's role, and X-User-ID identifies the calling
    principal.'"""

    def test_missing_both_headers_returns_auth_missing(self, api):
        """PRD §2.1: 'If either header is missing the request is
        rejected with ERR_AUTH_MISSING and HTTP 401.'

        Claim: empty headers dict → ERR_AUTH_MISSING.
        """
        res = api.create_agent(
            create_agent_payload(agent_role="LISTING_AGENT"), headers={},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_returns_auth_missing(self, api):
        """PRD §2.1: 'If either header is missing the request is
        rejected with ERR_AUTH_MISSING and HTTP 401.'

        Claim: X-User-Role present but X-User-ID absent → ERR_AUTH_MISSING.
        """
        res = api.create_agent(
            create_agent_payload(agent_role="LISTING_AGENT"),
            headers={"X-User-Role": "MlsAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header_returns_auth_missing(self, api):
        """PRD §2.1: 'If either header is missing the request is
        rejected with ERR_AUTH_MISSING and HTTP 401.'

        Claim: X-User-ID present but X-User-Role absent → ERR_AUTH_MISSING.
        """
        res = api.create_agent(
            create_agent_payload(agent_role="LISTING_AGENT"),
            headers={"X-User-ID": "anything"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_unrecognized_role_string_returns_auth_invalid(self, api):
        """PRD §2.1: 'If X-User-ID cannot be resolved to a valid
        principal for the supplied X-User-Role, or the role spelling
        itself is not one of the recognized values, the request is
        rejected with ERR_AUTH_INVALID and HTTP 401.'

        Claim: role string outside {ListingAgent, BuyerAgent, MlsAdmin}
        → ERR_AUTH_INVALID.
        """
        res = api.create_agent(
            create_agent_payload(agent_role="LISTING_AGENT"),
            headers=build_user_headers("anyone", "Wizard"),
        )
        validate_error(res, ApiErrorId.ERR_AUTH_INVALID.value)

    def test_listing_agent_unknown_id_returns_auth_invalid(self, api):
        """PRD §2.1: 'If X-User-ID cannot be resolved to a valid
        principal for the supplied X-User-Role, ... the request is
        rejected with ERR_AUTH_INVALID and HTTP 401.'

        Claim: ListingAgent X-User-ID that does not resolve to any
        Agent row → ERR_AUTH_INVALID.
        """
        res = api.list_listings(
            headers=build_user_headers(NON_EXISTENT_UUID, "ListingAgent"),
        )
        validate_error(res, ApiErrorId.ERR_AUTH_INVALID.value)


# ---------------------------------------------------------------------------
# §2.1 — RBAC role permissions
# ---------------------------------------------------------------------------
class TestRbacForbidden:
    """PRD §2.1: 'If the headers resolve but the role lacks permission
    to call the endpoint per the RBAC matrix, the request is rejected
    with ERR_FORBIDDEN and HTTP 403.'"""

    def test_listing_agent_cannot_register_agents(self, api):
        """PRD §4: POST /agents authorized role(s) = MlsAdmin only.
        Claim: A ListingAgent calling POST /agents → ERR_FORBIDDEN."""
        la = create_listing_agent()
        res = api.create_agent(
            create_agent_payload(agent_role="LISTING_AGENT"),
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_buyer_agent_cannot_create_listing(self, api):
        """PRD §4: POST /listings authorized role(s) = ListingAgent.
        Claim: BuyerAgent calling POST /listings → ERR_FORBIDDEN."""
        from test_helpers import create_buyer_agent
        ba = create_buyer_agent()
        res = api.create_listing(
            create_listing_payload(listing_agent_id=ba["id"]),
            make_buyer_agent_headers(ba["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_mls_admin_cannot_submit_offer(self, api, mls_admin_headers):
        """PRD §4: POST /listings/{listing_id}/offers authorized role =
        BuyerAgent only.

        Claim: MlsAdmin submitting an offer → ERR_FORBIDDEN.
        """
        from test_helpers import (
            create_buyer,
            create_buyer_agent,
            setup_listing_and_buyer,
            submit_offer_payload,
        )
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        res = api.submit_offer(
            listing["id"],
            submit_offer_payload(buyer_id=buyer["id"]),
            mls_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# §2.1 — Ownership (ERR_FORBIDDEN_NOT_OWNER)
# ---------------------------------------------------------------------------
class TestOwnership:
    """PRD §2.1: 'When a listing-side action is invoked by a
    ListingAgent whose id is not the listing's listing_agent_id, ... the
    request is rejected with ERR_FORBIDDEN_NOT_OWNER and HTTP 403.'"""

    def test_other_listing_agent_cannot_withdraw(self, api):
        """PRD §2.1: 'When a listing-side action is invoked by a
        ListingAgent whose id is not the listing's listing_agent_id,
        or a buyer-side action is invoked by a BuyerAgent whose id is
        not the buyer's buyer_agent_id, the request is rejected with
        ERR_FORBIDDEN_NOT_OWNER and HTTP 403.'

        Claim: A second listing agent attempting to withdraw another
        agent's listing → ERR_FORBIDDEN_NOT_OWNER.
        """
        from test_helpers import (
            create_listing,
            create_listing_agent,
            withdraw_listing_payload,
        )
        la1 = create_listing_agent()
        listing = create_listing(la1)
        la2 = create_listing_agent()
        # la2 attempts to withdraw la1's listing.
        res = api.withdraw_listing(
            listing["id"],
            withdraw_listing_payload(version=listing["version"]),
            make_listing_agent_headers(la2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)

    def test_other_buyer_agent_cannot_withdraw_offer(self, api):
        """PRD §2.1: 'a buyer-side action is invoked by a BuyerAgent
        whose id is not the buyer's buyer_agent_id, the request is
        rejected with ERR_FORBIDDEN_NOT_OWNER and HTTP 403.'

        Claim: A second buyer agent attempting to withdraw an offer made
        by another buyer's agent → ERR_FORBIDDEN_NOT_OWNER.
        """
        from test_helpers import (
            create_buyer_agent,
            setup_listing_and_buyer,
            submit_offer,
        )
        la, listing, lockbox, ba1, buyer = setup_listing_and_buyer()
        offer = submit_offer(listing, buyer, ba1)
        ba2 = create_buyer_agent()
        res = api.withdraw_offer(
            listing["id"], offer["id"],
            make_buyer_agent_headers(ba2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)


# ---------------------------------------------------------------------------
# §2.2 — Success / error envelope shape
# ---------------------------------------------------------------------------
class TestResponseEnvelope:
    """PRD §2.2: every successful response carries meta.api_request_id
    starting with 'req_' and meta.api_request_timestamp ISO 8601."""

    def test_success_envelope_fields_present(
        self, api, mls_admin_headers,
    ):
        """PRD §2.2: 'The api_request_id is a server-generated unique
        identifier for the request that starts with req_. The
        api_request_timestamp is a server-generated ISO 8601 UTC
        timestamp with three fractional digits.'

        Claim: A successful POST /agents response includes meta with
        api_request_id starting with 'req_' and ISO 8601
        api_request_timestamp; response_type is 'object'.
        """
        res = api.create_agent(
            create_agent_payload(agent_role="LISTING_AGENT"),
            mls_admin_headers,
        )
        body = res.json()
        assert res.status_code == 201
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert "data" in body

    def test_error_envelope_fields_present(self, api):
        """PRD §2.2: 'For error responses the meta object contains only
        api_request_id and api_request_timestamp ... The error_id is a
        unique, machine-readable string ... The message provides a
        human-readable explanation of what went wrong.'

        Claim: An error response has response_type='error' and a data
        object carrying error_id and message.
        """
        res = api.create_agent(create_agent_payload(), headers={})
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert isinstance(body["data"]["message"], str)


# ---------------------------------------------------------------------------
# §2.3 — Pagination defaults / bounds
# ---------------------------------------------------------------------------
class TestPagination:
    """PRD §2.3: limit defaults to 10, min 1, max 100; offset
    non-negative; has_more reflects further rows; default sort is
    created_at ASC then id ASC."""

    def test_listings_pagination_meta_present(
        self, api, mls_admin_headers,
    ):
        """PRD §2.3: 'The four pagination fields surfaced in the
        response meta object are limit, offset, total_count, and
        has_more, with has_more set to true whenever the next page
        would still contain at least one row.'

        Claim: GET /listings returns meta with limit/offset/total_count/
        has_more.
        """
        # Seed at least one listing.
        la = create_listing_agent()
        from test_helpers import create_listing
        create_listing(la)
        data, meta = validate_paginated(
            api.list_listings(mls_admin_headers),
        )
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        assert meta["total_count"] >= 1


# ---------------------------------------------------------------------------
# §3.1 — Agent CRUD
# ---------------------------------------------------------------------------
class TestAgentCrud:
    """PRD §3.1 agent onboarding."""

    def test_create_agent_default_split_is_070(
        self, api, mls_admin_headers,
    ):
        """PRD §3.1: 'An optional brokerage_split_pct may be supplied;
        if omitted, the agent's split defaults to 0.70.'

        Claim: Omitting brokerage_split_pct on POST /agents → stored
        value 0.70.
        """
        res = api.create_agent(
            create_agent_payload(agent_role="LISTING_AGENT"),
            mls_admin_headers,
        )
        agent = validate_success(res, 201)
        assert_agent(agent)
        assert float(agent["brokerage_split_pct"]) == pytest.approx(
            AGENT_SPLIT_DEFAULT, abs=1e-9,
        )
        assert agent["status"] == "ACTIVE"
        assert agent["version"] == 1

    def test_create_agent_explicit_split_round_trip(
        self, api, mls_admin_headers,
    ):
        """PRD §3.1: 'The split is stored to four decimal places, must
        be strictly greater than zero, and must not exceed 1.0.'

        Claim: explicit brokerage_split_pct round-trips to four
        decimals.
        """
        res = api.create_agent(
            create_agent_payload(
                agent_role="BUYER_AGENT", brokerage_split_pct=0.6500,
            ),
            mls_admin_headers,
        )
        agent = validate_success(res, 201)
        assert float(agent["brokerage_split_pct"]) == pytest.approx(
            0.6500, abs=1e-9,
        )

    def test_patch_agent_increments_version_by_one(
        self, api, mls_admin_headers,
    ):
        """PRD §2.6: 'Every successful mutation refreshes updated_at
        and increments version by 1 on the directly mutated row.'

        Claim: PATCH /agents/{id} increments version by exactly 1.
        """
        agent = create_listing_agent()
        v0 = agent["version"]
        res = api.patch_agent(
            agent["id"],
            patch_agent_payload(version=v0, brokerage_split_pct=0.65),
            mls_admin_headers,
        )
        updated = validate_success(res, 200)
        assert updated["version"] == v0 + 1
        assert float(updated["brokerage_split_pct"]) == pytest.approx(0.65)

    def test_patch_agent_stale_version_rejected(
        self, api, mls_admin_headers,
    ):
        """PRD §2.6: 'If the supplied version does not equal the stored
        version of the target row, the request is rejected with
        ERR_VERSION_CONFLICT and HTTP 409.'

        Claim: PATCH /agents/{id} with a stale version →
        ERR_VERSION_CONFLICT.
        """
        agent = create_listing_agent()
        # First PATCH bumps version to 2.
        api.patch_agent(
            agent["id"],
            patch_agent_payload(version=agent["version"], brokerage_split_pct=0.60),
            mls_admin_headers,
        )
        # Second PATCH still using version=1 should fail.
        res = api.patch_agent(
            agent["id"],
            patch_agent_payload(version=agent["version"], brokerage_split_pct=0.55),
            mls_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_get_nonexistent_agent(self, api, mls_admin_headers):
        """PRD §2.5: 'If any segment of the path does not resolve ...
        the response is ERR_NOT_FOUND with HTTP 404.'

        Claim: GET /agents/{id} with a UUID that does not exist →
        ERR_NOT_FOUND.
        """
        res = api.get_agent(NON_EXISTENT_UUID, mls_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
