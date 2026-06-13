"""The pricing engine: non-linear line costs, round-per-line tax, slope
threshold boundary, and the empty-estimate guard.

Translates Difficulty/combinatorial_formula and Difficulty/boundary_precision_check.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_customer, create_project,
    create_line_item_payload,
)

PM = TEST_USERS["project_manager_headers"]
EST = TEST_USERS["estimator_headers"]


def _price_single_estimate(api, line_specs, job_type="FENCE", tax_rate_pct=7.25):
    """Helper: customer + project + estimate with line_specs, then PRICE.
    Returns (estimate_after_price, [line_items_after_price])."""
    cust = create_customer()
    proj = create_project(cust["id"], job_type=job_type)
    est = get_success_data(api.create_estimate(proj["id"], {"tax_rate_pct": tax_rate_pct}, EST))
    lis = [get_success_data(api.create_line_item(
        create_line_item_payload(est["id"], **spec), EST)) for spec in line_specs]
    est_after = get_success_data(api.price_estimate(proj["id"], est["id"], EST))
    lis_after = [get_success_data(api.get_line_item(li["id"], EST)) for li in lis]
    return est_after, lis_after


# --- combinatorial_formula instance (a): non-linear line cost (slope + tier + adder)
def test_deck_line_cost_combines_tier_slope_and_accessory(api):
    """PRD §3.2: "The line material cost is therefore the rate multiplied by `quantity_units` multiplied by the slope multiplier, plus the accessory adder, with the whole line rounded half up to 2 decimal places."
    PRD §3.2: "composite standard decking 38.25 per square foot".
    PRD §3.2: "if `grade_slope_pct` is at least 15, the rate is multiplied by 1.12; otherwise the multiplier is 1.00."
    A COMPOSITE/DECK_STANDARD 200 sqft line at slope 20 with STAIR_SET prices to
    line_material_cost 8988.00.

    Design: Difficulty/combinatorial_formula/line_item_estimate_three_input_nonlinear_slope_tier
    """
    est, lis = _price_single_estimate(api, [dict(
        work_type="DECK", material="COMPOSITE", style="DECK_STANDARD",
        quantity_units=200, accessory="STAIR_SET", grade_slope_pct=20)], job_type="DECK")
    assert lis[0]["line_material_cost"] == 8988.00
    assert est["status"] == "PRICED"


def test_deck_line_cost_status_priced_after_combinatorial_price(api):
    """PRD §3.2: "A successful pricing moves the estimate from `DRAFT` to `PRICED`."
    The non-linear deck line (COMPOSITE/DECK_STANDARD 200 sqft, STAIR_SET,
    slope 20) prices to line_material_cost 8988.00.

    Design: Difficulty/combinatorial_formula/line_item_estimate_three_input_nonlinear_slope_tier
    """
    est, lis = _price_single_estimate(api, [dict(
        work_type="DECK", material="COMPOSITE", style="DECK_STANDARD",
        quantity_units=200, accessory="STAIR_SET", grade_slope_pct=20)], job_type="DECK")
    assert est["status"] == "PRICED"
    assert lis[0]["line_material_cost"] == 8988.00


# --- combinatorial_formula instance (b): material_tax round-per-line-then-sum
def test_material_tax_rounds_per_line_then_sums(api):
    """PRD §3.2: "The `material_tax` is computed by taking, for each line, the line's `line_material_cost` multiplied by `tax_rate_pct` divided by 100, rounding that per-line tax to 2 places, and then summing those per-line rounded amounts — the per-line rounding happens before the sum, never after."
    Three identical CEDAR/PRIVACY qty-2 NONE lines (85.00 each): per-line tax
    round(6.1625)=6.16, summed across 3 lines = 18.48.

    Design: Difficulty/combinatorial_formula/estimate_rollup_material_tax_round_per_line_then_sum
    """
    est, _ = _price_single_estimate(api, [
        dict(work_type="FENCE", material="CEDAR", style="PRIVACY",
             quantity_units=2, accessory="NONE", grade_slope_pct=0)] * 3,
        job_type="FENCE")
    assert est["material_subtotal"] == 255.00
    assert est["material_tax"] == 18.48


def test_contract_total_uses_per_line_rounded_tax(api):
    """PRD §3.2: "The estimate's `contract_total` is the sum of `material_subtotal`, `labor_subtotal`, and `material_tax`, rounded to 2 places."
    With per-line rounded tax 18.48, material 255.00, labor
    (3*2*9.50)+650.00 = 707.00, the contract_total is 980.48.

    Design: Difficulty/combinatorial_formula/estimate_rollup_material_tax_round_per_line_then_sum
    """
    est, _ = _price_single_estimate(api, [
        dict(work_type="FENCE", material="CEDAR", style="PRIVACY",
             quantity_units=2, accessory="NONE", grade_slope_pct=0)] * 3,
        job_type="FENCE")
    assert est["material_subtotal"] == 255.00
    assert est["material_tax"] == 18.48
    assert est["contract_total"] == 980.48


# --- boundary_precision_check instance (a): slope threshold at exactly 15
def test_slope_surcharge_applies_at_exactly_15(api):
    """PRD §3.2: "if `grade_slope_pct` is at least 15, the rate is multiplied by 1.12; otherwise the multiplier is 1.00."
    A CEDAR/PRIVACY 100ft NONE line at slope exactly 15 takes the surcharge:
    round(42.50*100*1.12) = 4760.00.

    Design: Difficulty/boundary_precision_check/slope_surcharge_threshold_at_15_exact
    """
    _est, lis = _price_single_estimate(api, [dict(
        work_type="FENCE", material="CEDAR", style="PRIVACY",
        quantity_units=100, accessory="NONE", grade_slope_pct=15)], job_type="FENCE")
    assert lis[0]["line_material_cost"] == 4760.00


def test_slope_surcharge_absent_just_below_15(api):
    """PRD §3.2: "if `grade_slope_pct` is at least 15, the rate is multiplied by 1.12; otherwise the multiplier is 1.00."
    At slope 14 (just below the threshold) the multiplier is 1.00:
    42.50*100 = 4250.00, distinct from the surcharged 4760.00 at slope 15.

    Design: Difficulty/boundary_precision_check/slope_surcharge_threshold_at_15_exact
    """
    _est, lis = _price_single_estimate(api, [dict(
        work_type="FENCE", material="CEDAR", style="PRIVACY",
        quantity_units=100, accessory="NONE", grade_slope_pct=14)], job_type="FENCE")
    assert lis[0]["line_material_cost"] == 4250.00


# --- boundary_precision_check instance (b): empty estimate rejected on price
def test_price_empty_estimate_rejected(api):
    """PRD §3.2: "Pricing requires that the estimate hold at least one line item; pricing an empty estimate is rejected with `ERR_EMPTY_ESTIMATE`."

    Design: Difficulty/boundary_precision_check/empty_estimate_zero_lineitems_rejected_on_price
    """
    cust = create_customer()
    proj = create_project(cust["id"], job_type="FENCE")
    est = get_success_data(api.create_estimate(proj["id"], {}, EST))
    resp = api.price_estimate(proj["id"], est["id"], EST)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ESTIMATE.value)


def test_price_empty_estimate_leaves_status_draft(api):
    """PRD §3.2: "pricing an empty estimate is rejected with `ERR_EMPTY_ESTIMATE`."
    PRD §3.2: "A successful pricing moves the estimate from `DRAFT` to `PRICED`." —
    a rejected price leaves the estimate in DRAFT.

    Design: Difficulty/boundary_precision_check/empty_estimate_zero_lineitems_rejected_on_price
    """
    cust = create_customer()
    proj = create_project(cust["id"], job_type="FENCE")
    est = get_success_data(api.create_estimate(proj["id"], {}, EST))
    resp = api.price_estimate(proj["id"], est["id"], EST)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ESTIMATE.value)
    estimates = get_success_data(api.list_estimates(proj["id"], EST))
    assert estimates[0]["status"] == "DRAFT"
