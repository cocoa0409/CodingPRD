"""Order pricing: provisional vs final settlement, gift-set bundle rounding, wholesale
shipping-on-discounted-subtotal, per-line refill rounding, and freshness-markdown refund."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_member, create_bulk_product, create_bottle, create_gift_set, add_component,
    create_fusti, create_order, pay_order, fulfill_order, create_approved_wholesale,
    set_clock, refill_line, unit_line, bundle_line, make_customer_headers,
)


# ── Difficulty: dual_variant_calc / order_pricing_provisional_vs_final ──

def test_provisional_total_prices_refill_at_list(api):
    """PRD §3.3: "A `REFILL` line contributes its product's `price_per_ml_cents` multiplied
    by its `volume_ml`, rounded half up to a whole cent — each refill line rounded individually."
    PRD §3.3: "The `shipping_fee_cents` is then evaluated against that discounted subtotal:
    it is zero when the discounted subtotal is at least 7,500 cents (seventy-five dollars),
    and otherwise a flat 995 cents."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final
    """
    set_clock(api, "2026-06-29T00:00:00Z")
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                 reorder_point_ml=2000, harvest_date="2026-01-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 5000)])
    assert order["provisional_total_cents"] == 2495, \
        f"expected provisional_total 2495, got {order['provisional_total_cents']}"


def test_final_total_applies_freshness_markdown_below_provisional(api):
    """PRD §3.5: "any refill line whose committed vessel has a `sensory_freshness_score` below
    seventy is repriced as its `price_per_ml_cents` multiplied by its `volume_ml` and by
    eighty-five percent (a fifteen-percent markdown), rounded half up per line before the
    subtotal is summed; all other lines price exactly as they did provisionally."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final
    """
    set_clock(api, "2026-06-29T00:00:00Z")
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                 reorder_point_ml=2000, harvest_date="2026-01-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 5000)])
    order = pay_order(api, member, order)
    set_clock(api, "2026-06-30T00:00:00Z")
    order = fulfill_order(api, order)
    assert order["final_total_cents"] == 2270, \
        f"expected final_total 2270, got {order['final_total_cents']}"
    assert order["final_total_cents"] < order["provisional_total_cents"]


# ── Difficulty: combinatorial_formula / gift_set_round_per_component_then_sum ──

def _gift_set_two_1005_components(api):
    member = create_member(api)
    comp_a = create_bottle(api, unit_price_cents=1005)
    comp_b = create_bottle(api, unit_price_cents=1005)
    gift = create_gift_set(api)
    add_component(api, gift["id"], comp_a["id"], quantity=1)
    add_component(api, gift["id"], comp_b["id"], quantity=1)
    return member, gift


def test_gift_set_rounds_each_component_before_summing(api):
    """PRD §3.3: "for every component of the set, take the component product's `unit_price_cents`
    multiplied by that component's bundled `quantity` and by ninety percent (a ten-percent
    gift-set discount), round that component amount half up to a whole cent, and then sum the
    rounded component amounts — components are rounded first and summed second, never the reverse."

    Design: Difficulty/combinatorial_formula/gift_set_round_per_component_then_sum
    """
    member, gift = _gift_set_two_1005_components(api)
    order = create_order(api, member, [bundle_line(gift["id"], 1)])
    assert order["provisional_subtotal_cents"] == 1810, \
        f"expected 905+905=1810, got {order['provisional_subtotal_cents']}"


def test_gift_set_bundle_total_includes_flat_shipping(api):
    """PRD §3.3: "The `shipping_fee_cents` is then evaluated against that discounted subtotal:
    it is zero when the discounted subtotal is at least 7,500 cents (seventy-five dollars),
    and otherwise a flat 995 cents. The total is the discounted subtotal plus the shipping fee."

    Design: Difficulty/combinatorial_formula/gift_set_round_per_component_then_sum
    """
    member, gift = _gift_set_two_1005_components(api)
    order = create_order(api, member, [bundle_line(gift["id"], 1)])
    assert order["provisional_total_cents"] == 2805, \
        f"expected 1810+995=2805, got {order['provisional_total_cents']}"


# ── Difficulty: combinatorial_formula / order_settlement_shipping_on_discounted_subtotal ──

def _tier1_magnum_order(api):
    member = create_member(api)
    product = create_bottle(api, unit_price_cents=8000)
    wa = create_approved_wholesale(api, member, tier="TIER_1")
    order = create_order(api, member, [unit_line(product["id"], 1)],
                         wholesale_account_id=wa["id"])
    return order


def test_wholesale_discount_applied_before_shipping_eval(api):
    """PRD §3.3: "the wholesale discount rate is zero unless the order carries a wholesale
    account that is `APPROVED`, in which case the rate is ten percent for `TIER_1`, twenty
    percent for `TIER_2`, or thirty percent for `TIER_3`. The `discount_cents` is the subtotal
    multiplied by that rate, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/order_settlement_shipping_on_discounted_subtotal
    """
    order = _tier1_magnum_order(api)
    assert order["provisional_subtotal_cents"] == 8000
    assert order["discount_cents"] == 800, f"expected 10% of 8000 = 800, got {order['discount_cents']}"


def test_shipping_evaluated_on_discounted_not_gross_subtotal(api):
    """PRD §3.3: "The `shipping_fee_cents` is then evaluated against that discounted subtotal:
    it is zero when the discounted subtotal is at least 7,500 cents (seventy-five dollars),
    and otherwise a flat 995 cents. The total is the discounted subtotal plus the shipping fee."

    Design: Difficulty/combinatorial_formula/order_settlement_shipping_on_discounted_subtotal
    """
    order = _tier1_magnum_order(api)
    # discounted_subtotal 7200 < 7500 -> flat 995 (gross 8000 would have been free-ship).
    assert order["shipping_fee_cents"] == 995, f"expected 995, got {order['shipping_fee_cents']}"
    assert order["provisional_total_cents"] == 8195, \
        f"expected 7200+995=8195, got {order['provisional_total_cents']}"


# ── Corner: calculations / refill_line_price_rounds_per_line ──

def test_refill_line_rounds_half_up_per_line(api):
    """PRD §3.3: "A `REFILL` line contributes its product's `price_per_ml_cents` multiplied by
    its `volume_ml`, rounded half up to a whole cent — each refill line rounded individually."

    Design: Corner/calculations/refill_line_price_rounds_per_line
    """
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                 reorder_point_ml=2000, harvest_date="2026-06-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 333)])
    assert order["provisional_subtotal_cents"] == 100, \
        f"expected round_half_up(99.9)=100, got {order['provisional_subtotal_cents']}"
    assert order["provisional_total_cents"] == 1095, \
        f"expected 100+995=1095, got {order['provisional_total_cents']}"


# ── Corner: calculations / fulfill_freshness_markdown_refunds_delta_to_wallet ──

def test_fulfill_markdown_refunds_delta_to_wallet(api):
    """PRD §3.5: "If the provisional total exceeded the final total, the difference is returned
    to the member as store credit — the member's `wallet_credit_cents` is increased by that
    difference and the order's `amount_refunded_cents` is increased by the same amount."

    Design: Corner/calculations/fulfill_freshness_markdown_refunds_delta_to_wallet
    """
    set_clock(api, "2026-06-29T00:00:00Z")
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                 reorder_point_ml=2000, harvest_date="2026-01-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 5000)])
    order = pay_order(api, member, order)
    set_clock(api, "2026-06-30T00:00:00Z")
    order = fulfill_order(api, order)
    assert order["final_total_cents"] == 2270
    member_data = validate_success(api.get_member(member["id"], make_customer_headers(member["id"])))
    assert member_data["wallet_credit_cents"] == 225, \
        f"expected 2495-2270=225 refunded to wallet, got {member_data['wallet_credit_cents']}"
