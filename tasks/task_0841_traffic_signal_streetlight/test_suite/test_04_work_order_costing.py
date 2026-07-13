"""Work-order provisional vs final costing and the pinned per-line rounding order."""
from test_helpers import validate_success, assert_cost_precision
from test_helpers.fixtures import (
    new_intersection, new_device, new_work_order, setup_completed_work_order,
)


# ── Difficulty: provisional (estimates) vs final (actuals) diverge ────────────
def test_provisional_cost_computed_from_estimates_at_creation(api, dispatcher_headers):
    """PRD §3.4: "A new work order opens in `DRAFT` with `crew_id`,
    `scheduled_start`, and `scheduled_end` empty, and its `provisional_cost` is
    computed immediately from the estimated inputs."
    PRD §3.4: "First, the labor cost is the hours multiplied by the labor rate of
    \\$95.00 per hour, rounded to two decimal places. Next, each parts line item's
    cost is the line's `qty` multiplied by its `unit_price`, rounded to two decimal
    places for that line individually; these per-line rounded values are then
    summed to give the parts cost. The subtotal is the labor cost plus the parts
    cost. Overhead is 15 percent of that subtotal, rounded to two decimal places.
    The final cost is the subtotal plus the rounded overhead."

    Design: Difficulty/dual_variant_calc/work_order_provisional_vs_final_cost
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    wo = new_work_order(device["id"], work_type="REPAIR", estimated_labor_hours=2.0,
                        estimated_parts=[{"qty": 3, "unit_price": 12.00}])
    # labor 190.00 + parts 36.00 = 226.00; overhead round(33.90) = 33.90; total 259.90.
    assert wo["provisional_cost"] == 259.90, \
        f"expected provisional 259.90, got {wo['provisional_cost']}"


def test_final_cost_from_actuals_diverges_from_provisional(api, dispatcher_headers):
    """PRD §3.4: "The provisional computation uses `estimated_labor_hours` and
    `estimated_parts` and writes `provisional_cost`; the final computation, run at
    completion, uses `actual_labor_hours` and `actual_parts` and writes
    `final_cost`, which diverges from the provisional whenever the actuals differ
    from the estimates."

    Design: Difficulty/dual_variant_calc/work_order_provisional_vs_final_cost
    """
    ctx = setup_completed_work_order(
        work_type="REPAIR", estimated_labor_hours=2.0,
        estimated_parts=[{"qty": 3, "unit_price": 12.00}],
        actual_labor_hours=2.5,
        actual_parts=[{"qty": 3, "unit_price": 12.333}, {"qty": 2, "unit_price": 5.005}])
    wo = ctx["work_order"]
    assert wo["provisional_cost"] == 259.90
    assert wo["final_cost"] == 327.19, f"expected final 327.19, got {wo['final_cost']}"
    assert wo["provisional_cost"] != wo["final_cost"]


# ── Difficulty: pinned per-line rounding order ───────────────────────────────
def test_final_cost_uses_per_line_rounding_order(api, dispatcher_headers):
    """PRD §3.4: "Next, each parts line item's cost is the line's `qty` multiplied
    by its `unit_price`, rounded to two decimal places for that line individually;
    these per-line rounded values are then summed to give the parts cost."
    PRD §3.4: "Rounding each line first and then summing is required; summing raw
    line values and rounding once at the end would produce a different, incorrect
    figure."

    Design: Difficulty/combinatorial_formula/work_order_cost_per_line_rounding_order
    """
    ctx = setup_completed_work_order(
        work_type="LED_REPLACEMENT", estimated_labor_hours=2.0,
        estimated_parts=[{"qty": 1, "unit_price": 1.00}], with_ticket=False,
        actual_labor_hours=2.5,
        actual_parts=[{"qty": 3, "unit_price": 12.333}, {"qty": 2, "unit_price": 5.005}])
    wo = ctx["work_order"]
    # round(3*12.333,2)=37.00 and round(2*5.005,2)=10.01 -> parts 47.01;
    # labor 237.50; overhead round(284.51*0.15,2)=42.68; final 327.19.
    assert wo["final_cost"] == 327.19, f"expected final 327.19, got {wo['final_cost']}"


def test_final_cost_two_decimal_precision(api, dispatcher_headers):
    """PRD §2.7: "All dollar amounts — provisional and final work-order costs and
    warranty payouts — are computed to 2 decimal places using round-half-up.
    Work-order costs additionally observe a **pinned rounding order** described in
    §3: each parts line item is rounded to cents individually before the line items
    are summed, and labor and overhead are each rounded to cents at their own step."

    Design: Difficulty/combinatorial_formula/work_order_cost_per_line_rounding_order
    """
    ctx = setup_completed_work_order(
        work_type="LED_REPLACEMENT", estimated_labor_hours=2.0,
        estimated_parts=[{"qty": 1, "unit_price": 1.00}], with_ticket=False,
        actual_labor_hours=2.5,
        actual_parts=[{"qty": 3, "unit_price": 12.333}, {"qty": 2, "unit_price": 5.005}])
    wo = ctx["work_order"]
    assert_cost_precision(wo["final_cost"])
    assert wo["final_cost"] == 327.19
