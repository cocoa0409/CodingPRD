"""Pricing: per-line cost, the dual estimate/final variants, discount rounding,
oversize tiers, deposit floor, and turnaround.

Translates queue A (Difficulty) rules dual_variant_calc (order pricing instance),
combinatorial_formula (both instances), and boundary_precision_check (oversize tier),
plus queue B (Corner) calculations and the consistency_model instance.
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_customer, create_order, add_line, measure_line, quote,
    setup_order_with_line, add_and_measure_lines, pay,
)
from test_helpers import api_client

DESIGNER = TEST_USERS["frame_designer_headers"]
TECH = TEST_USERS["frame_production_tech_headers"]
CLERK = TEST_USERS["front_desk_clerk_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc / order_estimate_vs_final_diverge_on_measured_dims
# (>=2 tests; second is in test_06 on the customer-scoring instance)
# ===========================================================================
def test_estimate_and_final_diverge_full_lifecycle(api):
    """PRD §2.7: "the quote estimate sums every line first and rounds once at the
    very end (a sum-then-round discipline), whereas the final invoice rounds each
    discounted line to cents before summing them (a round-per-line-then-sum
    discipline)."
    PRD §3.7: "Because the discount is rounded into each line before summation, and
    because the measured dimensions differ from the nominal ones, the final invoice
    total can differ from the quote estimate even for an identical line configuration."

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_diverge_on_measured_dims
    """
    cust = create_customer(loyalty_tier="STANDARD", email="ann@x.com", full_name="Ann Estimate")
    bench = get_success_data(api.create_workbench(
        {"bench_name": "Assembly 1", "bench_type": "ASSEMBLY"}, TECH))
    order = create_order(cust["id"], rush_requested=True, deposit_pct=0.30)
    line = add_line(order["id"], order["version"], artwork_label="Poster",
                    nominal_width_in=16, nominal_height_in=20, molding_rate_per_ui=0.45,
                    mat_border_in=2, mat_layers=2, glass_type="CONSERVATION",
                    mounting_type="DRY_MOUNT", conservation_package=True)
    assert line["estimate_subtotal"] == 183.80
    measured = measure_line(line["id"], 16.25, 20.5)
    assert measured["final_subtotal"] == 186.96
    quoted = quote(order["id"])
    assert quoted["estimate_total"] == 211.37
    pay(quoted["id"], "DEPOSIT", 63.41)
    get_success_data(api.start_production(quoted["id"], TECH))
    task = get_success_data(api.create_task(
        {"order_id": quoted["id"], "workbench_id": bench["id"], "start_minute": 0,
         "end_minute": 60}, TECH))
    get_success_data(api.complete_task(task["id"], TECH))
    ready = get_success_data(api.mark_ready(quoted["id"], TECH))
    assert ready["final_invoice_total"] == 215.00
    assert ready["estimate_total"] != ready["final_invoice_total"]


def test_estimate_and_final_per_line_subtotals_diverge_on_measured_dims(api):
    """PRD §3.3: "The nominal variant uses `nominal_width_in` and `nominal_height_in`
    and produces `estimate_subtotal` ... The measured variant uses `measured_width_in`
    and `measured_height_in` (which must already be set) and produces `final_subtotal`
    ... Because measured dimensions generally differ from the nominal ones, the two
    subtotals generally differ for the same line."

    Second test for the order estimate-vs-final divergence instance: the per-line
    nominal subtotal (183.80) and measured subtotal (186.96) differ for the same line.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_diverge_on_measured_dims
    """
    cust = create_customer(loyalty_tier="STANDARD", email="ann2@x.com")
    order = create_order(cust["id"], rush_requested=True, deposit_pct=0.30)
    line = add_line(order["id"], order["version"], artwork_label="Poster",
                    nominal_width_in=16, nominal_height_in=20, molding_rate_per_ui=0.45,
                    mat_border_in=2, mat_layers=2, glass_type="CONSERVATION",
                    mounting_type="DRY_MOUNT", conservation_package=True)
    assert line["estimate_subtotal"] == 183.80
    measured = measure_line(line["id"], 16.25, 20.5)
    assert measured["final_subtotal"] == 186.96
    assert measured["estimate_subtotal"] != measured["final_subtotal"]


def test_line_cost_tiered_oversize_with_conservation_multiplier(api):
    """PRD §3.3: "If the united inches are at least 120, the surcharge is 95.00.
    Otherwise, if the united inches are at least 80, the surcharge is 40.00.
    Otherwise the surcharge is 0.00."
    PRD §3.3: "If `conservation_package` is true on the line, the materials figure
    is multiplied by a conservation multiplier of 1.20 and the product rounded to
    two decimal places before proceeding".
    PRD §3.3: "The **mounting upcharge** is a flat amount keyed to `mounting_type`:
    0.00 for `NONE`, 15.00 for `PLAIN`, 35.00 for `DRY_MOUNT`, and 55.00 for
    `CONSERVATION_HINGE`."

    Design: Difficulty/combinatorial_formula/line_cost_tiered_oversize_with_conservation_multiplier
    """
    cust = create_customer(email="di@x.com", full_name="Di Big")
    order = create_order(cust["id"])
    line = add_line(order["id"], order["version"], artwork_label="Big",
                    nominal_width_in=30, nominal_height_in=40, molding_rate_per_ui=0.60,
                    mat_border_in=3, mat_layers=2, glass_type="MUSEUM",
                    mounting_type="CONSERVATION_HINGE", conservation_package=True)
    assert line["estimate_subtotal"] == 603.20


def test_line_cost_oversize_tier1_with_labor_and_mat_layers(api):
    """PRD §3.3: "If the united inches are at least 120, the surcharge is 95.00.
    Otherwise, if the united inches are at least 80, the surcharge is 40.00.
    Otherwise the surcharge is 0.00."
    PRD §3.3: "The line subtotal is then the sum of the molding cost, the (possibly
    conservation-adjusted) materials figure, the oversize surcharge, the mounting
    upcharge, and a flat labor charge of 45.00 dollars per line, with that sum rounded
    to two decimal places."

    Second test for the combinatorial line_cost instance — the same >=3-input formula
    crossing the 40.00 oversize tier (ui exactly 80, a 36x36 piece with a 2in mat
    border) without the conservation multiplier; the expected per-line subtotal is 204.11.

    Design: Difficulty/combinatorial_formula/line_cost_tiered_oversize_with_conservation_multiplier
    """
    cust = create_customer(email="t1@x.com")
    order = create_order(cust["id"])
    line = add_line(order["id"], order["version"], artwork_label="Tier1",
                    nominal_width_in=36, nominal_height_in=36, molding_rate_per_ui=0.10,
                    mat_border_in=2, mat_layers=1, glass_type="REGULAR")
    assert line["estimate_subtotal"] == 204.11


# ===========================================================================
# Difficulty: combinatorial_formula / discount_rounding_order_sum_then_round_vs_round_per_line
# ===========================================================================
def test_discount_rounding_sum_then_round_vs_round_per_line(api):
    """PRD §3.4: "This is the sum-then-round discipline: every line is summed, the
    rush and discount are applied to the aggregate, and a single final rounding is
    performed after the discount."
    PRD §3.7: "For each measured line, multiply its `final_subtotal` by one minus the
    owning customer's `loyalty_discount_pct` and round that discounted line value to
    two decimal places; sum those per-line rounded values to obtain the discounted sum."

    Design: Difficulty/combinatorial_formula/discount_rounding_order_sum_then_round_vs_round_per_line
    """
    cust = create_customer(loyalty_tier="PREFERRED", email="cy@x.com", full_name="Cy Round")
    bench = get_success_data(api.create_workbench(
        {"bench_name": "Assembly R", "bench_type": "ASSEMBLY"}, TECH))
    order = create_order(cust["id"], rush_requested=False, deposit_pct=0.50)
    add_and_measure_lines(order["id"], order["version"], [
        {"artwork_label": "L1", "nominal_width_in": 8, "nominal_height_in": 10,
         "molding_rate_per_ui": 0.30, "mat_border_in": 2, "mat_layers": 1,
         "glass_type": "REGULAR", "measure": (8, 10)},
        {"artwork_label": "L2", "nominal_width_in": 11, "nominal_height_in": 14,
         "molding_rate_per_ui": 0.30, "mat_border_in": 2, "mat_layers": 1,
         "glass_type": "REGULAR", "measure": (11, 14)},
        {"artwork_label": "L3", "nominal_width_in": 9, "nominal_height_in": 12,
         "molding_rate_per_ui": 0.30, "mat_border_in": 2, "mat_layers": 1,
         "glass_type": "REGULAR", "measure": (9, 12)},
    ])
    quoted = quote(order["id"])
    assert quoted["estimate_total"] == 185.64
    pay(quoted["id"], "DEPOSIT", 92.82)
    get_success_data(api.start_production(quoted["id"], TECH))
    task = get_success_data(api.create_task(
        {"order_id": quoted["id"], "workbench_id": bench["id"], "start_minute": 0,
         "end_minute": 90}, TECH))
    get_success_data(api.complete_task(task["id"], TECH))
    ready = get_success_data(api.mark_ready(quoted["id"], TECH))
    assert ready["final_invoice_total"] == 185.65
    assert round(ready["final_invoice_total"] - ready["estimate_total"], 2) == 0.01


def test_estimate_sum_then_round_single_final_rounding(api):
    """PRD §3.4: "The owning customer's `loyalty_discount_pct` is then applied to the
    rushed sum by multiplying it by one minus that discount fraction, and the result
    is rounded once to two decimal places."

    Second test for the discount-rounding instance — verifies the estimate side of
    the sum-then-round discipline in isolation.

    Design: Difficulty/combinatorial_formula/discount_rounding_order_sum_then_round_vs_round_per_line
    """
    cust = create_customer(loyalty_tier="PREFERRED", email="cy2@x.com")
    order = create_order(cust["id"], rush_requested=False, deposit_pct=0.50)
    add_and_measure_lines(order["id"], order["version"], [
        {"artwork_label": "L1", "nominal_width_in": 8, "nominal_height_in": 10,
         "molding_rate_per_ui": 0.30, "mat_border_in": 2, "mat_layers": 1, "glass_type": "REGULAR"},
        {"artwork_label": "L2", "nominal_width_in": 11, "nominal_height_in": 14,
         "molding_rate_per_ui": 0.30, "mat_border_in": 2, "mat_layers": 1, "glass_type": "REGULAR"},
        {"artwork_label": "L3", "nominal_width_in": 9, "nominal_height_in": 12,
         "molding_rate_per_ui": 0.30, "mat_border_in": 2, "mat_layers": 1, "glass_type": "REGULAR"},
    ])
    quoted = quote(order["id"])
    # raw 64.47+73.65+68.15=206.27; *0.9=185.643 -> round 185.64
    assert quoted["estimate_total"] == 185.64


# ===========================================================================
# Difficulty: boundary_precision_check / oversize_tier_boundary_ui_exactly_80
# ===========================================================================
def test_oversize_tier_boundary_ui_exactly_80(api):
    """PRD §3.3: "Otherwise, if the united inches are at least 80, the surcharge is
    40.00. Otherwise the surcharge is 0.00."

    Boundary: ui exactly 80 crosses OVERSIZE_TIER1 (at-least, i.e. >=).

    Design: Difficulty/boundary_precision_check/oversize_tier_boundary_ui_exactly_80
    """
    cust = create_customer(email="ka@x.com", full_name="Ka Bound")
    order = create_order(cust["id"])
    line = add_line(order["id"], order["version"], artwork_label="UI80",
                    nominal_width_in=36, nominal_height_in=36, molding_rate_per_ui=0.10,
                    mat_border_in=2, mat_layers=1, glass_type="REGULAR")
    assert line["estimate_subtotal"] == 204.11


def test_oversize_tier_boundary_just_below_80_no_surcharge(api):
    """PRD §3.3: "Otherwise, if the united inches are at least 80, the surcharge is
    40.00. Otherwise the surcharge is 0.00."

    Boundary X-: ui 79.5 stays below the tier and carries no surcharge.

    Design: Difficulty/boundary_precision_check/oversize_tier_boundary_ui_exactly_80
    """
    cust = create_customer(email="ka2@x.com")
    order = create_order(cust["id"])
    line = add_line(order["id"], order["version"], artwork_label="UI79",
                    nominal_width_in=35.5, nominal_height_in=36, molding_rate_per_ui=0.10,
                    mat_border_in=2, mat_layers=1, glass_type="REGULAR")
    assert line["estimate_subtotal"] == 162.67


# ===========================================================================
# Corner: calculations
# ===========================================================================
def test_trade_loyalty_discount_applied_to_estimate(api):
    """PRD §3.1: "a `TRADE` customer 0.15."
    PRD §3.4: "The owning customer's `loyalty_discount_pct` is then applied to the
    rushed sum by multiplying it by one minus that discount fraction, and the result
    is rounded once to two decimal places."

    Design: Corner/calculations/trade_loyalty_discount_applied_to_estimate
    """
    cust, order, line = setup_order_with_line(customer_tier="TRADE", measure_dims=(8, 10))
    quoted = quote(order["id"])
    assert quoted["estimate_total"] == 54.80


def test_deposit_min_floor_applied_when_pct_amount_below_minimum(api):
    """PRD §3.4: "Multiply `estimate_total` by the resulting fraction and round to
    two decimal places to obtain a raw deposit, then take the larger of a minimum
    deposit of 25.00 dollars and that raw figure."

    Design: Corner/calculations/deposit_min_floor_applied_when_pct_amount_below_minimum
    """
    cust, order, line = setup_order_with_line(deposit_pct=0.30, measure_dims=(8, 10))
    quoted = quote(order["id"])
    assert quoted["deposit_required"] == 25.00


def test_turnaround_rush_halves_base_days(api):
    """PRD §3.4: "Begin from a base turnaround of 14 days. If `rush_requested` is
    true, replace the base with the base divided by two and rounded up to a whole
    number (so 14 becomes 7)."

    Design: Corner/calculations/turnaround_rush_halves_base_days
    """
    cust, order, line = setup_order_with_line(rush_requested=True, measure_dims=(8, 10))
    quoted = quote(order["id"])
    assert quoted["turnaround_days"] == 7


def test_turnaround_fragile_adds_extra_days(api):
    """PRD §3.4: "Begin from a base turnaround of 14 days. ... If the order has a
    fragile line, add a further 5 fragile-handling days to the running figure."
    PRD §2.9: "An order is considered to contain fragile work ... when at least one
    of its frame lines that is not voided either is mounted behind `MUSEUM` glass or
    carries an explicit `is_fragile` mark of true."

    Design: Corner/calculations/turnaround_fragile_adds_extra_days
    """
    cust, order, line = setup_order_with_line(
        deposit_pct=0.50, measure_dims=(16, 20),
        line_overrides={"glass_type": "MUSEUM", "molding_rate_per_ui": 0.45,
                        "nominal_width_in": 16, "nominal_height_in": 20})
    quoted = quote(order["id"])
    assert quoted["has_fragile_line"] is True
    assert quoted["turnaround_days"] == 19


def test_quote_input_set_excludes_void_lines(api):
    """PRD §3.4: "The **estimate total** ... is computed over the order's non-voided
    frame lines ordered by `created_at` ascending, using each line's nominal
    `estimate_subtotal`."
    PRD §3.2: "A voided line is excluded from every total and from the fragility
    determination."

    Design: Corner/calculations/quote_input_set_excludes_void_lines
    """
    cust = create_customer()
    order = create_order(cust["id"])
    keep = add_line(order["id"], order["version"], artwork_label="Keep",
                    nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    refreshed = get_success_data(api.get_order(order["id"], DESIGNER))
    drop = add_line(order["id"], refreshed["version"], artwork_label="Drop",
                    nominal_width_in=9, nominal_height_in=12, molding_rate_per_ui=0.30)
    get_success_data(api.void_frame_line(drop["id"], DESIGNER))
    measure_line(keep["id"], 8, 10)
    quoted = quote(order["id"])
    assert quoted["estimate_total"] == 64.47


# ===========================================================================
# Corner: consistency_model / immediate
# ===========================================================================
def test_immediate_consistency_estimate_visible_in_quote_response(api):
    """PRD §3.4: "The **estimate total**, stored in `estimate_total`, is computed
    over the order's non-voided frame lines ordered by `created_at` ascending, using
    each line's nominal `estimate_subtotal`."

    Design: Corner/consistency_model/immediate_consistency_estimate_visible_in_quote_response
    """
    cust = create_customer(loyalty_tier="STANDARD", email="imm2@x.com")
    order = create_order(cust["id"], rush_requested=True, deposit_pct=0.30)
    line = add_line(order["id"], order["version"], artwork_label="Im2",
                    nominal_width_in=16, nominal_height_in=20, molding_rate_per_ui=0.45,
                    mat_border_in=2, mat_layers=2, glass_type="CONSERVATION",
                    mounting_type="DRY_MOUNT", conservation_package=True)
    measure_line(line["id"], 16, 20)
    quoted = quote(order["id"])  # quote response itself carries estimate_total
    assert quoted["estimate_total"] == 211.37
