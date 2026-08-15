"""Quote pricing ladder: tiered discount-then-fee vs informational variants,
per-line rounding order, tier thresholds, CASH_CHECK settlement, capacity zone,
and the pricing snapshot copied to the order at acceptance (PRD §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_money_eq,
    create_config,
    create_customer,
    create_variety,
    factories,
    create_quote,
    get_success_data,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def _base_setup(api):
    pc = create_config(api)
    v = create_variety(api)
    return pc, v


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / order_total_tiered_ladder_vs_additive_flat
# 48 PREMIUM pallets full -> turf 4104.00; zones 12/24/12 -> freight 728.87;
# pre 4832.87 -> tier T1; discount 289.97; fee 90.86; ladder total 4633.76;
# additive-flat variant 5225.30.
# ---------------------------------------------------------------------------

def test_tiered_ladder_computes_discount_then_fee(api):
    """PRD §3.4: "For `CARD` settlement, the ladder then computes `volume_discount` as the `pre_discount_subtotal` multiplied by the tier's fraction — `volume_t1_pct` at six percent or `volume_t2_pct` at fifteen percent by default, zero for `T0` — rounded half-up to two decimals; then `card_fee` as the discounted gross multiplied by `card_fee_pct` (two percent by default), again rounded half-up to two decimals; and finally `total_price` as the discounted gross plus the card fee, rounded half-up to two decimals."
    PRD §3.4: "The volume tier is evaluated on **pre-discount** values, resolving the apparent circularity between tier and fee: the quote earns `T2` when `turf_sqft` is at least `volume_t2_turf_min` (8000 by default) and `pre_discount_subtotal` is at least `volume_t2_pre_min` (15000 by default); otherwise `T1` when `turf_sqft` is at least `volume_t1_turf_min` (2000 by default) and `pre_discount_subtotal` is at least `volume_t1_pre_min` (4000 by default); otherwise `T0`."

    Design: Difficulty/dual_variant_calc/order_total_tiered_ladder_vs_additive_flat
    """
    _pc, v = _base_setup(api)
    c = create_customer(api)
    q = create_quote(
        api, c["id"],
        [factories.quote_line(v["id"], "PREMIUM", 48)],
        12, 24, 12,
    )
    assert_money_eq(q["turf_sqft"], 4104.00, "turf_sqft")
    assert_money_eq(q["freight_amount"], 728.87, "freight_amount")
    assert_money_eq(q["pre_discount_subtotal"], 4832.87, "pre_discount_subtotal")
    assert q["volume_tier"] == "T1", f"expected T1, got {q['volume_tier']}"
    assert_money_eq(q["volume_discount"], 289.97, "volume_discount")
    assert_money_eq(q["card_fee"], 90.86, "card_fee")
    assert_money_eq(q["total_price"], 4633.76, "total_price")


def test_additive_flat_variant_diverges_from_ladder(api):
    """PRD §3.4: "Every quote, whatever its settlement, also exposes two informational dual variants that are never authoritative: `cash_price`, the flat cash-settlement figure just described, and `additive_total` — for `CARD`, the `pre_discount_subtotal` marked up multiplicatively by one plus the tier fraction and then by one plus the card fee fraction, rounded half-up to two decimals; for `CASH_CHECK`, identical to `cash_price`."
    PRD §3.4: "`additive_total` diverges from the ladder's `total_price` whenever the tier fraction is positive."

    Design: Difficulty/dual_variant_calc/order_total_tiered_ladder_vs_additive_flat
    """
    _pc, v = _base_setup(api)
    c = create_customer(api)
    q = create_quote(
        api, c["id"],
        [factories.quote_line(v["id"], "PREMIUM", 48)],
        12, 24, 12,
    )
    assert_money_eq(q["additive_total"], 5225.30, "additive_total")
    assert_money_eq(q["total_price"], 4633.76, "total_price")
    assert q["additive_total"] != pytest.approx(q["total_price"]), (
        "additive_total must diverge from total_price when the tier fraction is positive"
    )


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / pricing_ladder_multi_input_tier_branching
# 42 PREMIUM full -> turf 3591.00; zones 12/18/12 -> d 78.00; freight 560.20;
# pre 4151.20 -> T1 (tier reads PRE-discount values even though the discounted
# gross 3902.13 falls below 4000); discount 249.07; fee 78.04; total 3980.17;
# additive 4488.28.
# ---------------------------------------------------------------------------

def test_tier_evaluated_on_pre_discount_values(api):
    """PRD §3.4: "The volume tier is evaluated on **pre-discount** values, resolving the apparent circularity between tier and fee: the quote earns `T2` when `turf_sqft` is at least `volume_t2_turf_min` (8000 by default) and `pre_discount_subtotal` is at least `volume_t2_pre_min` (15000 by default); otherwise `T1` when `turf_sqft` is at least `volume_t1_turf_min` (2000 by default) and `pre_discount_subtotal` is at least `volume_t1_pre_min` (4000 by default); otherwise `T0`."
    PRD §3.4: "The `freight_amount` is `turf_sqft` multiplied by that factor, divided by the card's `freight_sqft_unit` (500 by default), rounded half-up to two decimal places — freight is rounded before it joins anything else."

    Design: Difficulty/combinatorial_formula/pricing_ladder_multi_input_tier_branching
    """
    _pc, v = _base_setup(api)
    c = create_customer(api)
    q = create_quote(
        api, c["id"],
        [factories.quote_line(v["id"], "PREMIUM", 42)],
        12, 18, 12,
    )
    assert_money_eq(q["turf_sqft"], 3591.00, "turf_sqft")
    assert_money_eq(q["freight_amount"], 560.20, "freight_amount")
    assert_money_eq(q["pre_discount_subtotal"], 4151.20, "pre_discount_subtotal")
    # Tier reads pre-discount values: the post-discount gross (3902.13) falling
    # below 4000 does not revoke T1.
    assert q["volume_tier"] == "T1", f"expected T1, got {q['volume_tier']}"
    assert_money_eq(q["volume_discount"], 249.07, "volume_discount")
    assert_money_eq(q["card_fee"], 78.04, "card_fee")
    assert_money_eq(q["total_price"], 3980.17, "total_price")


def test_multi_input_ladder_additive_variant(api):
    """PRD §3.4: "Every quote, whatever its settlement, also exposes two informational dual variants that are never authoritative: `cash_price`, the flat cash-settlement figure just described, and `additive_total` — for `CARD`, the `pre_discount_subtotal` marked up multiplicatively by one plus the tier fraction and then by one plus the card fee fraction, rounded half-up to two decimals; for `CASH_CHECK`, identical to `cash_price`."

    Design: Difficulty/combinatorial_formula/pricing_ladder_multi_input_tier_branching
    """
    _pc, v = _base_setup(api)
    c = create_customer(api)
    q = create_quote(
        api, c["id"],
        [factories.quote_line(v["id"], "PREMIUM", 42)],
        12, 18, 12,
    )
    assert_money_eq(q["additive_total"], 4488.28, "additive_total")
    assert_money_eq(q["total_price"], 3980.17, "total_price")


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / turf_contribution_per_line_rounding_order
# Lines 795 and 785 PREMIUM sqft: per-line round2 gives 679.73 + 671.18 =
# 1350.91; sum-then-round would give 1350.90.
# ---------------------------------------------------------------------------

def _rounding_order_quote(api):
    _pc, v = _base_setup(api)
    c = create_customer(api, full_name="Bo Lin", email="bo@example.com",
                        phone="555-0102", freight_zone=1, address="4 Pine Ave")
    q = create_quote(
        api, c["id"],
        [
            factories.quote_line(v["id"], "PREMIUM", 8, shortfall_slabs=1),
            factories.quote_line(v["id"], "PREMIUM", 8, shortfall_slabs=3),
        ],
        8, 8, 0,
        delivery_date="2026-08-02",
    )
    return q


def test_turf_per_line_rounding_then_sum(api):
    """PRD §3.4: "The turf component `turf_sqft` then prices each line at its grade's per-square-foot rate — `rate_premium`, `rate_standard`, or `rate_economy` (0.855, 0.70, and 0.50 by default) — with each line's contribution rounded half-up to two decimal places **before** the contributions are summed."
    PRD §3.4: "The round-per-line-then-sum order is authoritative; summing first and rounding once produces a different number and is not compliant."

    Design: Difficulty/combinatorial_formula/turf_contribution_per_line_rounding_order
    """
    q = _rounding_order_quote(api)
    # 795 * 0.855 = 679.725 -> 679.73; 785 * 0.855 = 671.175 -> 671.18.
    assert_money_eq(q["turf_sqft"], 1350.91, "turf_sqft")


def test_rounding_order_propagates_to_total(api):
    """PRD §3.4: "The round-per-line-then-sum order is authoritative; summing first and rounding once produces a different number and is not compliant."
    PRD §3.4: "The `pre_discount_subtotal` is then simply `turf_sqft` plus `freight_amount`."

    Design: Difficulty/combinatorial_formula/turf_contribution_per_line_rounding_order
    """
    q = _rounding_order_quote(api)
    assert_money_eq(q["freight_amount"], 64.84, "freight_amount")
    assert_money_eq(q["pre_discount_subtotal"], 1415.75, "pre_discount_subtotal")
    assert q["volume_tier"] == "T0", f"expected T0, got {q['volume_tier']}"
    assert_money_eq(q["card_fee"], 28.32, "card_fee")
    assert_money_eq(q["total_price"], 1444.07, "total_price")


# ---------------------------------------------------------------------------
# Corner: calculations / volume_tier_requires_both_thresholds
# turf exactly 2000.00 but pre 2156.00 -> stays T0 (AND, not OR).
# ---------------------------------------------------------------------------

def test_volume_tier_requires_both_thresholds(api):
    """PRD §3.4: "The volume tier is evaluated on **pre-discount** values, resolving the apparent circularity between tier and fee: the quote earns `T2` when `turf_sqft` is at least `volume_t2_turf_min` (8000 by default) and `pre_discount_subtotal` is at least `volume_t2_pre_min` (15000 by default); otherwise `T1` when `turf_sqft` is at least `volume_t1_turf_min` (2000 by default) and `pre_discount_subtotal` is at least `volume_t1_pre_min` (4000 by default); otherwise `T0`."

    Design: Corner/calculations/volume_tier_requires_both_thresholds
    """
    _pc, v = _base_setup(api)
    c = create_customer(api)
    q = create_quote(
        api, c["id"],
        [
            factories.quote_line(v["id"], "PREMIUM", 22),
            factories.quote_line(v["id"], "STANDARD", 4, shortfall_rolls=3),
        ],
        13, 13, 0,
    )
    assert_money_eq(q["turf_sqft"], 2000.00, "turf_sqft")
    assert_money_eq(q["pre_discount_subtotal"], 2156.00, "pre_discount_subtotal")
    assert q["volume_tier"] == "T0", (
        f"turf threshold met but pre-discount subtotal below 4000 must stay T0, "
        f"got {q['volume_tier']}"
    )
    assert_money_eq(q["volume_discount"], 0.00, "volume_discount")
    assert_money_eq(q["total_price"], 2199.12, "total_price")


# ---------------------------------------------------------------------------
# Corner: calculations / cash_check_settlement_flat_discount_variant
# Same spec, two settlements: CARD total 938.20 with cash_price 892.21
# exposed; CASH_CHECK authoritative total 892.21, discount and fee 0.00.
# ---------------------------------------------------------------------------

def test_cash_check_flat_discount_replaces_tier_and_fee(api):
    """PRD §3.4: "For `CASH_CHECK` settlement the tier discount and card fee do not apply: `volume_discount` and `card_fee` are both 0.00, and `total_price` equals `cash_price` — the `pre_discount_subtotal` reduced by the `cash_discount_pct` fraction (three percent by default), rounded half-up to two decimals."
    PRD §3.4: "Every quote, whatever its settlement, also exposes two informational dual variants that are never authoritative: `cash_price`, the flat cash-settlement figure just described, and `additive_total` — for `CARD`, the `pre_discount_subtotal` marked up multiplicatively by one plus the tier fraction and then by one plus the card fee fraction, rounded half-up to two decimals; for `CASH_CHECK`, identical to `cash_price`."

    Design: Corner/calculations/cash_check_settlement_flat_discount_variant
    """
    _pc, v = _base_setup(api)
    c1 = create_customer(api)
    c2 = create_customer(api, full_name="Bo Lin", email="bo@example.com",
                         phone="555-0102", freight_zone=2, address="4 Pine Ave")
    lines = [
        factories.quote_line(v["id"], "PREMIUM", 8, shortfall_slabs=1),
        factories.quote_line(v["id"], "STANDARD", 6, shortfall_rolls=1),
    ]
    q_card = create_quote(api, c1["id"], lines, 7, 7, 0)
    q_cash = create_quote(api, c2["id"], lines, 7, 7, 0,
                          settlement_method="CASH_CHECK")

    # CARD quote: turf 882.73, freight 37.07, pre 919.80, fee 18.40, total 938.20.
    assert_money_eq(q_card["turf_sqft"], 882.73, "card turf_sqft")
    assert_money_eq(q_card["freight_amount"], 37.07, "card freight_amount")
    assert_money_eq(q_card["pre_discount_subtotal"], 919.80, "card pre")
    assert_money_eq(q_card["card_fee"], 18.40, "card card_fee")
    assert_money_eq(q_card["total_price"], 938.20, "card total_price")
    assert_money_eq(q_card["cash_price"], 892.21, "card cash_price (informational)")

    # CASH_CHECK quote: no tier, no fee; total equals the cash price.
    assert_money_eq(q_cash["volume_discount"], 0.00, "cash volume_discount")
    assert_money_eq(q_cash["card_fee"], 0.00, "cash card_fee")
    assert q_cash["volume_tier"] == "T0"
    assert_money_eq(q_cash["total_price"], 892.21, "cash total_price")
    assert_money_eq(q_cash["cash_price"], 892.21, "cash cash_price")


# ---------------------------------------------------------------------------
# Corner: calculations / capacity_zone_argmax_tiebreak_lowest_wins
# ---------------------------------------------------------------------------

def test_capacity_zone_argmax_ties_break_to_lowest_zone(api):
    """PRD §3.4: "The quote's `capacity_zone`, the zone whose trucks the booking will draw on, is whichever of the three zone counts is largest, ties breaking to the lowest zone number."

    Design: Corner/calculations/capacity_zone_argmax_tiebreak_lowest_wins
    """
    _pc, v = _base_setup(api)
    c1 = create_customer(api)
    c2 = create_customer(api, full_name="Bo Lin", email="bo@example.com",
                         phone="555-0102", freight_zone=2, address="4 Pine Ave")
    q1 = create_quote(api, c1["id"],
                      [factories.quote_line(v["id"], "PREMIUM", 16)], 8, 8, 0)
    q2 = create_quote(api, c2["id"],
                      [factories.quote_line(v["id"], "PREMIUM", 16)], 5, 5, 6)
    assert q1["capacity_zone"] == 1, (
        f"tie 8/8 must break to the lowest zone, got {q1['capacity_zone']}"
    )
    assert q2["capacity_zone"] == 3, (
        f"5/5/6 argmax must pick zone 3, got {q2['capacity_zone']}"
    )


# ---------------------------------------------------------------------------
# Corner: endpoints / accept_creates_order_with_copied_pricing
# 10 PREMIUM full, zones 0/10/0: turf 855.00, freight 30.78, pre 885.78,
# fee 17.72, total 903.50; order PLACED/PENDING; chargeable == total.
# ---------------------------------------------------------------------------

def test_accept_creates_order_with_copied_pricing(api):
    """PRD §3.4: "A successful acceptance creates the order: status `PLACED`, `payment_status` `PENDING`, `crew_referral_status` `NONE`, `chargeable_amount` equal to `total_price`."
    PRD §3.4: "The order records the `quote_id` (at most one order ever exists per quote), copies `customer_id`, `price_config_id`, `delivery_date`, `settlement_method`, `capacity_zone`, `turf_sqft`, `freight_amount`, `pre_discount_subtotal`, `volume_tier`, `volume_discount`, `card_fee`, `total_price`, and `total_pallets` from the quote, and takes `freight_zone` from the customer record."

    Design: Corner/endpoints/accept_creates_order_with_copied_pricing
    """
    _pc, v = _base_setup(api)
    c = create_customer(api)
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 10)], 0, 10, 0)
    resp = api.accept_quote(q["id"], SALES)
    o = validate_success(resp, 201)
    assert o["status"] == "PLACED"
    assert o["payment_status"] == "PENDING"
    assert o["crew_referral_status"] == "NONE"
    assert o["quote_id"] == q["id"]
    assert o["customer_id"] == c["id"]
    assert o["price_config_id"] == q["price_config_id"]
    assert o["freight_zone"] == 2  # copied from the customer record
    assert_money_eq(o["turf_sqft"], 855.00, "order turf_sqft")
    assert_money_eq(o["freight_amount"], 30.78, "order freight_amount")
    assert_money_eq(o["pre_discount_subtotal"], 885.78, "order pre_discount_subtotal")
    assert_money_eq(o["card_fee"], 17.72, "order card_fee")
    assert_money_eq(o["total_price"], 903.50, "order total_price")
    assert_money_eq(o["chargeable_amount"], 903.50, "chargeable_amount == total_price")
    assert_money_eq(o["amount_due"], 903.50, "amount_due")
    assert_money_eq(o["total_paid"], 0.00, "total_paid")


# ---------------------------------------------------------------------------
# Corner: entities / price_config_defaults_applied_on_omission
# ---------------------------------------------------------------------------

def test_price_config_defaults_applied_on_omission(api):
    """PRD §3.1: "Only the card's `name` is required at creation; every other setting — pallet coverage, turf rates, freight parameters, window and cutoff hours, freshness limit, settlement fractions, tier thresholds, harvest hours — falls back to the defaults documented where each is used (§3.3 through §3.5) when omitted from the creation payload."
    PRD §2.7: "Exactly one rate card is current at any moment: the most recently created card has `is_current` set to true, and creating a new card flips `is_current` to false on every other card."

    Design: Corner/entities/price_config_defaults_applied_on_omission
    """
    resp = api.create_price_config({"name": "Std 2026"}, FARM)
    pc = validate_success(resp, 201)
    assert pc["slab_sqft"] == 5
    assert pc["roll_sqft"] == 10
    assert_money_eq(pc["rate_premium"], 0.855, "rate_premium")
    assert pc["zone_truck_capacity"] == 4
    assert_money_eq(pc["freshness_limit_hours"], 24, "freshness_limit_hours")
    assert pc["is_current"] is True
