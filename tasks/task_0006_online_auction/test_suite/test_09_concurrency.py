"""Concurrency / race scenarios (PRD §2.10)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId,
    place_bid_payload, create_proxy_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers,
    create_seller, create_bidder, setup_live_lot, place_bid_on_lot,
    advance_clock, get_lot, unique_serial, iso_relative,
    validate_success, validate_error,
    run_race, assert_exactly_one_succeeds,
)


ADMIN = TEST_USERS["platform_admin_headers"]


class TestProxyAlreadyActiveRace:
    def test_two_simultaneous_proxy_creates_one_wins(self, api):
        """PRD §2.10: "Two simultaneous auto-bid-proxy creations from the same bidder on
        the same lot serialise with first-writer-wins on the `(bidder_id, lot_id)`
        uniqueness key; the loser is rejected with `ERR_PROXY_ALREADY_ACTIVE` (HTTP 409)."

        Claim: Two concurrent proxy creates by same bidder → exactly one succeeds; loser
        gets ERR_PROXY_ALREADY_ACTIVE.
        """
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=200_000)
        bidder = create_bidder("Racer", wallet_amount_cents=2_000_000)
        headers = make_bidder_headers(bidder["id"])

        results = run_race(
            lambda: api.create_auto_bid_proxy(lot["id"], create_proxy_payload(80_000), headers),
            lambda: api.create_auto_bid_proxy(lot["id"], create_proxy_payload(90_000), headers),
        )
        outcome = assert_exactly_one_succeeds(*results)
        # Loser must have ERR_PROXY_ALREADY_ACTIVE
        assert len(outcome["failures"]) == 1
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == "ERR_PROXY_ALREADY_ACTIVE"


class TestPaymentConfirmedRace:
    def test_two_simultaneous_payment_events_one_wins(self, api):
        """PRD §2.10: "Two simultaneous payment-confirmed events for the same invoice
        serialise on the `ISSUED → PAID` transition; exactly one wins, and the loser is
        rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409) because the invoice has, by
        then, already left `ISSUED`."

        Claim: Concurrent payment-confirmed events → exactly one succeeds; loser gets
        ERR_INVOICE_NOT_ISSUED.
        """
        from test_helpers import setup_sold_lot, event_payment_confirmed_payload
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000
        )
        results = run_race(
            lambda: api.event_payment_confirmed(
                event_payment_confirmed_payload(invoice["id"], iso_relative(0)), ADMIN,
            ),
            lambda: api.event_payment_confirmed(
                event_payment_confirmed_payload(invoice["id"], iso_relative(1)), ADMIN,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == "ERR_INVOICE_NOT_ISSUED"


class TestPhysicalItemTimeOverlapRace:
    def test_two_publishes_for_overlapping_window_one_wins(self, api):
        """PRD §2.10: "Two simultaneous publishes for distinct lots that share a
        `physical_item_serial` and have overlapping `[scheduled_start_at,
        effective_end_at)` intervals serialise first-writer-wins; the loser is rejected
        with `ERR_PHYSICAL_ITEM_TIME_OVERLAP` (HTTP 409)."

        Claim: Two concurrent publishes with overlapping windows on same serial →
        exactly one succeeds; loser gets ERR_PHYSICAL_ITEM_TIME_OVERLAP.
        """
        from test_helpers import create_lot_for_seller
        seller = create_seller()
        serial = unique_serial()
        # Two lots in DRAFT with same serial and overlapping windows.
        # Anchor relative to current clock to keep starts in the future.
        T = 86400
        H = 3600
        lot_a = create_lot_for_seller(
            seller, physical_item_serial=serial,
            scheduled_start_at=iso_relative(T),
            scheduled_end_at=iso_relative(T + 3 * H),
        )
        lot_b = create_lot_for_seller(
            seller, physical_item_serial=serial,
            scheduled_start_at=iso_relative(T + H),
            scheduled_end_at=iso_relative(T + 4 * H),
        )
        headers = make_seller_headers(seller["id"])
        results = run_race(
            lambda: api.publish_lot(lot_a["id"], headers),
            lambda: api.publish_lot(lot_b["id"], headers),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == "ERR_PHYSICAL_ITEM_TIME_OVERLAP"
