"""Line pricing, order subtotal rounding order, and volume discounts (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    create_dealer,
    create_draft_order,
    create_glass_gp1,
    create_order_line_payload,
    create_series_a050,
    create_series_v200,
    get_success_data,
    setup_mn_catalog,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]


def test_arch_line_geometry_and_lead_time(api):
    """PRD §3.2: "Its per-unit `glazing_sqft` is the width times the height
    divided by 144, scaled by the shape's area factor — 1.0 for `RECTANGLE`,
    0.85 for `ARCH`, 0.785 for `CIRCLE`, and 0.9 for `TRAPEZOID` — rounded
    half-up to two decimal places."
    PRD §3.2: "The per-unit `billable_sqft` is the greater of that glazing area
    and the series' `min_billable_sqft`, so a tiny unit still bills the series
    minimum."
    PRD §3.2: "Each line's `lead_time_days` is the series'
    `lead_time_special_shape_days` when the shape is anything other than
    `RECTANGLE`, and `lead_time_standard_days` otherwise."

    Design: Difficulty/combinatorial_formula/line_pricing_multi_input_nonlinear
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    line = validate_success(api.add_order_line(
        order["id"],
        create_order_line_payload(
            cat["series"]["id"], cat["glass"]["id"],
            shape="ARCH", width_in=36, height_in=48, quantity=2,
            grid_style="COLONIAL", hardware_finish="BRUSHED_NICKEL",
        ),
        PM,
    ), 201)
    assert line["united_inches"] == 84
    assert line["glazing_sqft"] == pytest.approx(10.2, abs=0.001)
    assert line["billable_sqft"] == pytest.approx(10.2, abs=0.001)
    assert line["lead_time_days"] == 25


def test_arch_line_total_multi_input(api):
    """PRD §3.2: "The raw per-unit price is then the `united_inches` multiplied
    by the series' `base_rate_cents_per_ui` multiplied by the shape multiplier,
    plus the `billable_sqft` multiplied by the glass package's
    `price_per_sqft_cents`, plus a grid adder of 0 cents for `NONE`, 4,000 cents
    for `COLONIAL`, 5,500 cents for `PRAIRIE`, or 7,000 cents for `DIAMOND`, plus
    a hardware adder of 0 cents for `STANDARD`, 2,500 cents for `BRUSHED_NICKEL`,
    or 3,200 cents for `OIL_RUBBED_BRONZE`."
    PRD §3.2: "The `line_total_cents` is that raw per-unit price multiplied by
    `quantity`, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/line_pricing_multi_input_nonlinear
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    line = validate_success(api.add_order_line(
        order["id"],
        create_order_line_payload(
            cat["series"]["id"], cat["glass"]["id"],
            shape="ARCH", width_in=36, height_in=48, quantity=2,
            grid_style="COLONIAL", hardware_finish="BRUSHED_NICKEL",
        ),
        PM,
    ), 201)
    # per-unit: 84*1500*1.40 + 10.2*900 + 4000 + 2500 = 192080; x2 = 384160
    assert line["line_total_cents"] == 384160


def test_per_line_rounding_applied_to_each_line(api):
    """PRD §3.2: "The `line_total_cents` is that raw per-unit price multiplied by
    `quantity`, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/order_subtotal_per_line_rounding_order
    """
    series = create_series_a050()
    glass = create_glass_gp1()
    dealer = create_dealer()
    order = create_draft_order(dealer["id"])
    line1 = add_line(order["id"], series["id"], glass["id"],
                     shape="ARCH", width_in=13, height_in=13)
    line2 = add_line(order["id"], series["id"], glass["id"],
                     shape="ARCH", width_in=13, height_in=13)
    # per-unit raw: 26*1999*1.33 + 1.0*900 = 70025.42 -> 70025 per line
    assert line1["line_total_cents"] == 70025
    assert line2["line_total_cents"] == 70025


def test_subtotal_sums_post_rounding_line_totals(api):
    """PRD §3.2: "The `subtotal_cents` is the sum of the post-rounding
    `line_total_cents` of all non-`CANCELLED` lines — each line is rounded
    first, and no rounding ever happens after the summation."

    Design: Difficulty/combinatorial_formula/order_subtotal_per_line_rounding_order
    """
    series = create_series_a050()
    glass = create_glass_gp1()
    dealer = create_dealer()
    order = create_draft_order(dealer["id"])
    add_line(order["id"], series["id"], glass["id"], shape="ARCH", width_in=13, height_in=13)
    add_line(order["id"], series["id"], glass["id"], shape="ARCH", width_in=13, height_in=13)
    fetched = validate_success(api.get_order(order["id"], PM), 200)
    # 70025 + 70025 = 140050; sum-then-round of the raw values would give 140051
    assert fetched["subtotal_cents"] == 140050


def test_discount_tier_keyed_on_prediscount_subtotal(api):
    """PRD §3.2: "Discounting is then evaluated in a fixed order: compute the
    pre-discount subtotal, select the tier from that pre-discount figure only,
    then apply it."
    PRD §3.2: "The discounted total never feeds back into tier selection."

    Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_prediscount_subtotal
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=13)
    confirmed = validate_success(api.confirm_order(order["id"], PM), 200)
    assert confirmed["subtotal_cents"] == 2145039
    # 8% of the PRE-discount subtotal: round_half_up(2145039 * 0.08) = 171603
    assert confirmed["discount_cents"] == 171603
    # 1973436 is below the 8% floor — proof the tier was keyed pre-discount
    assert confirmed["total_price_cents"] == 1973436


def test_confirm_freezes_totals_in_response(api):
    """PRD §3.2: "On success the server reprices every line one final time,
    freezes `subtotal_cents`, `discount_cents`, and `total_price_cents`, moves
    `compliance_status` to `PROVISIONALLY_COMPLIANT`, cascades each line from
    `PENDING` to `CONFIRMED`, and increments the order's `version`."

    Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_prediscount_subtotal
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=13)
    confirmed = validate_success(api.confirm_order(order["id"], PM), 200)
    assert confirmed["compliance_status"] == "PROVISIONALLY_COMPLIANT"
    reread = validate_success(api.get_order(order["id"], PM), 200)
    assert reread["subtotal_cents"] == confirmed["subtotal_cents"] == 2145039
    assert reread["discount_cents"] == confirmed["discount_cents"] == 171603
    assert reread["total_price_cents"] == confirmed["total_price_cents"] == 1973436


def test_volume_discount_tier_boundaries(api):
    """PRD §3.2: "A subtotal of at least 500,000 cents ($5,000) earns 5 percent;
    at least 2,000,000 cents ($20,000) earns 8 percent; at least 5,000,000 cents
    ($50,000) earns 12 percent; below the first tier there is no discount."
    PRD §3.2: "The `discount_cents` is the subtotal multiplied by the selected
    percentage, rounded half-up to whole cents, and `total_price_cents` is the
    subtotal minus the discount."

    Design: Corner/calculations/volume_discount_tier_boundaries
    """
    cat = setup_mn_catalog()
    orders = {}
    for qty in (3, 4, 16):
        order = create_draft_order(cat["dealer"]["id"])
        add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=qty)
        orders[qty] = validate_success(api.confirm_order(order["id"], PM), 200)

    # unit line total is 165003 cents
    assert orders[3]["subtotal_cents"] == 495009
    assert orders[3]["discount_cents"] == 0
    assert orders[3]["total_price_cents"] == 495009

    assert orders[4]["subtotal_cents"] == 660012
    assert orders[4]["discount_cents"] == 33001  # round_half_up(660012 * 0.05)
    assert orders[4]["total_price_cents"] == 627011

    assert orders[16]["subtotal_cents"] == 2640048
    assert orders[16]["discount_cents"] == 211204  # round_half_up(2640048 * 0.08)
    assert orders[16]["total_price_cents"] == 2428844


def test_line_patch_recomputes_price_and_promised_date(api):
    """PRD §3.2: "While the order remains `DRAFT`, a line can be reconfigured:
    the edit carries `expected_order_version` (see §2.8) plus any of
    `series_id`, `glass_package_id`, `shape`, `width_in`, `height_in`,
    `quantity`, `grid_style`, or `hardware_finish`, reprices the line under the
    same rules, re-evaluates its energy label back on the `PROVISIONAL` basis,
    recomputes the order totals, and increments the order's `version`."
    PRD §3.2: "The order's `promised_date` is its `order_date` plus the largest
    `lead_time_days` among its non-`CANCELLED` lines, recomputed whenever a line
    is added, edited, or cancelled."

    Design: Corner/calculations/line_patch_recomputes_price_and_promised_date
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])
    arch = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"],
                    shape="ARCH", width_in=36, height_in=48,
                    grid_style="COLONIAL", hardware_finish="BRUSHED_NICKEL")
    assert arch["line_total_cents"] == 192080
    before = validate_success(api.get_order(order["id"], PM), 200)
    assert str(before["promised_date"]).startswith("2026-08-27"), (
        f"max(10d, 25d) lead from 2026-08-02, got {before['promised_date']!r}"
    )

    patched = validate_success(api.patch_order_line(
        order["id"], arch["id"],
        {"expected_order_version": before["version"], "shape": "RECTANGLE"},
        PM,
    ), 200)
    # 84*1500*1.0 + 12.0*900 + 4000 + 2500 = 143300
    assert patched["line_total_cents"] == 143300
    assert patched["lead_time_days"] == 10

    after = validate_success(api.get_order(order["id"], PM), 200)
    assert str(after["promised_date"]).startswith("2026-08-12")
    assert after["subtotal_cents"] == 308303  # 165003 + 143300
