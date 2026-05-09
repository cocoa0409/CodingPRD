"""Validation priority chain (PRD §2.6)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    place_bid_payload, create_lot_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers,
    create_seller, create_bidder,
    setup_live_lot, place_bid_on_lot, advance_clock, get_lot,
    validate_success, validate_error,
)


ADMIN = TEST_USERS["platform_admin_headers"]


class TestStatePriorityOverBusinessConstraint:
    def test_state_error_wins_over_increment_check(self, api):
        """PRD §2.6: "When a single request triggers multiple checks, they are evaluated
        in a fixed order... (4) the state check producing `ERR_LOT_INVALID_STATE`,
        `ERR_LOT_NOT_LIVE`...; (8) the bid-increment check `ERR_BID_BELOW_MIN_INCREMENT`..."

        Claim: A bid below the increment floor on a CANCELLED lot returns
        ERR_LOT_NOT_LIVE (priority 4), not ERR_BID_BELOW_MIN_INCREMENT (priority 8).

        # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_on_bid
        """
        seller = create_seller()
        # Build a lot, publish to SCHEDULED, then cancel
        from test_helpers import create_lot_for_seller, publish_lot, cancel_lot
        lot = create_lot_for_seller(seller, starting_bid_cents=10_000, reserve_price_cents=10_000)
        lot = publish_lot(lot, seller)
        lot = cancel_lot(lot, seller)
        assert lot["status"] == "CANCELLED"

        bidder = create_bidder("B", wallet_amount_cents=2_000_000)
        # Trivially-low bid that ALSO violates increment
        resp = api.place_bid(lot["id"], place_bid_payload(1), make_bidder_headers(bidder["id"]))
        assert resp.status_code == 409, f"Expected 409 (ERR_LOT_NOT_LIVE), got {resp.status_code}"
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_LOT_NOT_LIVE", (
            f"Priority 4 (state) must win over priority 8 (business_constraint); got {body['data']['error_id']}"
        )


class TestSafetyPriorityOverFiscal:
    def test_bidder_restricted_wins_over_insufficient_funds(self, api):
        """PRD §2.6: "(5) the bidder-status safety check `ERR_BIDDER_RESTRICTED`...
        (13) the deposit-funding check `ERR_INSUFFICIENT_DEPOSIT_FUNDS`..."

        Claim: A RESTRICTED bidder with empty wallet bidding on a LIVE lot returns
        ERR_BIDDER_RESTRICTED (priority 5), not ERR_INSUFFICIENT_DEPOSIT_FUNDS
        (priority 13).

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_bid
        """
        seller, lot = setup_live_lot(reserve_price_cents=100_000, starting_bid_cents=50_000)
        bidder = create_bidder("Restricted", wallet_amount_cents=0)
        api.restrict_bidder(bidder["id"], ADMIN)
        resp = api.place_bid(lot["id"], place_bid_payload(999_999), make_bidder_headers(bidder["id"]))
        assert resp.status_code == 403
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_BIDDER_RESTRICTED"


class TestPriorityChainOrder:
    def test_role_forbidden_wins_over_existence(self, api):
        """PRD §2.6: "...(2) the role-permission check `ERR_ROLE_FORBIDDEN`; (3) the
        path-existence cascade producing one of the not-found errors..."

        Claim: A Bidder POSTing /lots with a non-existent seller_id sees
        ERR_ROLE_FORBIDDEN (priority 2 — Bidder cannot POST /lots) before any
        not-found check on the body.
        """
        bidder = create_bidder("B")
        resp = api.create_lot(
            create_lot_payload(seller_id=NON_EXISTENT_UUID),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)

    def test_existence_wins_over_state(self, api):
        """PRD §2.6: "...(3) the path-existence cascade producing one of the not-found
        errors; (4) the state check..."

        Claim: GET /lots/{nonexistent}/invoice → ERR_LOT_NOT_FOUND (priority 3) before
        any state check.
        """
        resp = api.get_invoice(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_FOUND.value)


class TestShillAffiliation:
    def test_affiliated_bidder_blocked_from_bid(self, api):
        """PRD §2.11: "A `Bidder` whose `affiliated_seller_id` matches a lot's
        `seller_id` may not place bids on that lot or create proxies for that lot;
        the request is rejected with `ERR_SHILL_AFFILIATION` (HTTP 403)."

        Claim: Affiliated bidder placing bid → ERR_SHILL_AFFILIATION.
        """
        seller, lot = setup_live_lot()
        bidder = create_bidder("Affiliated", wallet_amount_cents=2_000_000, affiliated_seller_id=seller["id"])
        resp = api.place_bid(
            lot["id"], place_bid_payload(50_000), make_bidder_headers(bidder["id"])
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_SHILL_AFFILIATION"
