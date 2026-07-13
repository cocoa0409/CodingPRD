"""Line pricing, per-line tax rounding, seasonal surcharge, immediate order totals.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_flavor, make_size, make_topping, make_batch,
    open_drawer, open_order, add_line, set_clock, get_order,
    TEST_USERS,
)

SCOOP = TEST_USERS["scooper_headers"]


# ─────────────── combinatorial_formula / line_price_premium_topping_size_nonlinear ───────────────

def test_line_price_premium_topping_double_nonlinear(api):
    """PRD 3.3: "a base equal to the size option's `base_price_cents` multiplied by
    `quantity`; a topping total equal to the sum of the `price_cents` of every
    topping named in `topping_ids`, multiplied by `quantity`; a seasonal surcharge
    equal to 40 cents per scoop applied only when the flavor's `is_seasonal` is
    true, and zero otherwise; and a premium surcharge equal to the flavor's
    `premium_surcharge_cents_per_scoop` per scoop applied only when the flavor's
    `is_premium` is true, and zero otherwise."

    Design: Difficulty/combinatorial_formula/line_price_premium_topping_size_nonlinear
    """
    flavor = make_flavor(name="Pistachio", allergens=["MILK", "NUTS", "PISTACHIO"],
                         is_premium=True, premium_surcharge_cents_per_scoop=60,
                         standard_cost_cents_per_ml=2.20, par_level_ml=300)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    topping = make_topping(name="Hot Fudge", price_cents=100, allergens=["MILK", "SOY"])
    make_batch(flavor["id"], initial_volume_ml=500, unit_cost_cents_per_ml=2.20)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"], topping_ids=[topping["id"]])
    # 550 base + 100 topping + 120 premium (60*2 scoops) = 770
    assert line["line_price_cents"] == 770
    assert line["line_tax_cents"] == 67   # round_half_up(770 * 0.0875) = 67
    assert line["scoops"] == 2


def test_line_price_premium_branch_suppressed_when_not_premium(api):
    """PRD 3.3: "a premium surcharge equal to the flavor's
    `premium_surcharge_cents_per_scoop` per scoop applied only when the flavor's
    `is_premium` is true, and zero otherwise."

    Design: Difficulty/combinatorial_formula/line_price_premium_topping_size_nonlinear
    """
    # Non-premium flavor: the premium branch must NOT fire even if a surcharge value is set.
    flavor = make_flavor(name="Vanilla", is_premium=False,
                         premium_surcharge_cents_per_scoop=60, par_level_ml=300)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    topping = make_topping(name="Hot Fudge", price_cents=100)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"], topping_ids=[topping["id"]])
    # 550 base + 100 topping + 0 premium (is_premium false) + 0 seasonal = 650
    assert line["line_price_cents"] == 650


# ─────────────── combinatorial_formula / order_tax_round_per_line_then_sum ───────────────

def test_tax_rounds_per_line_then_sums_two_lines(api):
    """PRD 3.4: "The rounding order is fixed and material: tax is rounded per line
    and *then* summed, never summed and then rounded — the two approaches yield
    different totals on many baskets, and only round-per-line-then-sum is correct
    here."

    Design: Difficulty/combinatorial_formula/order_tax_round_per_line_then_sum
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    add_line(order["id"], size["id"], flavor["id"])
    o = get_order(order["id"])
    # Each 350 line: round_half_up(350*0.0875)=round_half_up(30.625)=31; 31+31=62.
    # Sum-then-round would be round(700*0.0875)=round(61.25)=61 -> distinct.
    assert o["subtotal_cents"] == 700
    assert o["tax_cents"] == 62
    assert o["total_cents"] == 762


def test_tax_rounds_per_line_then_sums_three_lines(api):
    """PRD 3.4: "its `tax_cents` is the sum of the already-rounded `line_tax_cents`
    over active lines; and its `total_cents` is `subtotal_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/order_tax_round_per_line_then_sum
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    for _ in range(3):
        add_line(order["id"], size["id"], flavor["id"])
    o = get_order(order["id"])
    # Per-line 31 * 3 = 93; sum-then-round round(1050*0.0875)=round(91.875)=92 -> distinct.
    assert o["subtotal_cents"] == 1050
    assert o["tax_cents"] == 93
    assert o["total_cents"] == 1143


# ─────────────── calculations (corner) ───────────────

def test_pumpkin_in_season_seasonal_surcharge_applied(api):
    """PRD 3.3: "a seasonal surcharge equal to 40 cents per scoop applied only when
    the flavor's `is_seasonal` is true, and zero otherwise".
    PRD 3.3: "if the line's flavor is seasonal, the logical clock at the moment of
    sale must fall within the flavor's `[seasonal_start_utc, seasonal_end_utc)`
    window".

    Design: Corner/calculations/pumpkin_in_season_seasonal_surcharge_applied
    """
    flavor = make_flavor(name="Pumpkin", is_seasonal=True,
                         seasonal_start_utc="2026-09-01T00:00:00Z",
                         seasonal_end_utc="2026-12-01T00:00:00Z", par_level_ml=300)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    make_batch(flavor["id"], initial_volume_ml=500,
               produced_at="2026-09-15T00:00:00Z", expiry_at="2026-10-30T00:00:00Z")
    set_clock("2026-10-01T00:00:00Z")
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"])
    # 550 base + 40*2 seasonal = 630
    assert line["line_price_cents"] == 630
    assert line["line_tax_cents"] == 55   # round_half_up(630*0.0875)=round_half_up(55.125)=55


def test_flavor_out_of_season_line_add_rejected(api):
    """PRD 3.3: "if the line's flavor is seasonal, the logical clock at the moment
    of sale must fall within the flavor's `[seasonal_start_utc, seasonal_end_utc)`
    window; a sale outside that window is rejected with `ERR_FLAVOR_OUT_OF_SEASON`."

    Design: Corner/calculations/flavor_out_of_season_line_add_rejected
    """
    # Default clock is 2026-05-01, before the Sep-Dec window.
    flavor = make_flavor(name="Pumpkin", is_seasonal=True,
                         seasonal_start_utc="2026-09-01T00:00:00Z",
                         seasonal_end_utc="2026-12-01T00:00:00Z", par_level_ml=300)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500, expiry_at="2026-06-30T00:00:00Z")
    drawer = open_drawer()
    order = open_order(drawer["id"])
    res = api.add_line(order["id"], {"size_option_id": size["id"], "flavor_id": flavor["id"]}, SCOOP)
    validate_error(res, "ERR_FLAVOR_OUT_OF_SEASON")


# ─────────────── consistency_model (corner) ───────────────

def test_line_add_reflected_in_order_totals_same_request(api):
    """PRD 3.4: "Each active line's `line_tax_cents` is its `line_price_cents`
    multiplied by the tax rate of 0.0875, rounded half up to whole cents. The
    order's `subtotal_cents` is the sum of `line_price_cents` over active lines;
    its `tax_cents` is the sum of the already-rounded `line_tax_cents` over active
    lines; and its `total_cents` is `subtotal_cents` plus `tax_cents`."

    Design: Corner/consistency_model/line_add_reflected_in_order_totals_same_request
    """
    flavor = make_flavor(par_level_ml=300)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    o = get_order(order["id"])
    assert o["subtotal_cents"] == 350
    assert o["tax_cents"] == 31
    assert o["total_cents"] == 381
