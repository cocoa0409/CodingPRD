"""Estimate pricing: provisional vs measured divergence, pinned rounding order,
the non-linear waste factor, and the big-area surcharge boundary.

Literal expected values are copied verbatim from the design indices.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client,
    assert_estimate, assert_estimate_total_consistent,
    create_estimate_payload, measure_payload, issue_payload,
    create_draft_job, create_measured_job, create_measured_estimate,
    make_sales_rep_headers,
    TEST_USERS,
)


# ─── Dual-variant: PROVISIONAL vs MEASURED diverge on the same job ─────

def test_provisional_estimate_prices_off_declared_no_waste(api):
    """PRD §3.2: "A provisional estimate prices off the declared area with no
    waste factor and no tear-out labor: its `billable_sqft` is exactly the job's
    `declared_sqft`; its `material_cost_cents` is `declared_sqft` multiplied by
    the product's per-square-foot material rate, rounded to whole cents half up".

    Design: Difficulty/dual_variant_calc/estimate_provisional_vs_measured_diverge_on_same_job
    """
    # LVP material 320c, labor 250c, underlayment 40c (required), declared 500.
    customer, sales_rep, product, job = create_draft_job(
        declared_sqft=500,
        product_overrides={"sku": "LVP-A1", "category": "LVP",
                           "material_cost_per_sqft_cents": 320,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 40,
                           "lead_time_days": 7, "warranty_years": 15},
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    prov = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="PROVISIONAL"), rep_headers))
    assert_estimate(prov)
    assert prov["variant"] == "PROVISIONAL"
    assert prov["total_cents"] == 305000


def test_measured_estimate_diverges_from_provisional_on_same_job(api):
    """PRD §3.5: "The `billable_sqft` is the measured area inflated by the waste
    factor — measured square footage multiplied by one plus `waste_factor_pct`
    divided by 100 — and that billable area is rounded to two decimal places
    (half up) before any cost is computed."

    Design: Difficulty/dual_variant_calc/estimate_provisional_vs_measured_diverge_on_same_job
    """
    customer, sales_rep, product, job = create_draft_job(
        declared_sqft=500,
        product_overrides={"sku": "LVP-A1", "category": "LVP",
                           "material_cost_per_sqft_cents": 320,
                           "labor_rate_per_sqft_cents": 250,
                           "requires_underlayment": True,
                           "underlayment_cost_per_sqft_cents": 40,
                           "lead_time_days": 7, "warranty_years": 15},
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    prov = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="PROVISIONAL"), rep_headers))
    job = get_success_data(api.measure_job(
        job["id"], measure_payload(measured_sqft=520, tear_out_sqft=100, room_count=3),
        TEST_USERS["estimator_headers"]))
    meas = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="MEASURED"), rep_headers))
    assert meas["variant"] == "MEASURED"
    assert meas["billable_sqft"] == 572.0
    assert meas["total_cents"] == 350920
    assert meas["total_cents"] != prov["total_cents"]


# ─── Combinatorial: pinned round-per-line-then-sum (mode b) ───────────

def test_measured_estimate_rounding_order_pinned_lines(api):
    """PRD §3.5: "A measured estimate prices off the measured geometry, the waste
    factor, and the tear-out labor, with the rounding order pinned: each line item
    is rounded to whole cents first, and only then are the lines summed."
    PRD §3.5: "The `material_cost_cents` is `billable_sqft` multiplied by the
    product's per-square-foot material rate, rounded to whole cents half up."

    Design: Difficulty/combinatorial_formula/estimate_total_rounding_order_mode_b
    """
    # CARPET material 50c, labor 51c, no underlayment; measured 110.5, 1 room.
    customer, sales_rep, product, job, est = create_measured_estimate(
        declared_sqft=110, measured_sqft=110.5, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "CARP-R", "category": "CARPET",
                           "material_cost_per_sqft_cents": 50,
                           "labor_rate_per_sqft_cents": 51,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 5},
    )
    assert est["billable_sqft"] == 116.03
    assert est["material_cost_cents"] == 5802
    assert est["labor_cost_cents"] == 5636
    assert est["total_cents"] == 11438


def test_measured_estimate_total_is_sum_of_rounded_lines(api):
    """PRD §3.5: "the `total_cents` is the sum of the rounded material,
    underlayment, and labor lines."

    Design: Difficulty/combinatorial_formula/estimate_total_rounding_order_mode_b
    """
    customer, sales_rep, product, job, est = create_measured_estimate(
        declared_sqft=110, measured_sqft=110.5, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "CARP-R2", "category": "CARPET",
                           "material_cost_per_sqft_cents": 50,
                           "labor_rate_per_sqft_cents": 51,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 5},
    )
    assert_estimate_total_consistent(est)
    assert est["total_cents"] == 11438


# ─── Combinatorial: non-linear three-input waste factor (mode a) ──────

def test_waste_factor_combines_base_seam_and_big_area(api):
    """PRD §3.3: "The factor is the sum of three components. First, a category
    base: 10.0 percent for `HARDWOOD`, 8.0 percent for `LVP`, 12.0 percent for
    `TILE`, and 5.0 percent for `CARPET`. Second, a seam allowance for multi-room
    jobs: each room beyond the first adds 1.0 percent ... Third, a large-area
    surcharge: a flat 3.0 percent is added when the product's category is `TILE`
    or `HARDWOOD` and the measured area is strictly greater than 600 square feet".

    Design: Difficulty/combinatorial_formula/waste_factor_nonlinear_three_input_mode_a
    """
    # TILE, 700 sqft, 2 rooms -> 12.0 + 1.0 + 3.0 = 16.0.
    customer, sales_rep, product, job = create_measured_job(
        declared_sqft=700, measured_sqft=700, tear_out_sqft=0, room_count=2,
        product_overrides={"sku": "TILE-1", "category": "TILE",
                           "material_cost_per_sqft_cents": 500,
                           "labor_rate_per_sqft_cents": 400,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 10, "warranty_years": 25},
    )
    assert job["waste_factor_pct"] == 16.0


def test_waste_factor_set_and_job_advances_to_measured(api):
    """PRD §3.3: "Measuring a job in `DRAFT` advances it `DRAFT → MEASURED`".
    PRD §3.3: "The three components are summed and the result is kept to one
    decimal place, rounded half up."

    Design: Difficulty/combinatorial_formula/waste_factor_nonlinear_three_input_mode_a
    """
    customer, sales_rep, product, job = create_measured_job(
        declared_sqft=700, measured_sqft=700, tear_out_sqft=0, room_count=2,
        product_overrides={"sku": "TILE-1B", "category": "TILE",
                           "material_cost_per_sqft_cents": 500,
                           "labor_rate_per_sqft_cents": 400,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 10, "warranty_years": 25},
    )
    assert job["status"] == "MEASURED"
    assert job["waste_factor_pct"] == 16.0


# ─── Boundary: big-area surcharge strict > 600 ────────────────────────

def test_big_area_surcharge_not_triggered_at_exactly_600(api):
    """PRD §3.3: "a flat 3.0 percent is added when the product's category is
    `TILE` or `HARDWOOD` and the measured area is strictly greater than 600 square
    feet; an area of exactly 600 does not trigger it".

    Design: Difficulty/boundary_precision_check/big_area_surcharge_strict_greater_than_600_on_measure
    """
    # HARDWOOD at exactly 600 -> base 10.0 only, no surcharge.
    customer, sales_rep, product, job = create_measured_job(
        declared_sqft=600, measured_sqft=600, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "HW-E-600", "category": "HARDWOOD",
                           "material_cost_per_sqft_cents": 600,
                           "labor_rate_per_sqft_cents": 350,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 5, "warranty_years": 20},
    )
    assert job["waste_factor_pct"] == 10.0


def test_big_area_surcharge_triggered_above_600(api):
    """PRD §3.3: "a flat 3.0 percent is added when the product's category is
    `TILE` or `HARDWOOD` and the measured area is strictly greater than 600 square
    feet; an area of exactly 600 does not trigger it".

    Design: Difficulty/boundary_precision_check/big_area_surcharge_strict_greater_than_600_on_measure
    """
    # HARDWOOD at 601 -> base 10.0 + surcharge 3.0 = 13.0.
    customer, sales_rep, product, job = create_measured_job(
        declared_sqft=601, measured_sqft=601, tear_out_sqft=0, room_count=1,
        product_overrides={"sku": "HW-E-601", "category": "HARDWOOD",
                           "material_cost_per_sqft_cents": 600,
                           "labor_rate_per_sqft_cents": 350,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 5, "warranty_years": 20},
    )
    assert job["waste_factor_pct"] == 13.0


# ─── Calculation corner instances ─────────────────────────────────────

def test_provisional_estimate_no_waste_no_tearout(api):
    """PRD §3.2: "its `material_cost_cents` is `declared_sqft` multiplied by the
    product's per-square-foot material rate, rounded to whole cents half up; ...
    its `labor_cost_cents` is `declared_sqft` multiplied by the product's
    per-square-foot labor rate, rounded to whole cents half up; and its
    `total_cents` is the sum of those three rounded line items."

    Design: Corner/calculations/provisional_estimate_correct_no_waste_no_tearout
    """
    # HARDWOOD material 600c, labor 350c, no underlayment, declared 300.
    customer, sales_rep, product, job = create_draft_job(
        declared_sqft=300,
        product_overrides={"sku": "PROV-1", "category": "HARDWOOD",
                           "material_cost_per_sqft_cents": 600,
                           "labor_rate_per_sqft_cents": 350,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 5, "warranty_years": 20},
    )
    rep_headers = make_sales_rep_headers(sales_rep["id"])
    est = get_success_data(api.create_estimate(
        create_estimate_payload(job["id"], variant="PROVISIONAL"), rep_headers))
    assert est["material_cost_cents"] == 180000
    assert est["labor_cost_cents"] == 105000
    assert est["total_cents"] == 285000


def test_waste_seam_allowance_caps_at_six_pct(api):
    """PRD §3.3: "each room beyond the first adds 1.0 percent — that is, one less
    than `room_count`, multiplied by 1.0 — but this seam allowance is capped so it
    can never exceed 6.0 percent."

    Design: Corner/calculations/waste_seam_cap_at_six_pct
    """
    # CARPET base 5.0 + capped seam 6.0 = 11.0 with 9 rooms.
    customer, sales_rep, product, job = create_measured_job(
        declared_sqft=200, measured_sqft=200, tear_out_sqft=0, room_count=9,
        product_overrides={"sku": "SEAM-1", "category": "CARPET",
                           "material_cost_per_sqft_cents": 100,
                           "labor_rate_per_sqft_cents": 100,
                           "requires_underlayment": False,
                           "underlayment_cost_per_sqft_cents": 0,
                           "lead_time_days": 0, "warranty_years": 5},
    )
    assert job["waste_factor_pct"] == 11.0
