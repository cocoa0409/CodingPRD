"""Auth header presence, RBAC role gating, response envelope, and
masked-bidder identity rules (PRD §2.1, §2.2, §2.11)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_bidder_account_payload,
    create_lot_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_bidder_headers,
    setup_announced_lot,
    setup_lot_with_auction,
    setup_sold_auction,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Header presence — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_returns_auth_missing(self, api):
        """PRD §2.1: "Requests that omit either header, or supply them empty, are rejected with `ERR_AUTH_MISSING."

        Claim: omitting X-User-ID → ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/lots", headers={"X-User-Role": "CourtClerk"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header_returns_auth_missing(self, api):
        """PRD §2.1: "Requests that omit either header, or supply them empty, are rejected with `ERR_AUTH_MISSING."

        Claim: omitting X-User-Role → ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/lots", headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_header_returns_auth_missing(self, api):
        """PRD §2.1: "Requests that omit either header, or supply them empty, are rejected with `ERR_AUTH_MISSING."

        Claim: X-User-ID empty string → ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/lots",
            headers={"X-User-ID": "", "X-User-Role": "CourtClerk"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_role_header_returns_auth_missing(self, api):
        """PRD §2.1: "Requests that omit either header, or supply them empty, are rejected with `ERR_AUTH_MISSING."

        Claim: X-User-Role empty string → ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/lots",
            headers={"X-User-ID": "anyone", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# RBAC — PRD §2.1 + endpoint table
# ===========================================================================
class TestRbacForbidden:

    def test_bidder_cannot_register_lot(self, api, bidder_fallback_headers):
        """PRD §2.1: "Requests authenticated with a role not permitted for the requested operation are rejected with `ERR_AUTH_FORBIDDEN."

        PRD §4: POST /lots — Authorized Role(s): CourtClerk.
        Claim: Bidder → ERR_AUTH_FORBIDDEN on POST /lots.
        """
        resp = api.create_lot(create_lot_payload(), bidder_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_FORBIDDEN.value)

    def test_observer_cannot_register_lot(self, api, observer_headers):
        """PRD §2.1: "`Observer` is a strictly read-only role that sees the masked public surface — lot listings, the auction record, and the masked bid feed — but cannot transition any state."

        Claim: Observer → ERR_AUTH_FORBIDDEN on POST /lots.
        """
        resp = api.create_lot(create_lot_payload(), observer_headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_FORBIDDEN.value)

    def test_auction_admin_cannot_register_lot(self, api,
                                              auction_admin_headers):
        """PRD §4: POST /lots — Authorized Role(s): CourtClerk.

        Claim: AuctionAdmin → ERR_AUTH_FORBIDDEN on POST /lots.
        """
        resp = api.create_lot(create_lot_payload(), auction_admin_headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_FORBIDDEN.value)

    def test_court_clerk_cannot_register_bidder_account(
        self, api, court_clerk_headers,
    ):
        """PRD §4: POST /bidder-accounts — Authorized Role(s): AuctionAdmin.

        Claim: CourtClerk → ERR_AUTH_FORBIDDEN on POST /bidder-accounts.
        """
        resp = api.create_bidder_account(
            create_bidder_account_payload(), court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_FORBIDDEN.value)

    def test_observer_cannot_post_deposit(self, api, observer_headers):
        """PRD §2.1 + §4: POST /deposits — Authorized Role(s):
        Bidder, AuctionAdmin.

        Claim: Observer → ERR_AUTH_FORBIDDEN on POST /deposits.
        """
        resp = api.create_deposit(
            {"auction_id": NON_EXISTENT_UUID,
             "bidder_account_id": NON_EXISTENT_UUID},
            observer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_FORBIDDEN.value)


# ===========================================================================
# Response envelope shape — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_carries_required_meta_fields(
        self, api, court_clerk_headers,
    ):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_."

        Claim: a 2xx response carries meta.api_request_id starting with
        req_ and an ISO 8601 api_request_timestamp.
        """
        resp = api.list_lots(court_clerk_headers, params={"limit": 1})
        body = resp.json()
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id should start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Claim: error envelope carries non-empty error_id and message.
        """
        resp = api._request("GET", "/lots", headers={})
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip() != ""

    def test_paginated_response_carries_pagination_meta(
        self, api, court_clerk_headers,
    ):
        """PRD §2.3: "Paginated list responses always include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Claim: GET /lots meta contains all four pagination fields.
        """
        resp = api.list_lots(court_clerk_headers, params={"limit": 5})
        data, meta = validate_paginated(resp)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"pagination meta missing {key!r}"


# ===========================================================================
# Pagination defaults — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_default_limit_is_ten(self, api, court_clerk_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; if omitted it defaults to 10."

        Claim: omitting limit returns meta.limit == 10.
        """
        resp = api.list_lots(court_clerk_headers)
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"Default limit must be 10, got {meta['limit']}"
        )

    def test_default_offset_is_zero(self, api, court_clerk_headers):
        """PRD §2.3: "The `offset` parameter specifies the number of items to skip and defaults to 0."

        Claim: omitting offset returns meta.offset == 0.
        """
        resp = api.list_lots(court_clerk_headers)
        _, meta = validate_paginated(resp)
        assert meta["offset"] == 0


# ===========================================================================
# Masked-handle identity rules — PRD §2.11
# ===========================================================================
class TestBidIdentityMasking:

    def test_observer_view_omits_bidder_account_id(self, api, observer_headers):
        """PRD §2.11: "the underlying `bidder_account_id` is omitted from any payload returned to `AuctionAdmin`, `Bidder`, or `Observer."

        Claim: Observer's view of /auctions/{id}/bids carries
        masked_handle but never bidder_account_id.
        """
        _lot, auction, _bidders, _winning_bid = setup_sold_auction(
            num_bidders=2,
        )
        resp = api.list_auction_bids(auction["id"], observer_headers)
        data, _meta = validate_paginated(resp)
        for bid in data:
            assert "masked_handle" in bid and isinstance(
                bid["masked_handle"], str,
            ), "Observer view must include masked_handle"
            assert bid.get("bidder_account_id") in (None, ""), (
                "Observer view must omit bidder_account_id "
                f"(saw {bid.get('bidder_account_id')!r})"
            )

    def test_court_clerk_view_carries_unmasked_bidder_id(
        self, api, court_clerk_headers,
    ):
        """PRD §2.11: "Only `CourtClerk` reads the un-masked view."

        Claim: CourtClerk's view of /auctions/{id}/bids carries
        bidder_account_id as a valid UUID.
        """
        _lot, auction, _bidders, _winning_bid = setup_sold_auction(
            num_bidders=2,
        )
        resp = api.list_auction_bids(auction["id"], court_clerk_headers)
        data, _meta = validate_paginated(resp)
        for bid in data:
            assert is_valid_uuid(bid.get("bidder_account_id", "")), (
                "CourtClerk view must include un-masked bidder_account_id, "
                f"got {bid.get('bidder_account_id')!r}"
            )


# ===========================================================================
# Ownership enforcement for entity-backed Bidder (PRD §2.1)
# ===========================================================================
class TestBidderOwnership:

    def test_bidder_cannot_get_other_bidders_account(self, api):
        """PRD §2.1: "A `Bidder` may only post a deposit, pay it, raise or settle a dispute on it, place a bid, settle a payment, or read a bidder-account or payment record when the targeted resource belongs to their own account; cross-account access is rejected with `ERR_AUTH_FORBIDDEN`."

        Claim: Bidder A reading Bidder B's account → ERR_AUTH_FORBIDDEN.
        """
        from test_helpers import create_bidder_account
        bidder_a = create_bidder_account()
        bidder_b = create_bidder_account()
        resp = api.get_bidder_account(
            bidder_b["id"], make_bidder_headers(bidder_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_FORBIDDEN.value)
