"""Pricing calculations: PERCENT_OFF per-line rounding, BOGO cheapest-free,
THRESHOLD tier selection, the stacking ceiling, auto-apply selection, and
budget-headroom rejection.

Translates queue A (Difficulty): dual_variant_calc (percent rounding),
combinatorial_formula (percent rounding + stacking ceiling), boundary_precision
(threshold inclusive boundary). Translates queue B (Corner): calculations (BOGO,
threshold below/highest, auto-apply select/tie-break, stacking uncapped, budget
would-exceed) and consistency (immediate discount visibility).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock,
    create_customer,
    create_active_promotion,
    create_promotion,
    activate_promotion,
    setup_cart_with_lines,
    setup_priced_cart_with_coupon,
    create_cart_for,
    add_line,
    apply,
    reprice,
    get_promotion,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_shopper_headers

ADMIN = TEST_USERS["merchant_admin_headers"]


# ───────── dual_variant_calc / combinatorial_formula: percent rounding ──────
def test_percent_off_rounds_per_line_then_sums(api):
    """PRD §3.6: "walking the lines in ascending `created_at` order, the engine
    multiplies each line's total by the promotion's `percent_off`, rounds that
    line's result half up to whole cents first, and only then sums those rounded
    per-line amounts into the application's `raw_discount_cents`. The per-line
    rounding precedes the summation deliberately — two lines of 1005 and 2005
    cents at ten percent yield 101 and 201 cents for a raw discount of 302 cents,
    not the 301 cents that rounding a single combined product would give."

    Design: Difficulty/dual_variant_calc/dvc_percent_rounding_order_diverges
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="DVC1")
    create_active_promotion("PERCENT_OFF", name="P-pct10", percent_off=0.10,
                            coupon_code="ROUND10", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, app = setup_priced_cart_with_coupon(cust["id"], "ROUND10",
                                              [("S1", 1005, 1), ("S2", 2005, 1)])
    assert cart["subtotal_cents"] == 3010
    assert cart["total_discount_cents"] == 302
    assert cart["total_cents"] == 2708


def test_percent_off_three_lines_rounds_each_before_sum(api):
    """PRD §3.6: "the engine multiplies each line's total by the promotion's
    `percent_off`, rounds that line's result half up to whole cents first, and
    only then sums those rounded per-line amounts into the application's
    `raw_discount_cents`."

    Design: Difficulty/dual_variant_calc/dvc_percent_rounding_order_diverges
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="DVC1b")
    create_active_promotion("PERCENT_OFF", name="P-pct10b", percent_off=0.10,
                            coupon_code="ROUND10B", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    # Three lines each ending .5 cents at 10%: 105->round(10.5)=11 each; per-line sum 33.
    # Sum-then-round would give round(315*0.10)=round(31.5)=32. Per-line-then-sum yields 33.
    cart, _ = setup_priced_cart_with_coupon(cust["id"], "ROUND10B",
                                            [("S1", 105, 1), ("S2", 105, 1), ("S3", 105, 1)])
    assert cart["subtotal_cents"] == 315
    assert cart["total_discount_cents"] == 33
    assert cart["total_cents"] == 282


def test_percent_off_per_line_rounding_mode_b(api):
    """PRD §3.6: "the engine multiplies each line's total by the promotion's
    `percent_off`, rounds that line's result half up to whole cents first, and
    only then sums those rounded per-line amounts into the application's
    `raw_discount_cents`. The per-line rounding precedes the summation
    deliberately — two lines of 1005 and 2005 cents at ten percent yield 101 and
    201 cents for a raw discount of 302 cents, not the 301 cents that rounding a
    single combined product would give."

    Design: Difficulty/combinatorial_formula/cf_percent_per_line_rounding_mode_b
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CFB")
    create_active_promotion("PERCENT_OFF", name="PCT10", percent_off=0.10,
                            coupon_code="PCT10", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_priced_cart_with_coupon(cust["id"], "PCT10",
                                            [("S1", 1005, 1), ("S2", 2005, 1)])
    assert cart["total_discount_cents"] == 302
    assert cart["total_cents"] == 2708


def test_percent_off_quantity_line_rounds_before_sum(api):
    """PRD §3.6: "two lines of 1005 and 2005 cents at ten percent yield 101 and
    201 cents for a raw discount of 302 cents, not the 301 cents that rounding a
    single combined product would give."

    Design: Difficulty/combinatorial_formula/cf_percent_per_line_rounding_mode_b
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CFB2")
    create_active_promotion("PERCENT_OFF", name="PCT10b", percent_off=0.10,
                            coupon_code="PCT10B", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    # Two lines: 1005 (101) and 2005 (201) -> per-line sum 302; sum-then-round 301.
    cart, _ = setup_priced_cart_with_coupon(cust["id"], "PCT10B",
                                            [("S1", 1005, 1), ("S2", 2005, 1)])
    assert cart["subtotal_cents"] == 3010
    assert cart["total_discount_cents"] == 302


# ───────── combinatorial_formula: stacking ceiling waterfall (mode c) ───────
def test_stacking_ceiling_capped_waterfall_by_created_at(api):
    """PRD §3.7: "If the sum exceeds the ceiling, the total is clamped to the
    ceiling and distributed in a waterfall: the applications are taken in
    ascending `created_at` order of their promotions, and each receives the
    smaller of its own `raw_discount_cents` and whatever ceiling remains, with
    the remaining ceiling reduced by that grant as the waterfall proceeds"
    PRD §3.7: "the ceiling fraction is the smallest `max_stacked_discount_pct`
    among the applied applications' promotions, ignoring any that are null"

    Design: Difficulty/combinatorial_formula/cf_stacking_ceiling_circular_mode_c
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CFC")
    # P1 created first: PERCENT_OFF 30%, ceiling 0.50; coupon P1C.
    create_active_promotion("PERCENT_OFF", name="P1pct30", percent_off=0.30,
                            max_stacked_discount_pct=0.50,
                            coupon_code="P1C", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    # P2 created second: THRESHOLD {min 3000 -> 1500}; coupon P2C.
    create_active_promotion("THRESHOLD", name="P2thr",
                            threshold_tiers=[{"min_subtotal_cents": 3000, "discount_cents": 1500}],
                            coupon_code="P2C", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 4000, 1)])
    app1 = apply(cart["id"], cust["id"], "P1C")
    app2 = apply(cart["id"], cust["id"], "P2C")
    cart = reprice(cart["id"], cust["id"])

    assert cart["subtotal_cents"] == 4000
    # raw: P1 = 1200, P2 = 1500, sum 2700 > ceiling round(4000*0.5)=2000.
    # waterfall created_at ASC: P1 gets min(1200,2000)=1200; P2 gets min(1500,800)=800.
    assert cart["total_discount_cents"] == 2000
    assert cart["total_cents"] == 2000

    apps = get_success_data(api_client.list_applications(cart["id"], make_shopper_headers(cust["id"])))
    by_id = {a["id"]: a for a in apps}
    assert by_id[app1["id"]]["discount_cents"] == 1200
    assert by_id[app2["id"]]["discount_cents"] == 800


def test_stacking_ceiling_clamps_total_to_subtotal_fraction(api):
    """PRD §3.7: "the ceiling fraction is the smallest `max_stacked_discount_pct`
    among the applied applications' promotions, ignoring any that are null"
    PRD §3.7: "If the sum exceeds the ceiling, the total is clamped to the ceiling
    and distributed in a waterfall: the applications are taken in ascending
    `created_at` order of their promotions, and each receives the smaller of its
    own `raw_discount_cents` and whatever ceiling remains, with the remaining
    ceiling reduced by that grant as the waterfall proceeds"

    Design: Difficulty/combinatorial_formula/cf_stacking_ceiling_circular_mode_c
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CFC2")
    # P1 created first: PERCENT_OFF 50% (raw 2000 on 4000c) ceiling 0.25 -> ceiling 1000.
    create_active_promotion("PERCENT_OFF", name="P1pct50", percent_off=0.50,
                            max_stacked_discount_pct=0.25,
                            coupon_code="P1C2", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    # P2 created second: THRESHOLD {min 0 -> 500}, no ceiling of its own.
    create_active_promotion("THRESHOLD", name="P2thr2",
                            threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 500}],
                            coupon_code="P2C2", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 4000, 1)])
    apply(cart["id"], cust["id"], "P1C2")
    apply(cart["id"], cust["id"], "P2C2")
    cart = reprice(cart["id"], cust["id"])
    # sum_raw 2000+500=2500 > ceiling round(4000*0.25)=1000 -> total clamped to 1000.
    assert cart["total_discount_cents"] == 1000
    assert cart["total_cents"] == 3000


def test_stacking_uncapped_when_below_ceiling(api):
    """PRD §3.7: "If that sum is at most the ceiling, each application's
    `discount_cents` simply equals its own `raw_discount_cents`."

    Design: Corner/calculations/stacking_uncapped_when_below_ceiling
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CA6")
    create_active_promotion("PERCENT_OFF", name="UC1", percent_off=0.10,
                            max_stacked_discount_pct=0.50,
                            coupon_code="UC1K", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    create_active_promotion("THRESHOLD", name="UC2",
                            threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 100}],
                            coupon_code="UC2K", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 4000, 1)])
    apply(cart["id"], cust["id"], "UC1K")  # raw 400
    apply(cart["id"], cust["id"], "UC2K")  # raw 100
    cart = reprice(cart["id"], cust["id"])
    # sum_raw 500 <= ceiling round(4000*0.5)=2000 -> uncapped.
    assert cart["total_discount_cents"] == 500


# ──────────────────────────── BOGO cheapest-free ───────────────────────────
def test_bogo_cheapest_units_are_free(api):
    """PRD §3.6: "the engine totals the matching quantity across those lines,
    takes the floor of half that quantity to find how many units are free (every
    second unit), then expands each matching line into one price per unit it
    holds, sorts all those unit prices ascending with ties broken by the line's
    `created_at` ascending, and sums the cheapest free-count of them as the
    `raw_discount_cents` — the cheapest units are the free ones, never the most
    expensive."

    Design: Corner/calculations/bogo_cheapest_unit_free
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CA1")
    create_active_promotion("BOGO", name="BG", bogo_sku="B",
                            coupon_code="BGK", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("B", 1799, 3), ("B", 999, 1)])
    apply(cart["id"], cust["id"], "BGK")
    cart = reprice(cart["id"], cust["id"])
    # qty 4 -> 2 free, cheapest units 999 + 1799 = 2798.
    assert cart["subtotal_cents"] == 6396
    assert cart["total_discount_cents"] == 2798
    assert cart["total_cents"] == 3598


# ─────── boundary_precision + corner: THRESHOLD tier selection ──────────────
def test_threshold_subtotal_inclusive_boundary(api):
    """PRD §3.6: "the engine compares the cart `subtotal_cents` against the tiers
    and selects the single highest tier whose `min_subtotal_cents` is less than
    or equal to the subtotal; the reward is that tier's flat `discount_cents`"
    PRD §3.6: "The boundary is inclusive — a subtotal exactly equal to a tier's
    `min_subtotal_cents` qualifies for that tier, while a subtotal one cent below
    it does not."

    Design: Difficulty/boundary_precision_check/bpc_threshold_subtotal_inclusive_boundary
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="B1")
    create_active_promotion("THRESHOLD", name="THR5K",
                            threshold_tiers=[{"min_subtotal_cents": 5000, "discount_cents": 1000}],
                            coupon_code="THR5K", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_priced_cart_with_coupon(cust["id"], "THR5K", [("A", 5000, 1)])
    assert cart["subtotal_cents"] == 5000
    assert cart["total_discount_cents"] == 1000


def test_threshold_below_min_no_discount(api):
    """PRD §3.6: "if no tier's floor is met the raw discount is zero. The boundary
    is inclusive — a subtotal exactly equal to a tier's `min_subtotal_cents`
    qualifies for that tier, while a subtotal one cent below it does not."

    Design: Corner/calculations/threshold_below_min_no_discount
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CA2")
    create_active_promotion("THRESHOLD", name="THlo",
                            threshold_tiers=[{"min_subtotal_cents": 5000, "discount_cents": 1000}],
                            coupon_code="THK", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_priced_cart_with_coupon(cust["id"], "THK", [("A", 4999, 1)])
    assert cart["subtotal_cents"] == 4999
    assert cart["total_discount_cents"] == 0


def test_threshold_one_cent_below_min_no_discount(api):
    """PRD §3.6: "The boundary is inclusive — a subtotal exactly equal to a
    tier's `min_subtotal_cents` qualifies for that tier, while a subtotal one
    cent below it does not."

    Design: Difficulty/boundary_precision_check/bpc_threshold_subtotal_inclusive_boundary
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="B1lo")
    create_active_promotion("THRESHOLD", name="THR5Klo",
                            threshold_tiers=[{"min_subtotal_cents": 5000, "discount_cents": 1000}],
                            coupon_code="THR5KLO", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_priced_cart_with_coupon(cust["id"], "THR5KLO", [("A", 4999, 1)])
    assert cart["subtotal_cents"] == 4999
    assert cart["total_discount_cents"] == 0, "subtotal == min-1 does not qualify"


def test_threshold_selects_highest_qualifying_tier(api):
    """PRD §3.6: "the engine compares the cart `subtotal_cents` against the tiers
    and selects the single highest tier whose `min_subtotal_cents` is less than
    or equal to the subtotal; the reward is that tier's flat `discount_cents`"

    Design: Corner/calculations/threshold_highest_tier_selected
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CA3")
    create_active_promotion("THRESHOLD", name="THhi",
                            threshold_tiers=[{"min_subtotal_cents": 5000, "discount_cents": 1000},
                                             {"min_subtotal_cents": 10000, "discount_cents": 2500}],
                            coupon_code="THK2", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_priced_cart_with_coupon(cust["id"], "THK2", [("A", 10000, 1)])
    assert cart["total_discount_cents"] == 2500


# ─────────────────────────────── auto-apply ────────────────────────────────
def test_auto_apply_selects_highest_raw_discount(api):
    """PRD §3.9: "Among the candidates, the engine ranks first by the
    `raw_discount_cents` each would produce on this very cart, highest first,
    breaking ties by the promotion's `created_at` ascending so the earliest-created
    wins."

    Design: Corner/calculations/auto_apply_selects_highest_discount
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CA4")
    # P_pct (no coupon) raw 500 on 5000c; P_thr (no coupon) raw 1000.
    p_pct = create_promotion("PERCENT_OFF", name="AApct", percent_off=0.10, eligibility_mode="ALL")
    activate_promotion(p_pct["id"])
    p_thr = create_promotion("THRESHOLD", name="AAthr",
                             threshold_tiers=[{"min_subtotal_cents": 5000, "discount_cents": 1000}],
                             eligibility_mode="ALL")
    activate_promotion(p_thr["id"])
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 5000, 1)])

    res = api.auto_apply(cart["id"], make_shopper_headers(cust["id"]))
    app = validate_success(res, 201)
    assert app["source"] == "AUTO_APPLY"
    assert app["promotion_id"] == p_thr["id"]


def test_auto_apply_tie_break_earliest_created(api):
    """PRD §3.9: "breaking ties by the promotion's `created_at` ascending so the
    earliest-created wins."

    Design: Corner/calculations/auto_apply_tie_break_earliest_created
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CA5")
    p_first = create_promotion("PERCENT_OFF", name="TieFirst", percent_off=0.10, eligibility_mode="ALL")
    activate_promotion(p_first["id"])
    p_second = create_promotion("PERCENT_OFF", name="TieSecond", percent_off=0.10, eligibility_mode="ALL")
    activate_promotion(p_second["id"])
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 5000, 1)])

    res = api.auto_apply(cart["id"], make_shopper_headers(cust["id"]))
    app = validate_success(res, 201)
    assert app["promotion_id"] == p_first["id"], "earliest created_at wins the tie"


# ─────────────────── budget would-exceed (pre-commit) ──────────────────────
def test_budget_would_exceed_on_apply(api):
    """PRD §3.8: "If the committed total plus that prospective discount would
    exceed `budget_cap_cents`, the application is refused with
    `ERR_PROMO_BUDGET_WOULD_EXCEED` — a pre-commit rejection distinct from
    `ERR_PROMO_BUDGET_EXHAUSTED`, which fires only when the budget has already
    been fully spent."

    Design: Corner/calculations/budget_would_exceed_on_apply
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CA7")
    promo, _ = create_active_promotion("THRESHOLD", name="BWE",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                       budget_cap_cents=500,
                                       coupon_code="BWEK", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 5000, 1)])
    promo_ver = get_promotion(promo["id"])["version"]
    res = api.apply_coupon(cart["id"], {"code": "BWEK", "expected_promotion_version": promo_ver},
                           make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_BUDGET_WOULD_EXCEED", expected_status=409)


# ─────────────────── consistency: immediate discount visibility ────────────
def test_discount_visible_immediately_in_reprice_response(api):
    """PRD §3.6: "A reprice first recomputes `subtotal_cents` as the sum over
    every line of its `unit_price_cents` multiplied by its `quantity`. It then
    computes a `raw_discount_cents` for each `APPLIED` application according to
    that application's promotion type. It then enforces the stacking ceiling
    across the cart to set each application's final `discount_cents` and the
    cart's `total_discount_cents`."

    Design: Corner/consistency_model/immediate_visibility_of_discount_after_reprice
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CM1")
    create_active_promotion("PERCENT_OFF", name="IM", percent_off=0.10,
                            coupon_code="IMK", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "IMK")
    res = api.reprice(cart["id"], make_shopper_headers(cust["id"]))
    repriced = validate_success(res, 200)
    assert repriced["total_discount_cents"] == 200
