"""Auction close, settlement, buyer premium, and seller commission (PRD §3.4)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    place_bid_payload, event_identity_verified_payload, event_payment_confirmed_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers,
    create_seller, create_bidder, create_lot_for_seller,
    create_and_publish_lot, advance_clock, get_lot, iso_future, iso_relative,
    setup_live_lot, setup_live_lot_with_bid, setup_sold_lot, setup_paid_lot,
    place_bid_on_lot, close_lot_to_sold,
    validate_success, validate_error,
    assert_invoice, assert_invoice_money_invariants, assert_lot,
    buyer_premium_cents, seller_commission_cents,
    BP_TIER_1_UPPER_INCLUSIVE_CENTS, BP_TIER_2_UPPER_INCLUSIVE_CENTS,
    BP_TIER_1_RATE, BP_TIER_2_RATE, BP_TIER_3_RATE,
    JEWELRY_SURCHARGE_RATE, VERIFIED_DISCOUNT_RATE, MIN_PREMIUM_CENTS,
    SC_TIER_1_UPPER_INCLUSIVE_CENTS, SC_TIER_2_UPPER_INCLUSIVE_CENTS,
    SC_TIER_1_RATE, SC_TIER_2_RATE, SC_TIER_3_RATE,
)


ADMIN = TEST_USERS["platform_admin_headers"]


class TestLotClose:
    def test_lot_close_to_sold_when_reserve_met(self, api):
        """PRD §3.4: "If `has_met_reserve` is true, the lot transitions to `SOLD`:
        `hammer_price_cents` is set to `current_price_cents`, `winning_bidder_id` to
        `current_winner_bidder_id`, `hammer_at` to the current logical clock value..."

        Claim: After clock past effective_end_at with reserve met → SOLD with hammer set.
        """
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000
        )
        assert lot["status"] == "SOLD"
        assert lot["hammer_price_cents"] == 100_000
        assert lot["winning_bidder_id"] == bidder["id"]

    def test_lot_close_to_unsold_when_reserve_not_met(self, api):
        """PRD §3.4: "If `has_met_reserve` is false, the lot transitions to `UNSOLD`;
        every `HELD` deposit on the lot — including the would-be winner's — is
        `RELEASED` with `terminal_reason = LOSING_BIDDER`."

        Claim: With current_price < reserve at end, lot → UNSOLD.

        # difficulty: non_linear_state_machine/lot_branching_with_revert_shape
        """
        # Reserve 200_000 but bid only 100_000 → won't meet reserve
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=200_000)
        bidder = create_bidder("LoneBidder", wallet_amount_cents=2_000_000)
        place_bid_on_lot(bidder, lot, 100_000)
        lot = close_lot_to_sold(lot["id"])
        assert lot["status"] == "UNSOLD"

    def test_unsold_lot_has_no_invoice(self, api):
        """PRD §3.4: "If `has_met_reserve` is false, the lot transitions to `UNSOLD`..."
        PRD §2.5: "ERR_INVOICE_NOT_FOUND" — "Invoice for the given lot does not exist
        (lot never reached SOLD)."

        Claim: GET invoice on UNSOLD lot → 404 ERR_INVOICE_NOT_FOUND.

        # difficulty: non_linear_state_machine/lot_branching_with_revert_shape
        """
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=200_000)
        bidder = create_bidder("LoneBidder", wallet_amount_cents=2_000_000)
        place_bid_on_lot(bidder, lot, 100_000)
        lot = close_lot_to_sold(lot["id"])
        assert lot["status"] == "UNSOLD"
        resp = api.get_invoice(lot["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND.value)

    def test_invoice_created_on_sold(self, api):
        """PRD §3.4: "An `Invoice` is created in `PENDING` and immediately auto-advances
        to `ISSUED` in the same transaction; at issuance the `Invoice` snapshots
        `lot_id`, `buyer_id` (the winning bidder), `seller_id`, and `hammer_price_cents`,
        and computes the three composed monetary fields described below."

        Claim: After SOLD, /invoice returns invoice with status=ISSUED and snapshot fields.
        """
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000,
        )
        assert invoice["status"] == "ISSUED"
        assert invoice["lot_id"] == lot["id"]
        assert invoice["buyer_id"] == bidder["id"]
        assert invoice["seller_id"] == seller["id"]
        assert invoice["hammer_price_cents"] == 100_000
        assert_invoice_money_invariants(invoice)


class TestBuyerPremiumTiers:
    def test_buyer_premium_tier1_inclusive_at_100000(self, api):
        """PRD §3.4: "The base rate is 15% when the hammer is at most 100000 cents,
        12% when it is at most 1000000 cents, and 10% otherwise — the upper bounds are
        inclusive, so a hammer of exactly 100000 cents falls into the 15% tier and a
        hammer of 100001 cents into the 12% tier."

        Claim: hammer=100000 (tier 1 inclusive) → buyer_premium = floor(100000 * 0.15) = 15000.
        """
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000,
        )
        assert invoice["hammer_price_cents"] == 100_000
        assert invoice["buyer_premium_cents"] == 15_000

    def test_buyer_premium_tier2_at_100001(self, api):
        """PRD §3.4: "...a hammer of 100001 cents into the 12% tier."

        Claim: hammer=100001 → buyer_premium = floor(100001 * 0.12) = 12000.
        """
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=100_001, starting_bid_cents=100_001, bid_amount_cents=100_001,
        )
        assert invoice["hammer_price_cents"] == 100_001
        assert invoice["buyer_premium_cents"] == 12_000  # floor(100001 * 0.12) = 12000

    def test_buyer_premium_jewelry_surcharge_and_verified_discount(self, api):
        """PRD §3.4: "The base rate is then increased by 2 percentage points if
        `Lot.category` is `JEWELRY`, and decreased by 1 percentage point if the winning
        bidder's `identity_verified` is true; the `JEWELRY` surcharge and verified-bidder
        discount stack independently and additively. The final premium is the
        floor-truncation of the hammer multiplied by the effective rate, raised to a
        minimum of 100 cents..."

        Claim: hammer=200000, JEWELRY, verified bidder → rate = 0.12 + 0.02 - 0.01 = 0.13;
        premium = floor(200000 * 0.13) = 26000.

        # difficulty: combinatorial_formula/buyer_premium_three_input_combinatorial
        """
        from test_helpers import LotCategory
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=150_000, starting_bid_cents=150_000, bid_amount_cents=200_000,
            category=LotCategory.JEWELRY.value, bidder_identity_verified=True,
        )
        assert invoice["hammer_price_cents"] == 200_000
        assert invoice["buyer_premium_cents"] == 26_000

    def test_buyer_premium_minimum_floor(self, api):
        """PRD §3.4: "The final premium is the floor-truncation of the hammer multiplied
        by the effective rate, raised to a minimum of 100 cents — so even a microscopic
        hammer pays at least one dollar of premium."

        Claim: tiny hammer → buyer_premium clamps to MIN_PREMIUM_CENTS=100.
        """
        # reserve=500 (deposit_required=500), starting=500. hammer=500 → floor(500*0.15)=75 < 100 → clamp to 100
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=500, starting_bid_cents=500, bid_amount_cents=500,
        )
        assert invoice["buyer_premium_cents"] == 100


class TestSellerCommissionTiers:
    def test_seller_commission_tier1_inclusive_at_500000(self, api):
        """PRD §3.4: "10% when the hammer is at most 500000 cents, 8% when it is at
        most 5000000 cents, and 5% otherwise..."

        Claim: hammer=500000 (tier 1 inclusive) → seller_commission = floor(500000 * 0.10) = 50000.
        """
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=500_000, starting_bid_cents=500_000, bid_amount_cents=500_000,
            bidder_wallet=2_000_000,
        )
        assert invoice["hammer_price_cents"] == 500_000
        assert invoice["seller_commission_cents"] == 50_000

    def test_seller_commission_tier2_at_500001(self, api):
        """PRD §3.4: "8% when it is at most 5000000 cents..."

        Claim: hammer=500001 → seller_commission = floor(500001 * 0.08) = 40000.
        """
        seller, lot, bidder, invoice = setup_sold_lot(
            reserve_price_cents=500_001, starting_bid_cents=500_001, bid_amount_cents=500_001,
            bidder_wallet=5_000_000,
        )
        assert invoice["hammer_price_cents"] == 500_001
        assert invoice["seller_commission_cents"] == 40_000


class TestPaymentConfirmation:
    def test_payment_confirmed_moves_invoice_to_paid(self, api):
        """PRD §3.4: "Payment is recorded by the external payment system through an
        event ingestion: arriving with an `invoice_id` and a `paid_at`, the event moves
        the `Invoice` from `ISSUED` to `PAID`..."

        Claim: payment-confirmed event → Invoice.status=PAID.
        """
        seller, lot, bidder, invoice = setup_paid_lot()
        assert invoice["status"] == "PAID"

    def test_payment_credits_seller_proceeds(self, api):
        """PRD §3.4: "the seller's `gross_proceeds_cents` and `net_proceeds_cents` each
        increase by the invoice's `seller_payout_cents`."

        Claim: After payment, Seller.gross_proceeds = seller_payout (= hammer - commission).
        """
        seller, lot, bidder, invoice = setup_paid_lot(
            reserve_price_cents=100_000, starting_bid_cents=100_000, bid_amount_cents=100_000,
        )
        assert invoice["status"] == "PAID"
        assert invoice["seller_payout_cents"] == 90_000  # 100000 - floor(100000*0.10)
        seller_after = validate_success(api.get_seller(seller["id"], ADMIN))
        assert seller_after["gross_proceeds_cents"] == 90_000
        assert seller_after["net_proceeds_cents"] == 90_000

    def test_payment_confirmed_on_already_paid_invoice(self, api):
        """PRD §3.4: "A payment-confirmed event for an `Invoice` not in `ISSUED` —
        already `PAID`, already `REVERSED`, or still `PENDING` — is rejected with
        `ERR_INVOICE_NOT_ISSUED`."

        Claim: Second payment-confirmed event for same invoice → ERR_INVOICE_NOT_ISSUED.
        """
        seller, lot, bidder, invoice = setup_paid_lot()
        # Replay
        resp = api.event_payment_confirmed(
            event_payment_confirmed_payload(invoice["id"], iso_relative(0)),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED.value)
