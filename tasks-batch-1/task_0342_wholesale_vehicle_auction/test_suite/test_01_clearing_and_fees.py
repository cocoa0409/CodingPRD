"""Clearing-price, bid-increment, buyer-fee, total-due and seller-proceeds arithmetic.

Covers the dual-variant fee/proceeds calculations, the nested min/max clearing
formula, the per-term-then-sum rounding order, and numeric band boundaries.
"""
import pytest

from test_helpers import (
    make_admin_headers, make_buyer_headers, make_arbitrator_headers,
    get_success_data, validate_success,
    setup_two_proxy_hammered_lot, setup_paid_settlement_with_open_claim,
    setup_running_sale_with_lot, setup_hammered_lot,
    open_bidding, current_lot_version, place_bid_ok, get_settlement_for_lot,
)
import test_helpers as th


# ─── dual_variant_calc ──────────────────────────────────────────────────────
def test_buyer_fee_provisional_at_hammer_then_final_after_partial_arbitration(api):
    """PRD §3.7: "for a sale price from 200000 up to but not including 1000000 the base
    is 6% of the sale price, rounded half up to cents".
    PRD §3.7: "if the winning bid's `channel` is `ONLINE`, the surcharge is 10% of the
    base rounded half up to cents".
    PRD §3.10: "the settlement's `sale_price_cents` is reduced by `approved_cents`; the
    final `buyer_fee_cents`, `total_due_cents`, and `seller_proceeds_cents` are recomputed
    on the reduced sale price (which can drop the fee into a lower tier band, changing the fee)".

    Design: Difficulty/dual_variant_calc/buyer_fee_provisional_vs_final_after_partial_arbitration
    """
    admin = make_admin_headers()
    # Two-proxy clearing settles to 725000 (B1 ceiling 900000, B2 ceiling 700000,
    # second_ref = max(700000, house_floor 600000) = 700000; +25000 increment = 725000).
    ctx = setup_paid_settlement_with_open_claim(
        api, admin_headers=admin, claimed_cents=100000, reason_code="MECHANICAL",
        starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000, channel="ONLINE",
        buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02,
    )
    settlement = get_success_data(api.get_settlement(ctx["settlement"]["id"], admin))
    assert settlement["sale_price_cents"] == 725000, settlement
    assert settlement["buyer_fee_cents"] == 47850, "provisional fee on S=725000 ONLINE STANDARD"

    # Rule the claim: claimed 100000 <= cap (30% of 725000 = 217500) -> APPROVED_PARTIAL at 100000.
    ruled = get_success_data(api.rule_arbitration_claim(ctx["claim"]["id"], make_arbitrator_headers()))
    assert ruled["resolution"] == "APPROVED_PARTIAL", ruled

    final = get_success_data(api.get_settlement(ctx["settlement"]["id"], admin))
    assert final["sale_price_cents"] == 625000, "S reduced by 100000"
    assert final["buyer_fee_cents"] == 41250, "final fee on S=625000 ONLINE STANDARD"
    assert final["total_due_cents"] == 666250, "625000 + 41250"


def test_seller_proceeds_provisional_at_hammer_then_final_after_partial_arbitration(api):
    """PRD §3.8: "The seller commission is the sale price multiplied by `seller_fee_pct`,
    rounded half up to cents, and then capped at 150000".
    PRD §3.8: "The seller's net proceeds are the sale price minus the seller commission
    minus the assurance fee, floored at 0 so the figure is never negative."
    PRD §3.10: "the final `buyer_fee_cents`, `total_due_cents`, and `seller_proceeds_cents`
    are recomputed on the reduced sale price".

    Design: Difficulty/dual_variant_calc/seller_proceeds_provisional_vs_final_after_partial_arbitration
    """
    admin = make_admin_headers()
    ctx = setup_paid_settlement_with_open_claim(
        api, admin_headers=admin, claimed_cents=100000, reason_code="MECHANICAL",
        starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000, channel="ONLINE",
        buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02,
    )
    # Provisional proceeds at hammer S=725000: 725000 - round(725000*0.02)=14500 - 5000 = 705500.
    cons_before = get_success_data(api.get_consignment(ctx["consignment"]["id"], admin))
    assert cons_before["expected_proceeds_cents"] == 705500, cons_before

    get_success_data(api.rule_arbitration_claim(ctx["claim"]["id"], make_arbitrator_headers()))

    final_settlement = get_success_data(api.get_settlement(ctx["settlement"]["id"], admin))
    cons_after = get_success_data(api.get_consignment(ctx["consignment"]["id"], admin))
    # Final proceeds at S=625000: 625000 - round(625000*0.02)=12500 - 5000 = 607500.
    assert cons_after["expected_proceeds_cents"] == 607500, cons_after
    assert final_settlement["seller_proceeds_cents"] == 607500, final_settlement


# ─── combinatorial_formula ──────────────────────────────────────────────────
def test_clearing_price_nested_min_max_over_three_inputs(api):
    """PRD §3.5: "if two or more buyers have bid, with top ceiling C1 (buyer B1) and
    second-highest ceiling C2, then `high_bidder_id` is B1, and `high_bid_cents` is the
    lesser of C1 and the quantity `(second reference plus one bid increment computed on
    that second reference)`, where the second reference is the greater of C2 and the house floor."

    Design: Difficulty/combinatorial_formula/clearing_price_nested_min_max_three_inputs
    """
    admin = make_admin_headers()
    # starting_bid 500000, floor 0 -> house_floor 500000. B2 LIVE 500000, B1 PROXY 1000000.
    # second_ref = max(500000, 500000) = 500000; increment(500000) = 25000 (band2, >=).
    # clearing = min(1000000, 500000 + 25000) = 525000.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=500000)
    b1 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    b2 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B2"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], b2["id"], lot_open["version"],
                 bid_type="LIVE", amount_cents=500000, channel="LANE")
    v1 = current_lot_version(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], b1["id"], v1,
                 bid_type="PROXY", amount_cents=1000000, channel="ONLINE")

    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["high_bid_cents"] == 525000, lot
    assert lot["high_bidder_id"] == b1["id"], lot


def test_buyer_total_due_rounds_each_term_then_sums(api):
    """PRD §2.7: "each percentage-derived term is rounded to cents first, and only then
    are the rounded terms summed. The system never sums raw fractional terms and rounds
    once at the end".
    PRD §3.7: "The buyer's `total_due_cents` is the settlement's `sale_price_cents` plus
    its `buyer_fee_cents`."

    Design: Difficulty/combinatorial_formula/buyer_total_due_rounding_order_per_term_then_sum
    """
    admin = make_admin_headers()
    # Single PROXY 300000 ONLINE, starting_bid 200008 -> single-proxy clearing = 200008.
    # base = round(200008*0.06)=round(12000.48)=12000; surcharge=round(12000*0.10)=1200; fee=13200.
    # total = 200008 + 13200 = 213208. (sum-then-round-once would give 13201 -> 213209.)
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=200008, buyer_fee_schedule_code="STANDARD",
                                      seller_fee_pct=0.02)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=300000, channel="ONLINE")
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin))
    lot = get_success_data(api.hammer_lot(ctx["lot"]["id"], admin))
    assert lot["hammer_price_cents"] == 200008, lot

    settlement = get_settlement_for_lot(api, ctx["lot"]["id"], admin)
    assert settlement["buyer_fee_cents"] == 13200, settlement
    assert settlement["total_due_cents"] == 213208, settlement


# ─── boundary_precision_check ───────────────────────────────────────────────
def test_bid_increment_band_boundary_at_exactly_500000_uses_25000(api):
    """PRD §3.5: "The band boundaries are taken on the lower band's exclusion and the
    upper band's inclusion: a reference price of exactly 500000 uses 25000, and a
    reference price of exactly 1000000 uses 50000."

    Design: Difficulty/boundary_precision_check/bid_increment_band_boundary_at_exactly_500000
    """
    admin = make_admin_headers()
    # starting_bid 500000; B2 LIVE 500000, B1 PROXY 1000000 -> second_ref 500000, increment 25000,
    # clearing = min(1000000, 500000+25000) = 525000 (NOT 510000 which 10000 would give).
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=500000)
    b1 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    b2 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B2"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], b2["id"], lot_open["version"],
                 bid_type="LIVE", amount_cents=500000, channel="LANE")
    v1 = current_lot_version(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], b1["id"], v1,
                 bid_type="PROXY", amount_cents=1000000, channel="ONLINE")

    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["high_bid_cents"] == 525000, lot


def test_reserve_threshold_inclusive_hammer_succeeds_at_exact_reserve(api):
    """PRD §3.6: "if `high_bid_cents` is at least the consignment's `reserve_price_cents`,
    the outcome is `SOLD`".
    PRD §3.6: "The reserve threshold is inclusive — a frozen high bid exactly equal to the
    reserve sells".

    Design: Difficulty/boundary_precision_check/reserve_threshold_inclusive_sold_at_exact_reserve
    """
    admin = make_admin_headers()
    # Reserve 600000; starting_bid 600000; single PROXY 600000 -> clearing 600000 == reserve -> SOLD.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=600000, floor_price_cents=0,
                                      starting_bid_cents=600000)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=600000, channel="LANE")
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin))
    lot = get_success_data(api.hammer_lot(ctx["lot"]["id"], admin))
    assert lot["outcome"] == "SOLD", lot
    assert lot["hammer_price_cents"] == 600000, lot
    assert lot["status"] == "HAMMERED", lot


# ─── arbitration_partial_recredit_delta (corner, active instance) ───────────
def test_partial_arbitration_recredits_buyer_by_total_due_delta(api):
    """PRD §3.10: "the buyer is re-credited by the difference between the old total due and
    the new total due."
    PRD §2.10: "The read-only `available_credit_cents` is `credit_limit_cents` minus
    `committed_cents`".

    Design: Corner/cross_cutting_complexity_layers/arbitration_partial_recredit_delta
    """
    admin = make_admin_headers()
    ctx = setup_paid_settlement_with_open_claim(
        api, admin_headers=admin, claimed_cents=100000, reason_code="MECHANICAL",
        starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000, channel="ONLINE",
        buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02,
        b1_credit=2_000_000,
    )
    # Post-hammer total_due 772850, committed 772850, available 1227150.
    b1_before = get_success_data(api.get_buyer(ctx["b1"]["id"], admin))
    assert b1_before["committed_cents"] == 772850, b1_before

    ruled = get_success_data(api.rule_arbitration_claim(ctx["claim"]["id"], make_arbitrator_headers()))
    assert ruled["approved_cents"] == 100000, ruled

    b1_after = get_success_data(api.get_buyer(ctx["b1"]["id"], admin))
    # new total_due 666250 -> committed 666250, available 2,000,000 - 666250 = 1,333,750.
    assert b1_after["committed_cents"] == 666250, b1_after
    assert b1_after["available_credit_cents"] == 1333750, b1_after


# ─── consistency_model: immediate (corner) ──────────────────────────────────
def test_hammer_immediately_reflects_buyer_committed_credit(api):
    """PRD §3.6: "it debits the winning buyer's `available_credit_cents` by that
    `total_due_cents`, recomputing `committed_cents`."
    PRD §2.11: "every entity a cascade reaches is updated to a consistent state before
    the originating request returns."

    Design: Corner/consistency_model/hammer_response_reflects_all_immediate_side_effects
    """
    admin = make_admin_headers()
    ctx = setup_two_proxy_hammered_lot(
        api, admin, starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000,
        channel="ONLINE", buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02,
        b1_credit=2_000_000,
    )
    b1 = get_success_data(api.get_buyer(ctx["b1"]["id"], admin))
    # total_due at S=725000 ONLINE STANDARD = 772850.
    assert b1["committed_cents"] == 772850, b1
    assert b1["available_credit_cents"] == 1227150, b1
