"""Estate close settlement sweep, order pricing, buyer ledgers, provisional vs
final gross, and the seller payout split.
"""
from test_helpers import (
    validate_success, ApiErrorId,
    operator_headers, make_buyer_headers, assert_payout_split_invariant,
    new_estate, new_verified_buyer, new_listed_lot, lot_version, bid_on,
    first_order, get_order,
    setup_won_lot, setup_provisional_vs_final, setup_gross_vs_net,
    setup_three_lot_order,
)

OP = operator_headers()


# ==========================================================================
# Depth-3 cascade from a single close: lot -> order -> buyer ledger
# ==========================================================================
class TestCloseCascade:
    def test_close_sells_lot_and_prices_order(self, api):
        """PRD §3.4: "The order's subtotal_cents is the sum of
        hammer_price_cents over the lots in lot_ids." PRD §3.4: "The total_cents
        is the sum of subtotal_cents, buyer_premium_cents, and sales_tax_cents."
        PRD §3.4: "When a lot goes SELLING → SOLD, its hammer_price_cents is
        stamped to that high amount and its winning bid's is_winning is confirmed
        true; a passed lot keeps hammer_price_cents at null."

        Design: Difficulty/transitive_cascade/close_cascade_lot_order_buyer
        """
        s = setup_won_lot(api, amount=10000)
        validate_success(api.close_estate(s["estate"]["id"], OP))
        lot = validate_success(api.get_lot(s["lot"]["id"], OP))
        assert lot["status"] == "SOLD"
        assert lot["hammer_price_cents"] == 10000
        order = first_order(api, buyer_id=s["buyer"]["id"])
        assert order["subtotal_cents"] == 10000
        assert order["total_cents"] == 12690

    def test_close_recomputes_buyer_ledger(self, api):
        """PRD §3.4: "A buyer's gross_owed_cents is the sum of total_cents across
        all of that buyer's orders, while their net_owed_cents is the sum of
        total_cents across only those of the buyer's orders whose payment_status
        is UNPAID; a paid or refunded order drops out of the net figure but
        remains in the gross figure."

        Design: Difficulty/transitive_cascade/close_cascade_lot_order_buyer
        """
        s = setup_won_lot(api, amount=10000)
        validate_success(api.close_estate(s["estate"]["id"], OP))
        buyer = validate_success(api.get_buyer(s["buyer"]["id"], OP))
        assert buyer["gross_owed_cents"] == 12690
        assert buyer["net_owed_cents"] == 12690


# ==========================================================================
# Dual-variant estate gross: provisional (at close) vs final (at settle)
# ==========================================================================
class TestProvisionalVsFinalGross:
    def test_provisional_and_final_gross_diverge(self, api):
        """PRD §3.4: "The provisional_gross_cents is the sum of current_bid_cents
        over every lot that carried at least one accepted bid at close —
        deliberately including lots that were passed because their reserve was
        not met, since they still attracted a bid." PRD §3.7: "The estate's
        gross_sales_cents is the sum of hammer_price_cents over the lots that are
        in SOLD status and whose winning order's payment_status is PAID; unpaid,
        reversed, or passed lots are excluded, so the final gross is always less
        than or equal to the provisional gross taken at close."

        Design: Difficulty/dual_variant_calc/estate_provisional_vs_final_gross
        """
        s = setup_provisional_vs_final(api)  # o1 PAID (10000), o2 UNPAID (5000)
        estate = validate_success(api.settle_estate(s["estate"]["id"], OP))
        assert estate["provisional_gross_cents"] == 15000
        assert estate["gross_sales_cents"] == 10000

    def test_settle_stamps_commission_and_payout(self, api):
        """PRD §3.7: "The commission_cents is the gross multiplied by the
        estate's commission_bps, divided by 10000, and rounded half-up to a whole
        cent. The seller_payout_cents is the gross minus the commission."

        Design: Difficulty/dual_variant_calc/estate_provisional_vs_final_gross
        """
        s = setup_provisional_vs_final(api)
        estate = validate_success(api.settle_estate(s["estate"]["id"], OP))
        assert estate["commission_cents"] == 3500   # round(10000 * 3500 / 10000)
        assert estate["seller_payout_cents"] == 6500  # 10000 - 3500
        assert_payout_split_invariant(estate)


# ==========================================================================
# Dual-variant buyer owed: gross (all orders) vs net (unpaid only)
# ==========================================================================
class TestBuyerGrossVsNetOwed:
    def test_gross_owed_counts_all_orders(self, api):
        """PRD §3.4: "A buyer's gross_owed_cents is the sum of total_cents across
        all of that buyer's orders, while their net_owed_cents is the sum of
        total_cents across only those of the buyer's orders whose payment_status
        is UNPAID; a paid or refunded order drops out of the net figure but
        remains in the gross figure."

        Design: Difficulty/dual_variant_calc/buyer_gross_owed_vs_net_owed
        """
        s = setup_gross_vs_net(api)  # oa PAID 12690, ob UNPAID 25380
        buyer = validate_success(api.get_buyer(s["buyer"]["id"], OP))
        assert buyer["gross_owed_cents"] == 38070

    def test_net_owed_counts_only_unpaid_orders(self, api):
        """PRD §3.4: "their net_owed_cents is the sum of total_cents across only
        those of the buyer's orders whose payment_status is UNPAID; a paid or
        refunded order drops out of the net figure but remains in the gross
        figure."

        Design: Difficulty/dual_variant_calc/buyer_gross_owed_vs_net_owed
        """
        s = setup_gross_vs_net(api)
        buyer = validate_success(api.get_buyer(s["buyer"]["id"], OP))
        assert buyer["net_owed_cents"] == 25380


# ==========================================================================
# Buyer premium rounded ONCE on the aggregate subtotal (not per-lot)
# ==========================================================================
class TestOrderPremiumAggregateRounding:
    def test_premium_rounded_on_aggregate_subtotal(self, api):
        """PRD §3.4: "The buyer_premium_cents is computed once over that
        aggregate subtotal: multiply the subtotal by the estate's
        buyer_premium_bps, divide by 10000, and round half-up to a whole cent —
        the premium is emphatically not computed lot-by-lot and then summed,
        because rounding the aggregate once can differ by a cent from summing
        per-lot rounded premiums."

        Design: Difficulty/combinatorial_formula/order_premium_aggregate_vs_perlot_rounding
        """
        s = setup_three_lot_order(api)  # three lots of 550 -> subtotal 1650
        order = get_order(api, s["order"]["id"])
        assert order["subtotal_cents"] == 1650
        assert order["buyer_premium_cents"] == 289  # round(1650*1750/10000)=289, not 288

    def test_order_tax_and_total(self, api):
        """PRD §3.4: "The sales_tax_cents is then computed once as the subtotal
        plus the premium, multiplied by the sales-tax rate of 800 basis points,
        divided by 10000, and rounded half-up to a whole cent. The total_cents is
        the sum of subtotal_cents, buyer_premium_cents, and sales_tax_cents."

        Design: Difficulty/combinatorial_formula/order_premium_aggregate_vs_perlot_rounding
        """
        s = setup_three_lot_order(api)
        order = get_order(api, s["order"]["id"])
        assert order["sales_tax_cents"] == 155   # round((1650+289)*800/10000)=155
        assert order["total_cents"] == 2094      # 1650 + 289 + 155


# ==========================================================================
# Reserve not met -> lot PASSED at close (corner)
# ==========================================================================
def test_reserve_not_met_lot_passes(api):
    """PRD §3.4: "The reserve is considered met when the lot's reserve_cents is
    null, or when the high amount is greater than or equal to reserve_cents; a
    bid exactly equal to the reserve sells."
    PRD §3.4: "When a lot goes SELLING → SOLD, its hammer_price_cents is stamped
    to that high amount and its winning bid's is_winning is confirmed true; a
    passed lot keeps hammer_price_cents at null."

    Design: Corner/calculations/reserve_not_met_lot_passes
    """
    estate = new_estate(api)
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    lot = new_listed_lot(api, estate["id"], starting_bid_cents=9900, reserve_cents=10000)
    validate_success(api.open_estate(estate["id"], OP))
    bid_on(api, lot["id"], buyer["id"], 9900)  # 9900 < reserve 10000
    validate_success(api.close_estate(estate["id"], OP))
    lot_after = validate_success(api.get_lot(lot["id"], OP))
    assert lot_after["status"] == "PASSED"
    assert lot_after["hammer_price_cents"] is None
