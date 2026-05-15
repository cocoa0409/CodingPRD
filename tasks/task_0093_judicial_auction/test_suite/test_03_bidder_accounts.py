"""Bidder account lifecycle: real-name authentication, uniqueness,
SUSPENDED→ACTIVE clear path (PRD §3.2, §3.6)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_bidder_account,
    clear_bidder_account_payload,
    create_bidder_account,
    create_bidder_account_payload,
    make_bidder_headers,
    validate_error,
    validate_success,
)


class TestBidderAccountRegistration:

    def test_register_bidder_returns_active_account(self, api,
                                                  auction_admin_headers):
        """PRD §3.2: "The account is created with `status` `ACTIVE` and an initial `collusion_risk_score` of zero."

        Claim: POST /bidder-accounts → 201, status=ACTIVE,
        collusion_risk_score=0.
        """
        resp = api.create_bidder_account(
            create_bidder_account_payload(), auction_admin_headers,
        )
        account = validate_success(resp, expected_status=201)
        assert_bidder_account(account)
        assert account["status"] == "ACTIVE"
        assert account["collusion_risk_score"] == 0

    def test_duplicate_id_document_no_among_active_accounts_rejected(
        self, api, auction_admin_headers,
    ):
        """PRD §3.2: "the platform enforces uniqueness on `id_document_no` for all rows whose `status` is `ACTIVE`, returning `ERR_DUPLICATE` on collision."

        Claim: second POST /bidder-accounts with the same
        id_document_no → ERR_DUPLICATE.
        """
        payload = create_bidder_account_payload(id_document_no="ID-DUP-001")
        first = api.create_bidder_account(payload, auction_admin_headers)
        validate_success(first, expected_status=201)
        second = api.create_bidder_account(payload, auction_admin_headers)
        validate_error(second, ApiErrorId.ERR_DUPLICATE.value)


class TestBidderAccountClear:

    def test_clear_unknown_account_returns_not_found(
        self, api, court_clerk_headers,
    ):
        """PRD §2.8: existence checks return ERR_NOT_FOUND when the path
        identifier does not resolve.

        Claim: POST /bidder-accounts/{unknown}/clear → ERR_NOT_FOUND.
        """
        resp = api.clear_bidder_account(
            NON_EXISTENT_UUID, clear_bidder_account_payload(),
            court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_clear_active_account_returns_invalid_state(
        self, api, court_clerk_headers,
    ):
        """PRD §3.2: "A `SUSPENDED` account can be returned to `ACTIVE` only by a `CourtClerk`, by submitting `investigation_resolved` set to true; once `BLOCKED`, the account is terminal."

        Claim: calling clear on an already-ACTIVE account is not a
        valid transition → ERR_INVALID_STATE.
        """
        account = create_bidder_account()
        resp = api.clear_bidder_account(
            account["id"], clear_bidder_account_payload(),
            court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestBidderAccountReadOwnership:

    def test_owner_can_read_own_account(self, api):
        """PRD §2.1: "A `Bidder` may only post a deposit, pay it, raise or settle a dispute on it, place a bid, settle a payment, or read a bidder-account or payment record when the targeted resource belongs to their own account; cross-account access is rejected with `ERR_AUTH_FORBIDDEN`."

        Claim: Bidder reading their own account succeeds (HTTP 200).
        """
        account = create_bidder_account()
        resp = api.get_bidder_account(
            account["id"], make_bidder_headers(account["id"]),
        )
        data = validate_success(resp)
        assert data["id"] == account["id"]

    def test_auction_admin_can_read_any_account(
        self, api, auction_admin_headers,
    ):
        """PRD §4: GET /bidder-accounts/{account_id} — Authorized
        Role(s): AuctionAdmin, CourtClerk, Bidder.

        Claim: AuctionAdmin can read any bidder account.
        """
        account = create_bidder_account()
        resp = api.get_bidder_account(account["id"], auction_admin_headers)
        data = validate_success(resp)
        assert data["id"] == account["id"]
