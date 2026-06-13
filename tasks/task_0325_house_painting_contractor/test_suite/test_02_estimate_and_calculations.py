"""Material & labor estimation, rounding order, gallon/weather boundaries.

Covers the per-line-item gallon ceiling, per-line-then-sum labor rounding, tiered
prep multipliers, the exact-coverage gallon boundary, the exterior-weather
suitability threshold, and immediate visibility of the frozen estimate.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    create_product, create_project, add_surface,
    find_line_item_for_surface,
    TEST_DEFAULTS,
)


# ─── combinatorial_formula: material gallons ceil (mode a) ────────────────

def test_material_gallons_ceil_nonlinear_three_inputs(api):
    """PRD §3.2: "The gallons required is the surface's area in square feet multiplied
    by its number of coats, divided by the product's coverage per gallon per coat, with
    the quotient rounded up to the next whole gallon."
    PRD §3.2: "The material cost in cents is that whole-gallon count multiplied by the
    product's price per gallon in cents."

    Design: Difficulty/combinatorial_formula/material_gallons_ceil_three_input_nonlinear
    """
    product = create_product()  # price 4000, coverage 350
    project = create_project()
    surface = add_surface(project["id"], product["id"], label="Great Room",
                          area_sqft=600, coats=2, prep_level="STANDARD")
    li = find_line_item_for_surface(project["id"], surface["id"])
    assert li is not None, "line item must be auto-created for the surface"
    # 600 * 2 / 350 = 3.43 -> ceil -> 4 gallons; 4 * 4000 = 16000
    assert li["gallons_required"] == 4
    assert li["material_cost_cents"] == 16000


def test_material_cost_is_gallons_times_price(api):
    """PRD §3.2: "The material cost in cents is that whole-gallon count multiplied by the
    product's price per gallon in cents. Because the gallon count is always a whole number
    and the price is in whole cents, the material cost is an exact integer."

    Design: Difficulty/combinatorial_formula/material_gallons_ceil_three_input_nonlinear
    """
    product = create_product()  # price 4000, coverage 350
    project = create_project()
    # S1 default: 120 * 1 / 350 = 0.34 -> ceil -> 1 gallon; 1 * 4000 = 4000.
    surface = add_surface(project["id"], product["id"])
    li = find_line_item_for_surface(project["id"], surface["id"])
    assert li["gallons_required"] == 1
    assert li["material_cost_cents"] == TEST_DEFAULTS["S1_MATERIAL_CENTS"]


# ─── combinatorial_formula: project labor rounding order (mode b) ─────────

def test_estimate_labor_rounds_per_line_then_sums(api):
    """PRD §3.3: "two `LIGHT` line items with raw labor of 4912.5 and 8187.5 round to
    4913 and 8188 and sum to 13101, whereas summing the raw values to 13100.0 and rounding
    once would give 13100 — a one-cent difference that the per-line-item-then-sum rule
    deliberately avoids."

    Design: Difficulty/combinatorial_formula/project_labor_rounding_order_per_line_then_sum
    """
    product = create_product()
    project = create_project()
    add_surface(project["id"], product["id"], label="Bedroom",
                area_sqft=120, coats=1, prep_level="LIGHT")
    add_surface(project["id"], product["id"], label="Hall",
                area_sqft=100, coats=2, prep_level="LIGHT")
    finalized = validate_success(api.finalize_estimate(project["id"], _est()), 200)
    assert finalized["estimate_labor_cents"] == 13101
    assert finalized["estimate_material_cents"] == 8000
    assert finalized["estimate_total_cents"] == 21101


def test_estimate_total_is_material_plus_labor(api):
    """PRD §3.3: "the system sets `estimate_material_cents` to the sum of the line items'
    material costs, `estimate_labor_cents` to the sum of their labor costs (each labor cost
    having already been rounded to whole cents per line item before summing), and
    `estimate_total_cents` to the sum of those two components."

    Design: Difficulty/combinatorial_formula/project_labor_rounding_order_per_line_then_sum
    """
    product = create_product()
    project = create_project()
    add_surface(project["id"], product["id"], label="Bedroom",
                area_sqft=120, coats=1, prep_level="LIGHT")
    add_surface(project["id"], product["id"], label="Hall",
                area_sqft=100, coats=2, prep_level="LIGHT")
    finalized = validate_success(api.finalize_estimate(project["id"], _est()), 200)
    assert finalized["estimate_total_cents"] == (
        finalized["estimate_material_cents"] + finalized["estimate_labor_cents"]
    )
    assert finalized["estimate_total_cents"] == 21101


# ─── boundary_precision_check: gallons ceil at exact coverage ─────────────

def test_gallons_at_exact_coverage_boundary(api):
    """PRD §3.2: "The gallons required is the surface's area in square feet multiplied by
    its number of coats, divided by the product's coverage per gallon per coat, with the
    quotient rounded up to the next whole gallon."

    Design: Difficulty/boundary_precision_check/gallons_ceil_at_exact_coverage_boundary
    """
    product = create_product()  # coverage 350
    project = create_project()
    # 700 * 1 / 350 = 2.0 exactly -> 2 gallons.
    s_exact = add_surface(project["id"], product["id"], label="Exact",
                          area_sqft=700, coats=1, prep_level="LIGHT")
    li = find_line_item_for_surface(project["id"], s_exact["id"])
    assert li["gallons_required"] == 2


def test_gallons_just_over_coverage_boundary(api):
    """PRD §3.2: "...divided by the product's coverage per gallon per coat, with the
    quotient rounded up to the next whole gallon."

    Design: Difficulty/boundary_precision_check/gallons_ceil_at_exact_coverage_boundary
    """
    product = create_product()  # coverage 350
    project = create_project()
    # 701 * 1 / 350 = 2.0028 -> ceil -> 3 gallons.
    s_over = add_surface(project["id"], product["id"], label="Over",
                         area_sqft=701, coats=1, prep_level="LIGHT")
    li = find_line_item_for_surface(project["id"], s_over["id"])
    assert li["gallons_required"] == 3


def test_gallons_just_under_coverage_boundary(api):
    """PRD §3.2: "The gallons required is the surface's area in square feet multiplied by
    its number of coats, divided by the product's coverage per gallon per coat, with the
    quotient rounded up to the next whole gallon."

    Design: Difficulty/boundary_precision_check/gallons_ceil_at_exact_coverage_boundary
    """
    product = create_product()  # coverage 350
    project = create_project()
    # 699 * 1 / 350 = 1.997 -> ceil -> 2 gallons (still 2, one below exact 700).
    s_under = add_surface(project["id"], product["id"], label="Under",
                          area_sqft=699, coats=1, prep_level="LIGHT")
    li = find_line_item_for_surface(project["id"], s_under["id"])
    assert li["gallons_required"] == 2


# ─── corner: labor tiered prep multiplier (RESTORATION) ───────────────────

def test_labor_estimate_restoration_prep_factor(api):
    """PRD §3.2: "The prep factor is 1.0 for `LIGHT`, 1.25 for `STANDARD`, 1.6 for
    `HEAVY`, and 2.0 for `RESTORATION`."
    PRD §3.2: "The labor cost in cents is the labor hours multiplied by a fixed labor rate
    of 6550 cents per hour, then rounded half-up to whole cents."

    Design: Corner/calculations/labor_estimate_tiered_prep_multiplier_restoration
    """
    product = create_product()
    project = create_project()
    # 160 sqft * 1 coat * 2.0 / 160 = 2.0 hours; 2.0 * 6550 = 13100 cents exactly.
    surface = add_surface(project["id"], product["id"], label="Old Trim",
                          area_sqft=160, coats=1, prep_level="RESTORATION")
    li = find_line_item_for_surface(project["id"], surface["id"])
    assert li["labor_cost_cents"] == 13100


# ─── corner: weather suitability threshold at MIN temp boundary ───────────

def test_weather_suitable_at_min_temp_boundary(api, project_manager_headers):
    """PRD §3.1: "a window is suitable for exterior work exactly when its forecast
    temperature is at least 50 degrees Fahrenheit **and** its precipitation probability is
    at most 30 percent. A forecast of exactly 50 degrees is suitable; 49 is not. A
    precipitation probability of exactly 30 percent is suitable; 31 is not."

    Design: Corner/calculations/weather_suitability_threshold_at_min_temp_boundary
    """
    res = api.create_weather_window(
        {"window_date": "2026-03-20", "forecast_temp_f": 50, "precipitation_pct": 30},
        project_manager_headers,
    )
    window = validate_success(res, 201)
    assert window["exterior_suitable"] is True


# ─── corner: consistency_model — immediate visibility in finalize response ─

def test_finalize_response_carries_computed_estimate(api):
    """PRD §3.3: "the system sets ... `estimate_total_cents` to the sum of those two
    components."
    PRD §3.3: "Finally `workflow_status` advances from `DRAFT` to `ESTIMATED`."

    Design: Corner/consistency_model/immediate_estimate_visible_in_finalize_response
    """
    product = create_product()
    project = create_project()
    add_surface(project["id"], product["id"])  # S1 -> estimate_total 8913
    finalized = validate_success(api.finalize_estimate(project["id"], _est()), 200)
    assert finalized["estimate_total_cents"] == TEST_DEFAULTS["S1_TOTAL_CENTS"]
    assert finalized["workflow_status"] == "ESTIMATED"


# ─── helper ───────────────────────────────────────────────────────────────

def _est():
    from test_helpers import TEST_USERS
    return TEST_USERS["estimator_headers"]
