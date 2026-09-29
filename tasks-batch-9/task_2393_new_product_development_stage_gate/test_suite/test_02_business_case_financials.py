"""Business case volume derivation, per-line rounding and the gross-keyed trade tier."""
import pytest

from test_helpers import (
    add_forecast_line,
    assert_business_case,
    assert_forecast_line,
    forecast_line_payload,
    intake_project,
    open_business_case,
    set_clock,
    validate_success,
)

GROCERY_LINE = {
    "channel": "GROCERY",
    "store_count": 4200,
    "base_velocity_units_per_store_week": 1.75,
    "promo_weeks": 6,
    "promo_lift_pct": 45.5,
    "list_price_usd": 3.4915,
}
MASS_LINE = {
    "channel": "MASS",
    "store_count": 3150,
    "base_velocity_units_per_store_week": 2.35,
    "promo_weeks": 8,
    "promo_lift_pct": 57.5,
    "list_price_usd": 3.2875,
}
TOP_DOWN_CASE = {
    "variant_mode": "TOP_DOWN",
    "category_size_units_year": 40000000,
    "target_share_pct": 1.25,
    "cogs_per_unit_usd": 1.0500,
    "slotting_fees_usd": 250000.00,
    "capex_usd": 900000.00,
    "discount_rate_pct": 9.00,
}
BOTTOM_UP_CASE = dict(TOP_DOWN_CASE, variant_mode="BOTTOM_UP")


def _volume_probe_project(name="Volume Variant Probe"):
    return intake_project(
        owner_user_id="lead-p1",
        name=name,
        category="BEVERAGE",
        project_type="NEW_BRAND",
        strategic_fit_score=7,
        consumer_need_score=8,
        target_gross_margin_pct=32,
        category_attractiveness_score=6,
        development_budget_cap_usd=500000.00,
    )


def test_top_down_and_bottom_up_diverge_on_identical_channel_lines(api, innovation_lead_headers):
    """Two cases with identical inputs and identical lines settle on different volumes.

    PRD: "- Under `BOTTOM_UP`, `annual_units` is the sum of the stored `line_units` and
    `gross_revenue_usd` is the sum of the stored `line_revenue_usd`. `category_size_units_year`
    and `target_share_pct` are ignored entirely."

    Design: Difficulty/dual_variant_calc/business_case_volume_variant_divergence
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _volume_probe_project()

    top_down = open_business_case(project["id"], **TOP_DOWN_CASE)
    add_forecast_line(top_down["id"], **GROCERY_LINE)
    add_forecast_line(top_down["id"], **MASS_LINE)

    bottom_up = open_business_case(project["id"], **BOTTOM_UP_CASE)
    add_forecast_line(bottom_up["id"], **GROCERY_LINE)
    add_forecast_line(bottom_up["id"], **MASS_LINE)
    bottom_up = validate_success(api.get_business_case(bottom_up["id"], innovation_lead_headers))
    top_down = validate_success(api.get_business_case(top_down["id"], innovation_lead_headers))

    assert_business_case(top_down)
    assert_business_case(bottom_up)
    assert top_down["case_type"] == "PRELIMINARY", "the project's first case is preliminary"
    assert bottom_up["case_type"] == "FINAL", "every later case takes FINAL"
    assert top_down["annual_units"] == 500000, "40000000 * 1.25% = 500000"
    assert bottom_up["annual_units"] == 821248, "402266 + 418982 line units"
    assert bottom_up["annual_units"] - top_down["annual_units"] == 321248, (
        "the same two lines support two different volume theses"
    )
    assert top_down["avg_list_price_usd"] == pytest.approx(3.4041, abs=0.00005)
    assert bottom_up["avg_list_price_usd"] == pytest.approx(3.4041, abs=0.00005), (
        "the weighted average price is variant-independent"
    )
    assert top_down["gross_revenue_usd"] == pytest.approx(1702050.00, abs=0.01)
    assert bottom_up["gross_revenue_usd"] == pytest.approx(2781915.07, abs=0.01)
    assert top_down["gross_margin_pct"] == pytest.approx(57.93, abs=0.01)
    assert bottom_up["gross_margin_pct"] == pytest.approx(60.77, abs=0.01)
    assert top_down["payback_months"] == 15
    assert bottom_up["payback_months"] == 9
    assert top_down["status"] == "SUPERSEDED", "opening a new case supersedes the previous one"
    assert bottom_up["status"] == "COMPUTED"


def test_top_down_reads_the_category_share_and_ignores_the_line_volumes(api, innovation_lead_headers):
    """A top-down case takes nothing from its lines but the weighted average price.

    PRD: "- Under `TOP_DOWN`, `annual_units` is `category_size_units_year` multiplied by
    `target_share_pct` divided by 100, rounded half up to a whole number, and
    `gross_revenue_usd` is that `annual_units` multiplied by `avg_list_price_usd`, rounded
    half up to two decimal places. Here the lines contribute nothing but the weighted average
    price."

    Design: Difficulty/dual_variant_calc/business_case_volume_variant_divergence
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _volume_probe_project(name="Top Down Only Probe")

    case = open_business_case(project["id"], **TOP_DOWN_CASE)
    add_forecast_line(case["id"], **GROCERY_LINE)
    add_forecast_line(case["id"], **MASS_LINE)
    case = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert case["annual_units"] == 500000
    assert case["annual_units"] != 821248, "the summed line units are not the top-down volume"
    assert case["avg_list_price_usd"] == pytest.approx(3.4041, abs=0.00005)
    assert case["gross_revenue_usd"] == pytest.approx(1702050.00, abs=0.01)
    assert case["trade_spend_rate_pct"] == pytest.approx(12.00, abs=0.01)
    assert case["trade_spend_usd"] == pytest.approx(204246.00, abs=0.01)
    assert case["net_revenue_usd"] == pytest.approx(1247804.00, abs=0.01)
    assert case["cogs_total_usd"] == pytest.approx(525000.00, abs=0.01)
    assert case["gross_margin_usd"] == pytest.approx(722804.00, abs=0.01)
    assert case["gross_margin_pct"] == pytest.approx(57.93, abs=0.01)
    assert case["npv_usd"] == pytest.approx(1155954.60, abs=0.01)
    assert case["payback_months"] == 15


def test_each_line_rounds_its_units_before_the_volume_is_summed(api, innovation_lead_headers):
    """Rounding each line first yields 821248 units, one more than rounding the raw sum.

    PRD: "That raw figure is rounded half up to a whole number and stored as `line_units`, and
    `line_revenue_usd` is `line_units` multiplied by `list_price_usd`, rounded half up to two
    decimal places."

    Design: Difficulty/combinatorial_formula/forecast_per_line_rounding_before_summation
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _volume_probe_project(name="Rounding Probe")
    case = open_business_case(project["id"], **BOTTOM_UP_CASE)

    grocery = add_forecast_line(case["id"], **GROCERY_LINE)
    mass = validate_success(
        api.create_forecast_line(case["id"], forecast_line_payload(**MASS_LINE),
                                 innovation_lead_headers),
        201,
    )
    case = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert_forecast_line(grocery)
    assert_forecast_line(mass)
    assert grocery["line_units"] == 402266, "4200 * 1.75 * (52 + 6*45.5/100) rounds up"
    assert mass["line_units"] == 418982, "3150 * 2.35 * (52 + 8*57.5/100) rounds up"
    assert case["annual_units"] == 821248
    assert case["annual_units"] != 821247, (
        "summing the raw volumes and rounding once loses a unit"
    )
    assert case["annual_units"] == grocery["line_units"] + mass["line_units"]


def test_gross_revenue_sums_the_already_rounded_line_revenue(api, innovation_lead_headers):
    """Gross revenue is the sum of two cent-rounded line revenues, not one late rounding.

    PRD: "**Both per-line roundings happen before any summation**, which is load-bearing:
    summing raw units first and rounding once at the end can differ by a unit, and rounding
    revenue only once can differ by a cent."

    Design: Difficulty/combinatorial_formula/forecast_per_line_rounding_before_summation
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _volume_probe_project(name="Revenue Rounding Probe")
    case = open_business_case(project["id"], **BOTTOM_UP_CASE)

    grocery = add_forecast_line(case["id"], **GROCERY_LINE)
    mass = add_forecast_line(case["id"], **MASS_LINE)
    case = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert grocery["line_revenue_usd"] == pytest.approx(1404511.74, abs=0.01)
    assert mass["line_revenue_usd"] == pytest.approx(1377403.33, abs=0.01)
    assert case["gross_revenue_usd"] == pytest.approx(2781915.07, abs=0.01)
    assert abs(case["gross_revenue_usd"] - 2781915.06) > 0.005, (
        "a single late rounding of revenue would have lost a cent"
    )
    assert case["gross_revenue_usd"] == pytest.approx(
        grocery["line_revenue_usd"] + mass["line_revenue_usd"], abs=0.01
    )


def test_trade_spend_tier_keys_on_gross_revenue_at_the_upper_boundary(api, innovation_lead_headers):
    """Gross revenue of exactly 5000000.00 buys the 15 percent tier, not 12.

    PRD: "1. `trade_spend_rate_pct` is selected from a tiered table keyed on **gross**
    revenue, not net: `10.00` when `gross_revenue_usd` is below `1000000.00`, `12.00` when it
    is at least `1000000.00` and below `5000000.00`, and `15.00` when it is at least
    `5000000.00`."

    Design: Difficulty/combinatorial_formula/trade_rate_keyed_on_gross_before_net_derivation
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _volume_probe_project(name="Tier Boundary Probe")
    case = open_business_case(
        project["id"], **dict(TOP_DOWN_CASE, target_share_pct=5.00)
    )

    add_forecast_line(
        case["id"], channel="CLUB", store_count=1000,
        base_velocity_units_per_store_week=0.00, promo_weeks=0, promo_lift_pct=0.00,
        list_price_usd=2.5000,
    )
    case = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert case["avg_list_price_usd"] == pytest.approx(2.5000, abs=0.00005)
    assert case["annual_units"] == 2000000
    assert case["gross_revenue_usd"] == pytest.approx(5000000.00, abs=0.01)
    assert case["trade_spend_rate_pct"] == pytest.approx(15.00, abs=0.01), (
        "the boundary belongs to the higher tier"
    )
    assert case["trade_spend_rate_pct"] != pytest.approx(12.00, abs=0.001)
    assert case["trade_spend_usd"] == pytest.approx(750000.00, abs=0.01)


def test_net_revenue_follows_the_tier_chosen_on_gross(api, innovation_lead_headers):
    """The whole nine-step chain inherits the gross-keyed tier, down to payback.

    PRD: "3. `net_revenue_usd` is `gross_revenue_usd` less `trade_spend_usd` less
    `slotting_fees_usd`."

    Design: Difficulty/combinatorial_formula/trade_rate_keyed_on_gross_before_net_derivation
    """
    set_clock("2026-08-03T00:00:00Z")
    project = _volume_probe_project(name="Tier Chain Probe")
    case = open_business_case(
        project["id"], **dict(TOP_DOWN_CASE, target_share_pct=5.00)
    )

    add_forecast_line(
        case["id"], channel="CLUB", store_count=1000,
        base_velocity_units_per_store_week=0.00, promo_weeks=0, promo_lift_pct=0.00,
        list_price_usd=2.5000,
    )
    case = validate_success(api.get_business_case(case["id"], innovation_lead_headers))

    assert case["net_revenue_usd"] == pytest.approx(4000000.00, abs=0.01)
    assert abs(case["net_revenue_usd"] - 4150000.00) > 0.01, (
        "the 12 percent tier would have left 4150000.00 of net revenue"
    )
    assert case["cogs_total_usd"] == pytest.approx(2100000.00, abs=0.01)
    assert case["gross_margin_pct"] == pytest.approx(47.50, abs=0.01)
    assert case["npv_usd"] == pytest.approx(4504388.64, abs=0.01)
    assert case["payback_months"] == 6
