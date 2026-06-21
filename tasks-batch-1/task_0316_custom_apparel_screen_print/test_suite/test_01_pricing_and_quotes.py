"""Pricing-engine tests: quantity-tier run pricing, per-method branches, the
ESTIMATE-vs-FINAL dual variant, the reorder setup waiver, and the rush window.

Every test below derives from one design-index instance (tag on the last docstring line).
"""
import pytest
from test_helpers import (
    validate_success,
    setup_shop_catalog,
    setup_confirmed_order,
    setup_invoiced_order,
    setup_fulfilled_order,
    get_quote,
    get_order,
    api_client,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# combinatorial_formula — mode (a): tier × colors × locations
# ═══════════════════════════════════════════════════════════════════════════

def test_screenprint_decoration_subtotal_tier_color_location(api):
    """PRD §3.5: "For a `SCREEN_PRINT` line, the per-unit-per-location run cost is
    that tier rate plus the method's `extra_color_run_cents` multiplied by one fewer
    than `num_colors` — the first ink color is included in the tier rate and each
    additional color adds the uplift."
    PRD §3.5: "72 through 143 units at 400 cents".

    Design: Difficulty/combinatorial_formula/decoration_run_cost_tier_color_location_mode_a
    """
    cat = setup_shop_catalog(method_overrides={"extra_color_run_cents": 75})
    parts = setup_confirmed_order(
        cat, size_run={"L": 72}, line_overrides={"num_locations": 2, "num_colors": 3}
    )
    quote = get_quote(parts["order"]["id"])
    # tier_rate(72)=400; (3-1)*75=150; per-unit-per-location=550; *2 loc=1100; *72=79200
    assert quote["decoration_subtotal_cents"] == 79200


def test_screenprint_setup_subtotal_colors_times_locations(api):
    """PRD §3.6: "For a `SCREEN_PRINT` line the setup is `num_colors` times
    `num_locations` times the method's `screen_fee_cents` — one screen per ink color
    per location."

    Design: Difficulty/combinatorial_formula/decoration_run_cost_tier_color_location_mode_a
    """
    cat = setup_shop_catalog(method_overrides={"extra_color_run_cents": 75})
    parts = setup_confirmed_order(
        cat, size_run={"L": 72}, line_overrides={"num_locations": 2, "num_colors": 3}
    )
    quote = get_quote(parts["order"]["id"])
    # num_colors 3 * num_locations 2 * screen_fee 2500 = 15000
    assert quote["setup_subtotal_cents"] == 15000


# ═══════════════════════════════════════════════════════════════════════════
# combinatorial_formula — mode (b): round per line, then sum
# ═══════════════════════════════════════════════════════════════════════════

def test_decoration_subtotal_round_per_line_then_sum(api):
    """PRD §3.4: "the order is "round per line, then sum," never "sum fractional then
    round once.""
    PRD §3.5: "24 through 71 units at 550 cents".

    Design: Difficulty/combinatorial_formula/decoration_subtotal_round_per_line_then_sum_mode_b
    """
    cat = setup_shop_catalog(
        method_overrides={"extra_color_run_cents": 75},
        stock_qty=300,
    )
    parts = setup_order_two_lines(cat)
    quote = get_quote(parts["order"]["id"])
    # line A {L:30} 1 color/1 loc: rate 550, 550*30=16500
    # line B {L:50} 2 color/1 loc: (550+75)=625, 625*50=31250
    assert quote["decoration_subtotal_cents"] == 47750


def test_setup_subtotal_summed_per_line(api):
    """PRD §3.6: "The setup subtotal is the sum of these per-line setups."
    PRD §3.6: "For a `SCREEN_PRINT` line the setup is `num_colors` times
    `num_locations` times the method's `screen_fee_cents`".

    Design: Difficulty/combinatorial_formula/decoration_subtotal_round_per_line_then_sum_mode_b
    """
    cat = setup_shop_catalog(
        method_overrides={"extra_color_run_cents": 75},
        stock_qty=300,
    )
    parts = setup_order_two_lines(cat)
    quote = get_quote(parts["order"]["id"])
    # line A 1*1*2500=2500 + line B 2*1*2500=5000 = 7500
    assert quote["setup_subtotal_cents"] == 7500


def setup_order_two_lines(cat):
    """Two-line confirmed order used by mode-(b) tests. Built from PRD endpoints."""
    from test_helpers import (
        create_draft_order, add_line, create_proof, submit_proof, approve_proof,
    )
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    order_v = order["version"]
    add_line(order["id"], cat["style"]["id"], cat["method"]["id"], {"L": 30},
             num_locations=1, num_colors=1)
    add_line(order["id"], cat["style"]["id"], cat["method"]["id"], {"L": 50},
             num_locations=1, num_colors=2)
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    approve_proof(order["id"], proof["id"], cat["customer"]["id"], order_v)
    confirmed = validate_success(api_client.confirm_order(order["id"], SM), 200)
    return {"order": confirmed}


# ═══════════════════════════════════════════════════════════════════════════
# dual_variant_calc — ESTIMATE vs FINAL on the Order domain
# ═══════════════════════════════════════════════════════════════════════════

def test_estimate_grand_total_on_ordered_quantities(api):
    """PRD §3.4: "Finally `grand_total_cents` is the sum of `blank_subtotal_cents`,
    `setup_subtotal_cents`, `decoration_subtotal_cents`, and `rush_surcharge_cents`."
    PRD §3.4: "The `blank_subtotal_cents` is the sum across lines of the style's
    `blank_cost_cents` times that line's `line_qty`."

    Design: Difficulty/dual_variant_calc/order_price_estimate_vs_final_on_order_domain
    """
    cat = setup_shop_catalog(
        clock="2026-06-01T00:00:00.000Z",
        method_overrides={"screen_fee_cents": 2500, "extra_color_run_cents": 75},
        style_overrides={"blank_cost_cents": 350},
    )
    parts = setup_invoiced_order(
        cat, size_run={"L": 72}, good_units=72, spoiled_units=2,
        line_overrides={"num_locations": 2, "num_colors": 3},
        order_overrides={"requested_ship_date": "2026-06-20T00:00:00.000Z"},
    )
    quote = get_quote(parts["order"]["id"])
    # blank 350*72=25200 + setup 15000 + decoration 79200 + rush 0 = 119400
    assert quote["grand_total_cents"] == 119400


def test_final_total_bills_consumed_blanks_not_reserved(api):
    """PRD §3.9: "Where the ESTIMATE priced the blank subtotal on the reserved units,
    the FINAL bills the blank subtotal on the units actually consumed — `good_units`
    plus `spoiled_units`, capped at each reservation's `reserved_qty` — times each
    style's `blank_cost_cents`."
    PRD §3.9: "The decoration subtotal and the setup subtotal are carried over
    unchanged from the estimate".

    Design: Difficulty/dual_variant_calc/order_price_estimate_vs_final_on_order_domain
    """
    cat = setup_shop_catalog(
        clock="2026-06-01T00:00:00.000Z",
        method_overrides={"screen_fee_cents": 2500, "extra_color_run_cents": 75},
        style_overrides={"blank_cost_cents": 350},
    )
    parts = setup_invoiced_order(
        cat, size_run={"L": 72}, good_units=72, spoiled_units=2,
        line_overrides={"num_locations": 2, "num_colors": 3},
        order_overrides={"requested_ship_date": "2026-06-20T00:00:00.000Z"},
    )
    order = parts["order"]
    # consumed blanks 72+2=74; 74*350=25900 + setup 15000 + decoration 79200 = 120100
    assert order["final_total_cents"] == 120100
    quote = get_quote(order["id"])
    assert quote["grand_total_cents"] != order["final_total_cents"]


# ═══════════════════════════════════════════════════════════════════════════
# boundary_precision_check — quantity tier 23 vs 24
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("qty,expected_subtotal", [
    (23, 18400),   # tier-1 rate 800 at the <=23 boundary; 800*23
    (24, 13200),   # tier-2 rate 550 just past the boundary; 550*24
])
def test_quantity_tier_boundary_23_vs_24(api, qty, expected_subtotal):
    """PRD §3.5: "A `line_qty` of 23 units or fewer is priced at 800 cents per unit
    per location; 24 through 71 units at 550 cents".

    Design: Difficulty/boundary_precision_check/quantity_tier_boundary_23_vs_24
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_confirmed_order(
        cat, size_run={"L": qty}, line_overrides={"num_locations": 1, "num_colors": 1}
    )
    quote = get_quote(parts["order"]["id"])
    assert quote["decoration_subtotal_cents"] == expected_subtotal


def test_quantity_tier_just_below_first_boundary(api):
    """PRD §3.5: "the rate is 800 when `line_qty` is at most 23".

    Design: Difficulty/boundary_precision_check/quantity_tier_boundary_23_vs_24
    """
    cat = setup_shop_catalog(stock_qty=100)
    parts = setup_confirmed_order(
        cat, size_run={"L": 22}, line_overrides={"num_locations": 1, "num_colors": 1}
    )
    quote = get_quote(parts["order"]["id"])
    # 22 units still tier-1: 800*22 = 17600
    assert quote["decoration_subtotal_cents"] == 17600


# ═══════════════════════════════════════════════════════════════════════════
# boundary_precision_check — rush window strict 7-day cutoff
# ═══════════════════════════════════════════════════════════════════════════

def test_rush_window_exactly_seven_days_is_not_rush(api):
    """PRD §3.4: "the order `is_rush` exactly when that whole-day count is strictly
    less than the shop's `rush_threshold_days`. A ship date exactly
    `rush_threshold_days` whole days out is *not* a rush; the boundary is strict."

    Design: Difficulty/boundary_precision_check/rush_window_threshold_7_days_strict
    """
    cat = setup_shop_catalog(clock="2026-06-01T00:00:00.000Z", stock_qty=100)
    parts = setup_confirmed_order(
        cat, size_run={"L": 30}, line_overrides={"num_locations": 1, "num_colors": 1},
        order_overrides={"requested_ship_date": "2026-06-08T00:00:00.000Z"},
    )
    order = parts["order"]
    assert order["is_rush"] is False
    quote = get_quote(order["id"])
    assert quote["rush_surcharge_cents"] == 0


def test_rush_window_six_days_is_below_strict_cutoff(api):
    """PRD §3.4: "the order `is_rush` exactly when that whole-day count is strictly less
    than the shop's `rush_threshold_days`."

    Design: Difficulty/boundary_precision_check/rush_window_threshold_7_days_strict
    """
    cat = setup_shop_catalog(clock="2026-06-01T00:00:00.000Z", stock_qty=100)
    parts = setup_confirmed_order(
        cat, size_run={"L": 30}, line_overrides={"num_locations": 1, "num_colors": 1},
        order_overrides={"requested_ship_date": "2026-06-07T00:00:00.000Z"},  # 6 whole days
    )
    # 6 < 7 -> is_rush true (strict-cutoff lower side).
    assert parts["order"]["is_rush"] is True


def test_rush_window_six_days_is_rush(api):
    """PRD §3.4: "The `rush_surcharge_cents` is the ceiling of `decoration_subtotal_cents`
    times the shop's `rush_surcharge_pct` when the order is a rush, and 0 otherwise."
    PRD §3.4: "the order `is_rush` exactly when that whole-day count is strictly less
    than the shop's `rush_threshold_days`."

    Design: Corner/cross_cutting_complexity_layers/rush_surcharge_applied_when_rush
    """
    cat = setup_shop_catalog(
        clock="2026-06-01T00:00:00.000Z",
        method_overrides={"screen_fee_cents": 2500, "extra_color_run_cents": 75},
        style_overrides={"blank_cost_cents": 350},
        stock_qty=200,
    )
    parts = setup_confirmed_order(
        cat, size_run={"L": 72}, line_overrides={"num_locations": 2, "num_colors": 3},
        order_overrides={"requested_ship_date": "2026-06-07T00:00:00.000Z"},
    )
    order = parts["order"]
    assert order["is_rush"] is True
    quote = get_quote(order["id"])
    # rush = ceil(decoration 79200 * 0.25) = 19800; grand = 25200+15000+79200+19800
    assert quote["rush_surcharge_cents"] == 19800
    assert quote["grand_total_cents"] == 139200


# ═══════════════════════════════════════════════════════════════════════════
# calculations (corner) — embroidery run cost by stitch thousands
# ═══════════════════════════════════════════════════════════════════════════

def test_embroidery_run_cost_by_stitch_thousands(api):
    """PRD §3.5: "the per-unit-per-location run cost is the method's
    `stitch_run_per_1k_cents` multiplied by the line's stitch count expressed in whole
    thousands, where the thousands are obtained by dividing `stitch_count` by 1000 and
    rounding up to the next whole thousand."

    Design: Corner/calculations/embroidery_run_cost_stitch_thousands
    """
    cat = setup_shop_catalog(
        method_type="EMBROIDERY",
        method_overrides={"digitizing_fee_cents": 5000, "stitch_run_per_1k_cents": 90},
        style_overrides={
            "sku_code": "CAP-100", "name": "Cap", "blank_cost_cents": 600,
            "available_colors": ["BLACK"], "available_sizes": ["OS"],
        },
        sku_size="OS", stock_qty=100,
    )
    parts = setup_confirmed_order(
        cat, size_run={"OS": 30}, line_overrides={"num_locations": 1, "stitch_count": 8500}
    )
    quote = get_quote(parts["order"]["id"])
    # ceil(8500/1000)=9; 9*90=810; *1 loc=810; *30=24300
    assert quote["decoration_subtotal_cents"] == 24300
    # setup = 1 location * digitizing_fee 5000
    assert quote["setup_subtotal_cents"] == 5000
    # blanks 600*30
    assert quote["blank_subtotal_cents"] == 18000


# ═══════════════════════════════════════════════════════════════════════════
# calculations (corner) — reorder setup waiver
# ═══════════════════════════════════════════════════════════════════════════

def test_reorder_with_matching_art_hash_waives_setup(api):
    """PRD §3.6: "When the order names a `reorder_of_order_id` and the order's
    `APPROVED` `ArtProof`'s `art_hash` equals the referenced order's approved proof's
    `art_hash`, the screens or digitized design already exist and that line's setup
    charge is waived to zero before it is added to the subtotal."

    Design: Corner/calculations/reorder_setup_waived
    """
    cat = setup_shop_catalog(
        method_overrides={"extra_color_run_cents": 75, "screen_fee_cents": 2500},
        style_overrides={"blank_cost_cents": 350},
        stock_qty=400,
    )
    # Order #1 fulfilled with art_hash h1.
    first = setup_fulfilled_order(
        cat, size_run={"L": 72}, good_units=72, spoiled_units=0,
        line_overrides={"num_locations": 2, "num_colors": 3},
    )
    o1_id = first["order"]["id"]

    # Order #2: reorder of #1, same line + art_hash h1, approved + confirmed.
    parts = setup_confirmed_order(
        cat, size_run={"L": 72},
        line_overrides={"num_locations": 2, "num_colors": 3},
        order_overrides={"reorder_of_order_id": o1_id,
                         "requested_ship_date": "2026-06-25T00:00:00.000Z"},
    )
    quote = get_quote(parts["order"]["id"])
    assert quote["setup_subtotal_cents"] == 0
    # blank 25200 + decoration 79200 + setup 0
    assert quote["grand_total_cents"] == 104400
