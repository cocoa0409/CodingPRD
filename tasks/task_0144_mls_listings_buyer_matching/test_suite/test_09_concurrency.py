"""Concurrency: two listing agents accepting siblings, listing OCC,
showing overlap races.

Cites PRD §2.6 (OCC) and §2.10 (Concurrency Outcomes).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exactly_one_succeeds,
    create_buyer,
    create_buyer_agent,
    iso_in_future,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    patch_listing_payload,
    request_showing_payload,
    run_race,
    setup_listing_and_buyer,
    submit_offer,
    submit_offer_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestListingOcc:
    """PRD §2.6 + PRD §2.10.4."""

    def test_two_patches_with_same_version_exactly_one_wins(self, api):
        """PRD §2.10: 'Two PATCH /listings/{id} requests with the same
        stored version: only the request whose version matches the row
        at the moment of write succeeds; the loser sees
        ERR_VERSION_CONFLICT.'

        Claim: Concurrent PATCH with the same stored version → one
        succeeds, one returns ERR_VERSION_CONFLICT.
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        v = listing["version"]
        la_headers = make_listing_agent_headers(la["id"])

        def patch_a():
            return api_client.patch_listing(
                listing["id"],
                patch_listing_payload(version=v, list_price_cents=51_000_000),
                la_headers,
            )

        def patch_b():
            return api_client.patch_listing(
                listing["id"],
                patch_listing_payload(version=v, list_price_cents=52_000_000),
                la_headers,
            )

        results = run_race(patch_a, patch_b)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Confirm the loser's error_id is exactly ERR_VERSION_CONFLICT.
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestConcurrentAccept:
    """PRD §2.10.1."""

    def test_concurrent_accept_of_siblings_yields_listing_already_under_contract(
        self, api,
    ):
        """PRD §2.10: 'Two ListingAgent callers attempting to accept
        different offers on the same listing at the same instant: at
        most one offer reaches ACCEPTED; the loser, finding the
        listing now UNDER_CONTRACT, is rejected with
        ERR_LISTING_ALREADY_UNDER_CONTRACT.'

        Claim: Two simultaneous accepts on sibling SUBMITTED offers →
        exactly one succeeds; the loser sees
        ERR_LISTING_ALREADY_UNDER_CONTRACT.
        """
        la, listing, lockbox, ba1, buyer1 = setup_listing_and_buyer()
        offer_a = submit_offer(listing, buyer1, ba1)
        ba2 = create_buyer_agent()
        buyer2 = create_buyer(
            ba2,
            max_price_cents=60_000_000,
            min_price_cents=40_000_000,
            desired_zips=["94110"],
        )
        offer_b = submit_offer(listing, buyer2, ba2)
        la_headers = make_listing_agent_headers(la["id"])

        def accept_a():
            return api_client.accept_offer(
                listing["id"], offer_a["id"], la_headers,
            )

        def accept_b():
            return api_client.accept_offer(
                listing["id"], offer_b["id"], la_headers,
            )

        results = run_race(accept_a, accept_b)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser's error_id MUST be ERR_LISTING_ALREADY_UNDER_CONTRACT
        # per PRD §2.10.
        loser = outcome["failures"][0]
        validate_error(
            loser, ApiErrorId.ERR_LISTING_ALREADY_UNDER_CONTRACT.value,
        )


class TestConcurrentAcceptVsWithdraw:
    """PRD §2.10.2."""

    def test_accept_vs_withdraw_loser_sees_offer_not_submitted(self, api):
        """PRD §2.10: 'A ListingAgent accepting an offer while the
        BuyerAgent simultaneously withdraws that same offer: exactly
        one operation succeeds. If the withdraw lands first, the
        accept finds the offer no longer in SUBMITTED status and is
        rejected with ERR_OFFER_NOT_SUBMITTED; if the accept lands
        first, the withdraw likewise finds the offer no longer in
        SUBMITTED status and is rejected with the same
        ERR_OFFER_NOT_SUBMITTED.'

        Claim: race(accept, withdraw) → exactly one succeeds; the
        loser sees ERR_OFFER_NOT_SUBMITTED.
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        offer = submit_offer(listing, buyer, ba)
        la_headers = make_listing_agent_headers(la["id"])
        ba_headers = make_buyer_agent_headers(ba["id"])

        def do_accept():
            return api_client.accept_offer(
                listing["id"], offer["id"], la_headers,
            )

        def do_withdraw():
            return api_client.withdraw_offer(
                listing["id"], offer["id"], ba_headers,
            )

        results = run_race(do_accept, do_withdraw)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_OFFER_NOT_SUBMITTED.value)


class TestConcurrentShowingOverlap:
    """PRD §2.10.3."""

    def test_concurrent_overlapping_showing_approval_one_wins(self, api):
        """PRD §2.10: 'Two BuyerAgent callers approving overlapping
        showings on the same listing simultaneously: at most one
        SCHEDULED showing can occupy any half-open interval; the
        second to commit sees the overlap and is rejected with
        ERR_SHOWING_TIME_OVERLAP.'

        Claim: Two requested showings with overlapping windows
        approved concurrently → exactly one is SCHEDULED, the loser
        sees ERR_SHOWING_TIME_OVERLAP.
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        # Two buyer agents request overlapping showings.
        ba2 = create_buyer_agent()
        buyer2 = create_buyer(
            ba2, max_price_cents=60_000_000, min_price_cents=40_000_000,
            desired_zips=["94110"],
        )
        # Same time window for both.
        start = iso_in_future(3600)
        from datetime import datetime, timedelta
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(minutes=60)
        from test_helpers import iso_at
        end = iso_at(end_dt)
        # Request both showings.
        s1_resp = api.request_showing(
            listing["id"],
            request_showing_payload(
                buyer_agent_id=ba["id"], buyer_id=buyer["id"],
                start_at=start, end_at=end,
            ),
            make_buyer_agent_headers(ba["id"]),
        )
        s1 = validate_success(s1_resp, 201)
        s2_resp = api.request_showing(
            listing["id"],
            request_showing_payload(
                buyer_agent_id=ba2["id"], buyer_id=buyer2["id"],
                start_at=start, end_at=end,
            ),
            make_buyer_agent_headers(ba2["id"]),
        )
        s2 = validate_success(s2_resp, 201)
        # Race the approvals.
        la_headers = make_listing_agent_headers(la["id"])

        def approve_s1():
            return api_client.approve_showing(
                listing["id"], s1["id"], la_headers,
            )

        def approve_s2():
            return api_client.approve_showing(
                listing["id"], s2["id"], la_headers,
            )

        results = run_race(approve_s1, approve_s2)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_SHOWING_TIME_OVERLAP.value)
