"""Post-event actualization and settlement (estimate vs actual, conditional bases).

Translates queue-A instances (dual_variant_calc/food_revenue_estimate_vs_actual_headcount,
combinatorial_formula/settlement_conditional_bases_grand_total).
"""
from test_helpers import validate_success
from test_helpers import fixtures as fx
from test_helpers.constants import dt


# --------------------------------------------------------------------------
# Difficulty: dual_variant_calc / food_revenue_estimate_vs_actual_headcount
# --------------------------------------------------------------------------
def test_quote_food_revenue_uses_booked_headcount(api, sales_manager_headers):
    """PRD §3.3: "The revenue contribution of the line is that portion count times the
    referenced menu item's `sell_price_cents_per_portion` ... Summing the revenue
    contributions over all active lines gives `food_revenue_cents`"

    Design: Difficulty/dual_variant_calc/food_revenue_estimate_vs_actual_headcount
    """
    ctx = fx.drive_order_to_completed(
        api, guest_count=100, service_charge_pct=0.20, gratuity_pct=0.15,
        portions_per_guest=1.0, sell=1000, unit_cost_cents=10, qty_per_portion=5,
        run_portions=120, staff_actual=None, rental=None,
    )
    quote = validate_success(api.get_quote(ctx["quote_id"], sales_manager_headers))
    assert quote["food_revenue_cents"] == 100000, (
        f"quote at booked guest_count 100: 100 * 1000, got {quote['food_revenue_cents']}"
    )


def test_actual_food_revenue_uses_served_headcount(api, sales_manager_headers):
    """PRD §3.8: "`actual_food_revenue_cents` is the sum, over `ACTIVE` order lines, of
    each line's portion count (its `portions_per_guest` times `actual_guest_count`,
    rounded up to a whole number) times the menu item's `sell_price_cents_per_portion`"

    Design: Difficulty/dual_variant_calc/food_revenue_estimate_vs_actual_headcount
    """
    ctx = fx.drive_order_to_completed(
        api, guest_count=100, service_charge_pct=0.20, gratuity_pct=0.15,
        portions_per_guest=1.0, sell=1000, unit_cost_cents=10, qty_per_portion=5,
        run_portions=120, staff_actual=None, rental=None,
    )
    order = validate_success(api.actualize_order(ctx["order_id"], {"actual_guest_count": 120}, sales_manager_headers))
    assert order["actual_food_revenue_cents"] == 120000, (
        f"settlement at served 120: 120 * 1000, got {order['actual_food_revenue_cents']}"
    )
    assert order["actual_food_revenue_cents"] != ctx["quote_food_revenue"], (
        "actual (served) revenue must differ from quote (booked) revenue"
    )


# --------------------------------------------------------------------------
# Difficulty: combinatorial_formula / settlement_conditional_bases_grand_total
# --------------------------------------------------------------------------
_SETTLEMENT_RENTAL = {"qty": 4, "price": 500, "total_units": 20, "out": dt(8), "return": dt(21)}


def _settlement_order(api):
    return fx.drive_order_to_completed(
        api, guest_count=50, service_charge_pct=0.20, gratuity_pct=0.15,
        portions_per_guest=1.0, sell=1000, unit_cost_cents=10, qty_per_portion=5,
        run_portions=50, staff_shift=(dt(10), dt(16)), staff_actual=(dt(10), dt(16)),
        rental=_SETTLEMENT_RENTAL,
    )


def test_settlement_surcharge_bases_exclude_and_include_correctly(api, sales_manager_headers):
    """PRD §3.8: "The service charge, `actual_service_charge_cents`, is `service_charge_pct`
    times the sum of `actual_food_revenue_cents` and the accumulated labor total, rounded
    half up — its base deliberately excludes rentals. The gratuity, `actual_gratuity_cents`,
    is `gratuity_pct` times `actual_food_revenue_cents` alone, rounded half up — its base is
    food revenue only."

    Design: Difficulty/combinatorial_formula/settlement_conditional_bases_grand_total
    """
    ctx = _settlement_order(api)
    order = validate_success(api.actualize_order(ctx["order_id"], {"actual_guest_count": 50}, sales_manager_headers))
    assert order["actual_service_charge_cents"] == 12400, (
        f"0.20 * (50000 + 12000 labor), rentals excluded = 12400, got {order['actual_service_charge_cents']}"
    )
    assert order["actual_gratuity_cents"] == 7500, (
        f"0.15 * 50000 food only = 7500, got {order['actual_gratuity_cents']}"
    )


def test_settlement_grand_total_sums_five_components(api, sales_manager_headers):
    """PRD §3.8: "Finally, `actual_grand_total_cents` is the sum of five components:
    `actual_food_revenue_cents`, the labor total, `actual_rental_cents`,
    `actual_service_charge_cents`, and `actual_gratuity_cents`."

    Design: Difficulty/combinatorial_formula/settlement_conditional_bases_grand_total
    """
    ctx = _settlement_order(api)
    order = validate_success(api.actualize_order(ctx["order_id"], {"actual_guest_count": 50}, sales_manager_headers))
    assert order["actual_food_revenue_cents"] == 50000
    assert order["actual_labor_total_cents"] == 12000
    assert order["actual_rental_cents"] == 2000
    assert order["actual_grand_total_cents"] == 83900, (
        f"50000 + 12000 + 2000 + 12400 + 7500 = 83900, got {order['actual_grand_total_cents']}"
    )
