"""Cascading side effects (campaign close, seller block) and compensating
reversals (refund conserves money / credit).

Covers difficulty queue A rules: transitive_cascade, compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated,
    setup_active_catalog, setup_active_pledge,
    place_simple_order, place_and_pay_order, place_order, order_line,
    create_pledge,
    add_product, add_prize_tier,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


# ─── transitive_cascade / close_cascades_order_cancel_to_reservation_release

class TestCloseCascade:
    def test_close_cancels_pending_order(self, api, admin_headers):
        """PRD §3.2: "every `Order` that is still unpaid — `payment_status` equal
        to `PENDING` — and whose `fulfillment_status` is either `PLACED` or
        `CONFIRMED` has its `fulfillment_status` driven to `CANCELLED`."

        Design: Difficulty/transitive_cascade/close_cascades_order_cancel_to_reservation_release
        """
        camp, seller, product = setup_active_catalog()
        order = place_simple_order(camp["id"], seller["id"], product["id"], 5)

        closed = validate_success(api.close_campaign(camp["id"], admin_headers), 200)
        assert closed["posture"] == "CLOSED"

        after = validate_success(api.get_order(order["id"], admin_headers), 200)
        assert after["fulfillment_status"] == "CANCELLED", \
            "PENDING+PLACED order must be cancelled by close cascade"

    def test_close_cascade_releases_product_reservation(self, api, admin_headers):
        """PRD §3.2: "each of those order cancellations releases that order's
        line reservations, so each affected product's `reserved_qty`
        recomputes downward."

        Design: Difficulty/transitive_cascade/close_cascades_order_cancel_to_reservation_release
        """
        camp, seller, product = setup_active_catalog()
        place_simple_order(camp["id"], seller["id"], product["id"], 5)
        before = validate_success(api.get_product(product["id"], admin_headers), 200)
        assert before["reserved_qty"] == 5

        validate_success(api.close_campaign(camp["id"], admin_headers), 200)
        after = validate_success(api.get_product(product["id"], admin_headers), 200)
        assert after["reserved_qty"] == 0, \
            "reserved_qty must fall to 0 after the close cascade cancels the order"


# ─── transitive_cascade / block_cascades_to_promised_pledge_cancel ─────────

class TestBlockCascade:
    def test_block_marks_seller_blocked(self, api, admin_headers):
        """PRD §3.3: "A seller's status moves between `ACTIVE` and `BLOCKED`."

        Design: Difficulty/transitive_cascade/block_cascades_to_promised_pledge_cancel
        """
        camp, seller = setup_active_pledge()
        create_pledge(camp["id"], seller["id"], per_unit_cents=0, flat_cents=4000)

        blocked = validate_success(api.block_seller(seller["id"], admin_headers), 200)
        assert blocked["status"] == "BLOCKED"

    def test_block_cancels_promised_pledge(self, api, admin_headers):
        """PRD §3.3: "Every `Pledge` crediting this seller that is still
        `PROMISED` is moved to `CANCELLED`."

        Design: Difficulty/transitive_cascade/block_cascades_to_promised_pledge_cancel
        """
        camp, seller = setup_active_pledge()
        pledge = create_pledge(camp["id"], seller["id"], per_unit_cents=0, flat_cents=4000)
        assert pledge["status"] == "PROMISED"

        validate_success(api.block_seller(seller["id"], admin_headers), 200)
        after = validate_success(api.get_pledge(pledge["id"], admin_headers), 200)
        assert after["status"] == "CANCELLED", \
            "a PROMISED pledge of the blocked seller must be cancelled by the block cascade"


# ─── compensating_invariant / pay_then_refund_conserves_gross_collected ────

class TestRefundConservesCampaignGross:
    def test_refund_returns_order_to_refunded(self, api, admin_headers):
        """PRD §3.4: "Refunding an order moves `payment_status` from `PAID` to
        `REFUNDED` and is the compensating reversal of payment."

        Design: Difficulty/compensating_invariant/pay_then_refund_conserves_gross_collected
        """
        camp, seller, product = setup_active_catalog()
        order = place_and_pay_order(camp["id"], seller["id"], product["id"], 5)
        assert order["payment_status"] == "PAID"

        refunded = validate_success(api.refund_order(order["id"], admin_headers), 200)
        assert refunded["payment_status"] == "REFUNDED"

    def test_refund_removes_amount_from_campaign_gross(self, api, treasurer_headers, admin_headers):
        """PRD §3.4: "The order stops counting toward the seller's
        `credited_cents` and the campaign's `gross_collected_cents`"

        PRD §3.8: "the **final** view is `gross_collected_cents`: the sum of
        `total_charged_cents` over orders that are `PAID`, plus the sum of
        `collected_cents` over pledges that are `COLLECTED`. Refunded orders
        are excluded."

        Design: Difficulty/compensating_invariant/pay_then_refund_conserves_gross_collected
        """
        camp, seller, product = setup_active_catalog()
        order = place_and_pay_order(camp["id"], seller["id"], product["id"], 5)
        paid_camp = validate_success(api.get_campaign(camp["id"], treasurer_headers), 200)
        assert paid_camp["gross_collected_cents"] == 10825

        validate_success(api.refund_order(order["id"], admin_headers), 200)
        refunded_camp = validate_success(api.get_campaign(camp["id"], treasurer_headers), 200)
        assert refunded_camp["gross_collected_cents"] == 0, \
            "refund must remove the paid amount from gross_collected_cents (back to 0)"


# ─── compensating_invariant / refund_conserves_seller_credit_and_drops_tier

class TestRefundConservesSellerCredit:
    def _setup_two_paid_orders(self):
        """Seller with O1 PAID 10825 and O2 PAID 5842; tiers at 5000 (BRONZE)
        and 10000 (SILVER). Returns (seller, bronze_id, o1)."""
        # setup_active_catalog already adds tier T1 @5000 (the BRONZE role).
        camp, seller, product = setup_active_catalog(prize_threshold_cents=5000)
        add_prize_tier(camp["id"], label="SILVER", threshold_cents=10000)
        mug = add_product(camp["id"], sku="MUG", name="Mug",
                          unit_price_cents=1299, unit_cost_cents=500, stock_qty=100)
        pen = add_product(camp["id"], sku="PEN", name="Pen",
                          unit_price_cents=750, unit_cost_cents=200, stock_qty=100)
        o1 = place_and_pay_order(camp["id"], seller["id"], product["id"], 5)  # 10825
        o2 = place_order(camp["id"], seller["id"],
                         [order_line(mug["id"], 3), order_line(pen["id"], 2)])  # 5842
        api_client.pay_order(o2["id"], ADMIN)
        tiers, _ = validate_paginated(api_client.list_prize_tiers(
            ADMIN, params={"campaign_id": camp["id"]}))
        bronze_id = next(t["id"] for t in tiers if t["threshold_cents"] == 5000)
        return seller, bronze_id, o1

    def test_refund_drops_credit_to_remaining_paid_order(self, api):
        """PRD §3.6: "A seller's `credited_cents` is the settled money attributed
        to them: the sum of `total_charged_cents` over their orders that are
        `PAID`, plus the sum of `collected_cents` over their pledges that are
        `COLLECTED`. Refunded orders and cancelled pledges contribute
        nothing."

        Design: Difficulty/compensating_invariant/refund_conserves_seller_credit_and_drops_tier
        """
        seller, bronze_id, o1 = self._setup_two_paid_orders()
        # Before refund: credited = 10825 + 5842 = 16667 -> SILVER(10000).
        api_client.refund_order(o1["id"], ADMIN)
        after = validate_success(api_client.get_seller(seller["id"], TREASURER), 200)
        assert after["credited_cents"] == 5842, \
            f"refunding O1 leaves only O2's 5842 credited, got {after['credited_cents']}"

    def test_refund_drops_earned_tier_back_to_bronze(self, api):
        """PRD §3.6: "Among the campaign's prize tiers, the seller earns the
        single highest tier whose `threshold_cents` is less than or equal to
        their `credited_cents`."

        PRD §3.6: "each recomputes `earned_prize_tier_id`, which may step up
        on new revenue or step down on a refund."

        Design: Difficulty/compensating_invariant/refund_conserves_seller_credit_and_drops_tier
        """
        seller, bronze_id, o1 = self._setup_two_paid_orders()
        api_client.refund_order(o1["id"], ADMIN)
        after = validate_success(api_client.get_seller(seller["id"], TREASURER), 200)
        # credited now 5842: highest tier <= 5842 is BRONZE(5000), not SILVER(10000).
        assert after["earned_prize_tier_id"] == bronze_id, \
            f"earned tier must drop to BRONZE(5000) after refund, got {after['earned_prize_tier_id']}"
