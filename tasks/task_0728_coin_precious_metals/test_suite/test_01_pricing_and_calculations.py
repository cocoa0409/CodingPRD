"""Pricing engine and money calculations: melt-value-derived sell price,
dual-variant COGS (weighted-average provisional vs FIFO final), hedge PnL,
and the round-then-sum settlement breakdown.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_spot_rate,
    create_product,
    create_inventory_lot,
    create_customer,
    create_placed_sell_order,
    setup_sold_consignment,
    create_settlement_payload,
    create_hedge_position_payload,
    TEST_USERS,
)

TRADER = TEST_USERS["trader_headers"]
SALES = TEST_USERS["sales_agent_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Rule 1a: provisional (weighted-average) vs final (FIFO) COGS diverge ──

def _setup_two_lot_sell_order():
    """GOLD spot 200000; BULLION 1oz product (sell 210000); lot1 5@100000
    (older), lot2 5@120000 (newer); a sell order for quantity 6."""
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-1OZ-BULLION", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    create_inventory_lot(product["id"], total_qty=5, acquisition_unit_cost_cents=100_000)
    create_inventory_lot(product["id"], total_qty=5, acquisition_unit_cost_cents=120_000)
    customer = create_customer("Buyer One")
    order = create_placed_sell_order(product["id"], customer["id"], quantity=6)
    return order


def test_provisional_and_final_cogs_diverge_on_settle(api):
    """PRD §3.2: "Because the provisional figure weights all available lots
    equally by quantity while the final figure consumes the oldest lots first,
    when lots for the same product carry different acquisition_unit_cost_cents
    the provisional and final costs will differ for identical order inputs".

    Design: Difficulty/dual_variant_calc/sell_cogs_provisional_vs_final_diverge
    """
    order = _setup_two_lot_sell_order()
    assert order["provisional_cogs_cents"] == 660_000

    settled = validate_success(api.settle_sell_order(order["id"], SALES), 200)
    assert settled["final_cogs_cents"] == 620_000
    assert settled["provisional_cogs_cents"] != settled["final_cogs_cents"]


def test_realized_margin_uses_final_cogs(api):
    """PRD §3.3: "The system then sets realized_margin_cents to total_price_cents
    minus final_cogs_cents."

    Design: Difficulty/dual_variant_calc/sell_cogs_provisional_vs_final_diverge
    """
    order = _setup_two_lot_sell_order()
    assert order["total_price_cents"] == 1_260_000

    settled = validate_success(api.settle_sell_order(order["id"], SALES), 200)
    assert settled["realized_margin_cents"] == 640_000
    assert settled["realized_margin_cents"] == settled["total_price_cents"] - settled["final_cogs_cents"]


# ─── Rule 1b: hedge unrealized (live) vs realized (fixed at close) PnL ──────

def _open_hedge_then_move_spot():
    """GOLD spot 200000 at open; short 10 oz (entry 200000); spot moves to 190000."""
    rate = set_spot_rate("GOLD", 200_000)
    hedge = get_success_data(api_client.create_hedge_position(
        create_hedge_position_payload(metal="GOLD", short_troy_oz=10), TRADER))
    api_client.update_spot_rate(rate["id"], {"price_per_troy_oz_cents": 190_000}, TRADER)
    return hedge


def test_hedge_unrealized_pnl_live_against_current_spot(api):
    """PRD §3.9: "the system subtracts the current spot price for the metal from
    the position's entry_spot_cents, multiplies that difference by the
    short_troy_oz, and rounds half up to whole cents."

    Design: Difficulty/dual_variant_calc/hedge_unrealized_vs_realized_pnl
    """
    hedge = _open_hedge_then_move_spot()
    assert hedge["entry_spot_cents"] == 200_000

    read = validate_success(api.get_hedge_position(hedge["id"], TRADER), 200)
    assert read["unrealized_pnl_cents"] == 100_000


def test_hedge_realized_pnl_fixed_at_close(api):
    """PRD §3.9: "the system captures the exit_spot_cents from the current spot
    rate, then computes the realized profit-and-loss by subtracting the captured
    exit_spot_cents from the entry_spot_cents, multiplying by the short_troy_oz,
    and rounding half up to whole cents".

    Design: Difficulty/dual_variant_calc/hedge_unrealized_vs_realized_pnl
    """
    hedge = _open_hedge_then_move_spot()
    closed = validate_success(api.close_hedge_position(hedge["id"], TRADER), 200)
    assert closed["realized_pnl_cents"] == 100_000
    assert closed["exit_spot_cents"] == 190_000
    assert closed["status"] == "CLOSED"


# ─── Rule 2a: numismatic premium added to melt BEFORE the spread ───────────

def _place_numismatic_order():
    """GOLD spot 200000; NUMISMATIC 1oz product premium 15000, spread 0.05
    (melt 200000, base 215000, sell 225750); a sell order quantity 1."""
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-NUM-01", product_type="NUMISMATIC", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04, numismatic_premium_cents=15_000)
    customer = create_customer("Collector")
    return create_placed_sell_order(product["id"], customer["id"], quantity=1)


def test_numismatic_quoted_price_premium_then_spread(api):
    """PRD §3.1: "for a numismatic item the collectible premium is added to melt
    before the sell spread is applied, so the spread compounds over the premium
    as well as the metal."

    Design: Difficulty/combinatorial_formula/numismatic_sell_price_premium_then_spread
    """
    order = _place_numismatic_order()
    assert order["quoted_unit_price_cents"] == 225_750


def test_numismatic_total_price_locks_quoted(api):
    """PRD §3.3: "sets total_price_cents to the quoted unit price multiplied by
    the quantity".

    Design: Difficulty/combinatorial_formula/numismatic_sell_price_premium_then_spread
    """
    order = _place_numismatic_order()
    assert order["total_price_cents"] == 225_750


# ─── Rule 2b: settlement rounds each component independently, then sums ─────

def _settle_hammer(hammer, commission_pct, buyer_premium_pct, reserve=50_000, room="ROOM-SB"):
    ctx = setup_sold_consignment(reserve_price_cents=reserve, commission_pct=commission_pct,
                                 buyer_premium_pct=buyer_premium_pct, hammer_price_cents=hammer,
                                 room=room, customer_name="Consignor")
    settlement = validate_success(
        api_client.create_settlement(
            create_settlement_payload(ctx["consignment"]["id"]), COMPLIANCE), 201)
    return settlement


def test_settlement_components_rounded_independently(api):
    """PRD §3.7: "the commission_cents is the hammer_price_cents multiplied by the
    consignment's commission_pct, rounded half up to whole cents; the
    buyer_premium_cents is the hammer_price_cents multiplied by the consignment's
    buyer_premium_pct, rounded half up to whole cents independently of the commission".

    Design: Difficulty/combinatorial_formula/settlement_round_each_component_then_sum
    """
    settlement = _settle_hammer(100_003, 0.125, 0.075)
    assert settlement["commission_cents"] == 12_500
    assert settlement["buyer_premium_cents"] == 7_500


def test_settlement_dealer_revenue_round_then_sum(api):
    """PRD §3.7: "the dealer_revenue_cents is the already-rounded commission_cents
    plus the already-rounded buyer_premium_cents. This round-then-sum order is
    required — rounding the sum of the two percentages together would produce a
    different cent in edge cases."

    Design: Difficulty/combinatorial_formula/settlement_round_each_component_then_sum
    """
    settlement = _settle_hammer(100_003, 0.125, 0.075)
    assert settlement["dealer_revenue_cents"] == 20_000
    assert settlement["seller_proceeds_cents"] == 87_503
