"""Pricing engine: provisional vs final payout, tiered commission floor, and the
pinned buyer-order-total rounding order (PRD §3.4, §3.6).
"""
import pytest

from test_helpers import (
    validate_success,
    make_seller_headers, make_buyer_headers,
    # fixtures
    setup_published_listing, setup_direct_sale, create_buyer, make_offer,
    get_sale_by_listing,
)


# --- dual_variant_calc: provisional (Listing) vs final (Sale) payout ---------
def test_provisional_payout_pinned_at_publish(api):
    """PRD §3.4: "It computes the `provisional_payout_cents` estimate as the
    `list_price_cents` minus the commission on that asking price, where the commission is
    `list_price_cents` multiplied by `commission_rate_locked_pct` and rounded half up to
    whole cents."

    Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_diverge_on_accepted_offer
    """
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    # STANDARD seller, base 0.20 -> rate 0.20; commission = round(200000*0.20)=40000.
    assert ctx["listing"]["provisional_payout_cents"] == 160000, ctx["listing"]["provisional_payout_cents"]


def test_final_payout_on_accepted_offer_diverges_from_provisional(api):
    """PRD §3.6: "The `commission_cents` is `sale_price_cents` multiplied by
    `commission_rate_pct`, rounded half up to whole cents. The `seller_net_payout_cents` —
    the seller's final payout basis — is `sale_price_cents` minus `commission_cents`."
    PRD §3.6: "Because an accepted offer usually settles below the asking price, this final
    payout can diverge from the earlier provisional estimate whenever the sale price
    differs from the list price."

    Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_diverge_on_accepted_offer
    """
    ctx = setup_published_listing(list_price_cents=200000, category="HANDBAGS")
    buyer = create_buyer()
    offer = make_offer(ctx["listing_id"], buyer["id"], 180000, ctx["listing_version"])
    validate_success(api.accept_offer(offer["id"], make_seller_headers(ctx["seller_id"])), 200)
    sale = get_sale_by_listing(ctx["listing_id"])
    assert sale["sale_price_cents"] == 180000, sale["sale_price_cents"]
    assert sale["commission_cents"] == 36000, sale["commission_cents"]
    assert sale["seller_net_payout_cents"] == 144000, sale["seller_net_payout_cents"]
    assert ctx["listing"]["provisional_payout_cents"] != sale["seller_net_payout_cents"], (
        "provisional (160000) must diverge from the final net (144000)")


# --- combinatorial_formula: tiered commission with max() floor ---------------
def test_commission_rate_floor_binds_below_minimum(api):
    """PRD §3.4: "start from the category's `base_commission_pct`, subtract the tier
    discount — zero for a `STANDARD` seller, three hundredths (`0.03`) for a `PREMIER`
    seller, five hundredths (`0.05`) for an `ELITE` seller — and take the greater of that
    discounted rate and the platform minimum commission floor of `0.05`; the locked rate
    is never allowed below that five-percent floor."
    PRD §3.6: "The `commission_rate_pct` is copied from the listing's locked
    `commission_rate_locked_pct`."

    Design: Difficulty/combinatorial_formula/commission_tiered_rate_max_floor_binds
    """
    ctx = setup_direct_sale(list_price_cents=300000, category="SHOES",
                            policy_overrides={"base_commission_pct": 0.04})
    sale = ctx["sale"]
    # STANDARD seller, base 0.04 -> max(0.04-0.0, 0.05) = 0.05 (floor lifts 0.04 to 0.05).
    assert sale["commission_rate_pct"] == pytest.approx(0.05, abs=1e-9), sale["commission_rate_pct"]


def test_commission_amount_uses_lifted_floor_rate(api):
    """PRD §3.6: "The `commission_cents` is `sale_price_cents` multiplied by
    `commission_rate_pct`, rounded half up to whole cents. The `seller_net_payout_cents` —
    the seller's final payout basis — is `sale_price_cents` minus `commission_cents`."

    Design: Difficulty/combinatorial_formula/commission_tiered_rate_max_floor_binds
    """
    ctx = setup_direct_sale(list_price_cents=300000, category="SHOES",
                            policy_overrides={"base_commission_pct": 0.04})
    sale = ctx["sale"]
    # commission = round(300000*0.05)=15000 (not the 12000 that base 0.04 would give).
    assert sale["commission_cents"] == 15000, sale["commission_cents"]
    assert sale["seller_net_payout_cents"] == 285000, sale["seller_net_payout_cents"]


# --- combinatorial_formula: pinned buyer-order-total rounding order ----------
def test_buyer_fee_rounded_before_tax(api):
    """PRD §3.6: "first the `buyer_fee_cents` is the category's `buyer_fee_flat_cents` plus
    (`sale_price_cents` multiplied by the category's `buyer_fee_pct`, rounded half up to
    whole cents);"

    Design: Difficulty/combinatorial_formula/buyer_order_total_pinned_rounding_order
    """
    ctx = setup_direct_sale(list_price_cents=123455, category="HANDBAGS")
    sale = ctx["sale"]
    # buyer_fee = 500 + round_half_up(123455*0.10) = 500 + round(12345.5)=12346 -> 12846.
    assert sale["buyer_fee_cents"] == 12846, sale["buyer_fee_cents"]


def test_tax_on_price_plus_rounded_fee_then_order_total(api):
    """PRD §3.6: "then the `tax_cents` is (`sale_price_cents` plus the already-rounded
    `buyer_fee_cents`) multiplied by the eight-percent sales tax fraction (`0.08`), rounded
    half up to whole cents — the tax is deliberately levied on the price plus the rounded
    fee, not on the price alone; and finally the `order_total_cents` is `sale_price_cents`
    plus `buyer_fee_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/buyer_order_total_pinned_rounding_order
    """
    ctx = setup_direct_sale(list_price_cents=123455, category="HANDBAGS")
    sale = ctx["sale"]
    # tax = round_half_up((123455+12846)*0.08) = round(10904.08) = 10904.
    # order_total = 123455 + 12846 + 10904 = 147205.
    assert sale["sale_price_cents"] == 123455, sale["sale_price_cents"]
    assert sale["tax_cents"] == 10904, sale["tax_cents"]
    assert sale["order_total_cents"] == 147205, sale["order_total_cents"]
