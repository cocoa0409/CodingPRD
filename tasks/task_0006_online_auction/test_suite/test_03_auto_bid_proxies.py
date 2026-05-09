"""Auto-bid proxies and multi-proxy conflict (PRD §3.3)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId,
    place_bid_payload, create_proxy_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers,
    create_seller, create_bidder, setup_live_lot, place_bid_on_lot,
    advance_clock, get_lot,
    validate_success, validate_error,
    assert_auto_bid_proxy,
)


ADMIN = TEST_USERS["platform_admin_headers"]


class TestProxyCreation:
    def test_create_proxy_emits_initial_bid(self, api):
        """PRD §3.3: "On creation, if the lot has no current winner, or if the bidder
        is not currently winning, the proxy emits an immediate `Bid` of exactly the
        current minimum-required-bid, with `source = PROXY` and `proxy_id` referencing
        the new proxy..."

        Claim: New proxy on no-bid lot emits an initial Bid at starting_bid_cents.
        """
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=200_000)
        bidder = create_bidder("ProxyOwner", wallet_amount_cents=1_000_000)
        resp = api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(80_000), make_bidder_headers(bidder["id"])
        )
        proxy = validate_success(resp, expected_status=201)
        assert_auto_bid_proxy(proxy)
        assert proxy["status"] == "ACTIVE"
        # The lot now has a current bid; current_price >= starting_bid_cents
        lot = get_lot(lot["id"])
        assert lot["current_price_cents"] == 50_000
        assert lot["bid_count"] >= 1

    def test_proxy_max_too_low(self, api):
        """PRD §3.3: "the supplied `max_amount_cents` to be at least the lot's
        `starting_bid_cents` and at least the current minimum-required-bid (otherwise
        `ERR_PROXY_MAX_TOO_LOW`, HTTP 422)."

        Claim: max_amount_cents < starting_bid_cents → ERR_PROXY_MAX_TOO_LOW at HTTP 422.
        """
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=100_000)
        bidder = create_bidder("Lowball", wallet_amount_cents=1_000_000)
        resp = api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(40_000), make_bidder_headers(bidder["id"])
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_PROXY_MAX_TOO_LOW"

    def test_only_one_active_proxy_per_bidder_per_lot(self, api):
        """PRD §3.3: "Only one `ACTIVE` proxy is permitted per `(bidder_id, lot_id)`;
        a second creation, even from a serialised race, is rejected with
        `ERR_PROXY_ALREADY_ACTIVE` (HTTP 409)."

        Claim: Second proxy create on same lot by same bidder → ERR_PROXY_ALREADY_ACTIVE.
        """
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=200_000)
        bidder = create_bidder("Dup", wallet_amount_cents=1_000_000)
        api.create_auto_bid_proxy(lot["id"], create_proxy_payload(80_000), make_bidder_headers(bidder["id"]))
        resp2 = api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(90_000), make_bidder_headers(bidder["id"])
        )
        assert resp2.status_code == 409
        body = resp2.json()
        assert body["data"]["error_id"] == "ERR_PROXY_ALREADY_ACTIVE"


class TestProxyMasking:
    def test_proxy_max_amount_visible_to_owner(self, api):
        """PRD §4 endpoint table: "GET /lots/{lotId}/auto-bid-proxies/{proxyId} ...
        (`max_amount_cents` is masked for non-owners)."
        PRD §3.3: "The proxy read endpoint returns the full record to the proxy's owner
        (and to operators) but masks `max_amount_cents` for any other reader."

        Claim: Owner reading own proxy sees max_amount_cents.
        """
        seller, lot = setup_live_lot()
        bidder = create_bidder("Owner", wallet_amount_cents=1_000_000)
        proxy = validate_success(api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(150_000), make_bidder_headers(bidder["id"])
        ), expected_status=201)
        # Owner read
        resp = api.get_auto_bid_proxy(lot["id"], proxy["id"], make_bidder_headers(bidder["id"]))
        data = validate_success(resp)
        assert data.get("max_amount_cents") == 150_000

    def test_proxy_max_amount_masked_for_non_owner(self, api):
        """PRD §3.3: "The proxy read endpoint returns the full record to the proxy's
        owner (and to operators) but masks `max_amount_cents` for any other reader."

        Claim: Non-owner Bidder reading proxy sees masked max_amount_cents (null/absent).
        """
        seller, lot = setup_live_lot()
        owner = create_bidder("Owner", wallet_amount_cents=1_000_000)
        outsider = create_bidder("Outsider", wallet_amount_cents=1_000_000)
        proxy = validate_success(api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(150_000), make_bidder_headers(owner["id"])
        ), expected_status=201)
        # Outsider read
        resp = api.get_auto_bid_proxy(lot["id"], proxy["id"], make_bidder_headers(outsider["id"]))
        data = validate_success(resp)
        # Masked → either absent or None
        assert data.get("max_amount_cents") in (None,) or "max_amount_cents" not in data


class TestProxyCancellation:
    def test_cancel_active_proxy(self, api):
        """PRD §3.3: "A `Bidder` may cancel their own still-`ACTIVE` proxy, moving it
        to `CANCELLED`."

        Claim: cancel of ACTIVE proxy → status=CANCELLED.
        """
        seller, lot = setup_live_lot()
        bidder = create_bidder("Owner", wallet_amount_cents=1_000_000)
        proxy = validate_success(api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(150_000), make_bidder_headers(bidder["id"])
        ), expected_status=201)
        resp = api.cancel_auto_bid_proxy(lot["id"], proxy["id"], make_bidder_headers(bidder["id"]))
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

    def test_cancel_already_cancelled_proxy(self, api):
        """PRD §3.3: "Cancellation outside `ACTIVE` produces `ERR_PROXY_INVALID_STATE`."

        Claim: Cancel on already-CANCELLED proxy → ERR_PROXY_INVALID_STATE.
        """
        seller, lot = setup_live_lot()
        bidder = create_bidder("Owner", wallet_amount_cents=1_000_000)
        proxy = validate_success(api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(150_000), make_bidder_headers(bidder["id"])
        ), expected_status=201)
        # First cancel
        api.cancel_auto_bid_proxy(lot["id"], proxy["id"], make_bidder_headers(bidder["id"]))
        # Second cancel
        resp = api.cancel_auto_bid_proxy(lot["id"], proxy["id"], make_bidder_headers(bidder["id"]))
        validate_error(resp, ApiErrorId.ERR_PROXY_INVALID_STATE.value)


class TestProxyResolutionEvaluationOrder:
    def test_two_proxies_walk_until_one_exhausts(self, api):
        """PRD §3.3: "When two proxies are bidding against each other, this iteration
        walks them upward through the ladder until one proxy's next required emission
        would exceed its `max_amount_cents`; that proxy is moved to `EXHAUSTED`
        (`ERR_PROXY_INVALID_STATE` blocks any later operation) and the other proxy
        continues to hold the winner slot."
        PRD §3.3: "On creation, if the lot has no current winner, or if the bidder is
        not currently winning, the proxy emits an immediate `Bid` of exactly the
        current minimum-required-bid..."
        PRD §3.3: "After any later bid, every `ACTIVE` proxy on the lot whose owner is
        not the new winner emits a counter-bid, again at the post-bid
        minimum-required-bid."

        Claim: Two proxies with maxes 30000 and 50000. After resolution: lower-max
        proxy is EXHAUSTED at 30000; higher-max proxy is ACTIVE at 31000;
        Lot.current_price_cents=31000.

        # difficulty: combinatorial_formula/proxy_resolution_evaluation_order
        """
        seller, lot = setup_live_lot(starting_bid_cents=10_000, reserve_price_cents=200_000)
        x = create_bidder("X", wallet_amount_cents=2_000_000)
        y = create_bidder("Y", wallet_amount_cents=2_000_000)

        proxy_x = validate_success(api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(30_000), make_bidder_headers(x["id"])
        ), expected_status=201)
        proxy_y = validate_success(api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(50_000), make_bidder_headers(y["id"])
        ), expected_status=201)

        lot = get_lot(lot["id"])
        # Y, with the higher max, should be the current winner at 31000
        assert lot["current_price_cents"] == 31_000, (
            f"Expected current_price_cents == 31000 (X exhausts at 30000, Y bids 31000); "
            f"got {lot['current_price_cents']}"
        )
        assert lot["current_winner_bidder_id"] == y["id"], (
            f"Expected Y to be current winner; got {lot['current_winner_bidder_id']}"
        )

        # Read both proxies as their owners
        proxy_x_final = validate_success(api.get_auto_bid_proxy(
            lot["id"], proxy_x["id"], make_bidder_headers(x["id"])
        ))
        proxy_y_final = validate_success(api.get_auto_bid_proxy(
            lot["id"], proxy_y["id"], make_bidder_headers(y["id"])
        ))
        assert proxy_x_final["status"] == "EXHAUSTED", (
            f"X with max 30000 should be EXHAUSTED; got {proxy_x_final['status']}"
        )
        assert proxy_x_final["last_executed_amount_cents"] == 30_000
        assert proxy_y_final["status"] == "ACTIVE"
        assert proxy_y_final["last_executed_amount_cents"] == 31_000


class TestProxyAffiliationGate:
    def test_proxy_blocked_by_shill_affiliation(self, api):
        """PRD §3.3: "Creation requires the bidder to be `ACTIVE` and unaffiliated with
        the lot's seller..."
        PRD §2.11: "A `Bidder` whose `affiliated_seller_id` matches a lot's `seller_id`
        may not place bids on that lot or create proxies for that lot; the request is
        rejected with `ERR_SHILL_AFFILIATION` (HTTP 403)."

        Claim: Affiliated bidder creating proxy → ERR_SHILL_AFFILIATION at HTTP 403.
        """
        seller, lot = setup_live_lot()
        bidder = create_bidder("Affil", wallet_amount_cents=1_000_000, affiliated_seller_id=seller["id"])
        resp = api.create_auto_bid_proxy(
            lot["id"], create_proxy_payload(100_000), make_bidder_headers(bidder["id"])
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_SHILL_AFFILIATION"
