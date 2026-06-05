"""Retail sales: flower-equivalent math, per-customer daily limits, age
verification, lab-hold gating, and finalize lockdown."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_retail_license, create_cultivation_license, create_testing_license,
    create_active_package, create_customer, open_sale, add_sale_line,
    open_sale_with_line, finalize_sale, setup_retail_scenario,
    create_cured_harvest, create_package,
    bud_h, cult_h,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Rule 1 (dual_variant_calc): adult vs medical daily-limit divergence
# ---------------------------------------------------------------------------
def test_daily_limit_rejects_adult_at_29g(api):
    """PRD §3.7: "If the projected same-day total is strictly greater than that
    limit, finalize is rejected with `ERR_DAILY_LIMIT_EXCEEDED`; a projection
    exactly equal to the limit passes."
    PRD §3.7: "The customer's limit is the retail license's
    `daily_purchase_limit_grams`, multiplied by 3 for a medical customer (when
    `is_medical` is true) and by 1 for an adult-use customer."

    Design: Difficulty/dual_variant_calc/daily_limit_adult_vs_medical_diverge
    """
    ret = create_retail_license(daily_purchase_limit_grams=28.5)
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=200,
                                product_category="FLOWER")
    adult = create_customer(is_medical=False, birthdate="1990-01-01T00:00:00Z")
    sale = open_sale_with_line(ret["id"], adult["id"], pkg["id"], 29.0,
                               sale_date="2026-06-01T00:00:00Z")
    assert sale["flower_equiv_grams"] == 29.0
    resp = finalize_sale(sale["id"], expected_version=sale["version"])
    validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)


def test_daily_limit_passes_medical_at_29g(api):
    """PRD §3.7: "The customer's limit is the retail license's
    `daily_purchase_limit_grams`, multiplied by 3 for a medical customer (when
    `is_medical` is true) and by 1 for an adult-use customer."

    Design: Difficulty/dual_variant_calc/daily_limit_adult_vs_medical_diverge
    """
    ret = create_retail_license(daily_purchase_limit_grams=28.5)
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=200,
                                product_category="FLOWER")
    medical = create_customer(is_medical=True, birthdate="1990-01-01T00:00:00Z",
                              medical_card_number="MED-1")
    sale = open_sale_with_line(ret["id"], medical["id"], pkg["id"], 29.0,
                               sale_date="2026-06-01T00:00:00Z")
    assert sale["flower_equiv_grams"] == 29.0
    resp = finalize_sale(sale["id"], expected_version=sale["version"])
    data = validate_success(resp)
    assert data["status"] == "FINALIZED", "29.0 <= 85.5 (28.5*3) must finalize"


# ---------------------------------------------------------------------------
# Rule 2 (combinatorial_formula): round-per-line-then-sum
# ---------------------------------------------------------------------------
def test_flower_equiv_each_edible_line_rounds_to_026(api):
    """PRD §3.7: "Each line computes its own `flower_equiv_grams`: the dispensed
    `grams` multiplied by the flower-equivalent factor for the package's
    `product_category`, where `FLOWER` weighs 1.0, `CONCENTRATE` weighs 5.0, and
    `EDIBLE` weighs 0.1, with that product rounded to 2 decimal places using
    round-half-up."

    Design: Difficulty/combinatorial_formula/flower_equiv_round_per_line_then_sum
    """
    scn = setup_retail_scenario(is_medical=False, product_category="EDIBLE",
                                package_quantity=100, thc_pct=10.0)
    sale = open_sale(scn["ret"]["id"], scn["customer"]["id"],
                     sale_date="2026-06-01T00:00:00Z")
    line = add_sale_line(sale["id"], scn["package"]["id"], 2.55)
    # 2.55 * 0.1 = 0.255 -> round-half-up to 0.26
    assert line["flower_equiv_grams"] == 0.26


def test_flower_equiv_sale_total_is_round_then_sum(api):
    """PRD §3.7: "The sale's aggregate `flower_equiv_grams` is the sum of the
    already-rounded per-line values, that sum itself rounded to 2 decimal places
    — the rounding is applied per line first and only then summed, never the
    reverse."

    Design: Difficulty/combinatorial_formula/flower_equiv_round_per_line_then_sum
    """
    scn = setup_retail_scenario(is_medical=False, product_category="EDIBLE",
                                package_quantity=100, thc_pct=10.0)
    sale = open_sale(scn["ret"]["id"], scn["customer"]["id"],
                     sale_date="2026-06-01T00:00:00Z")
    add_sale_line(sale["id"], scn["package"]["id"], 2.55)
    add_sale_line(sale["id"], scn["package"]["id"], 2.55)
    data = validate_success(api.get_sale(sale["id"], bud_h()))
    # round-then-sum: 0.26 + 0.26 = 0.52 (NOT sum-then-round 0.51)
    assert data["flower_equiv_grams"] == 0.52


# ---------------------------------------------------------------------------
# Rule 2 (combinatorial_formula): multifactor non-linear selection (CONCENTRATE)
# ---------------------------------------------------------------------------
def test_concentrate_17g_passes_medical_limit(api):
    """PRD §3.7: "where `FLOWER` weighs 1.0, `CONCENTRATE` weighs 5.0, and
    `EDIBLE` weighs 0.1"
    PRD §3.7: "a projection exactly equal to the limit passes."

    Design: Difficulty/combinatorial_formula/daily_limit_multifactor_nonlinear_selection
    """
    ret = create_retail_license(daily_purchase_limit_grams=28.5)
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100,
                                product_category="CONCENTRATE", thc_pct=70.0)
    cust = create_customer(is_medical=True, birthdate="1990-01-01T00:00:00Z",
                           medical_card_number="MED-2")
    sale = open_sale_with_line(ret["id"], cust["id"], pkg["id"], 17.0,
                               sale_date="2026-06-03T00:00:00Z")
    assert sale["flower_equiv_grams"] == 85.0  # 17.0 * 5.0
    resp = finalize_sale(sale["id"], expected_version=sale["version"])
    data = validate_success(resp)
    assert data["status"] == "FINALIZED", "85.0 <= medical limit 85.5 must finalize"


def test_concentrate_172g_exceeds_medical_limit(api):
    """PRD §3.7: "If the projected same-day total is strictly greater than that
    limit, finalize is rejected with `ERR_DAILY_LIMIT_EXCEEDED`; a projection
    exactly equal to the limit passes."

    Design: Difficulty/combinatorial_formula/daily_limit_multifactor_nonlinear_selection
    """
    ret = create_retail_license(daily_purchase_limit_grams=28.5)
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100,
                                product_category="CONCENTRATE", thc_pct=70.0)
    cust = create_customer(is_medical=True, birthdate="1990-01-01T00:00:00Z",
                           medical_card_number="MED-2")
    sale = open_sale_with_line(ret["id"], cust["id"], pkg["id"], 17.2,
                               sale_date="2026-06-04T00:00:00Z")
    assert sale["flower_equiv_grams"] == 86.0  # 17.2 * 5.0
    resp = finalize_sale(sale["id"], expected_version=sale["version"])
    validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Rule 6 (boundary_precision_check): daily-limit equal-boundary passes
# ---------------------------------------------------------------------------
def test_daily_limit_exact_boundary_finalizes(api):
    """PRD §3.7: "a projection exactly equal to the limit passes."

    Design: Difficulty/boundary_precision_check/daily_limit_equal_boundary_passes
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=200)
    sale = open_sale_with_line(scn["ret"]["id"], scn["customer"]["id"],
                               scn["package"]["id"], 28.5,
                               sale_date="2026-06-07T00:00:00Z")
    resp = finalize_sale(sale["id"], expected_version=sale["version"])
    data = validate_success(resp)
    assert data["status"] == "FINALIZED", "projected 28.5 == limit 28.5 passes"


def test_daily_limit_just_over_boundary_rejected(api):
    """PRD §3.7: "If the projected same-day total is strictly greater than that
    limit, finalize is rejected with `ERR_DAILY_LIMIT_EXCEEDED`; a projection
    exactly equal to the limit passes."

    Design: Difficulty/boundary_precision_check/daily_limit_equal_boundary_passes
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=200)
    sale = open_sale_with_line(scn["ret"]["id"], scn["customer"]["id"],
                               scn["package"]["id"], 28.51,
                               sale_date="2026-06-07T00:00:00Z")
    resp = finalize_sale(sale["id"], expected_version=sale["version"])
    validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Corner: concentrate factor applied per line
# ---------------------------------------------------------------------------
def test_concentrate_line_flower_equiv_factor(api):
    """PRD §3.7: "where `FLOWER` weighs 1.0, `CONCENTRATE` weighs 5.0, and
    `EDIBLE` weighs 0.1, with that product rounded to 2 decimal places using
    round-half-up."

    Design: Corner/calculations/flower_equiv_concentrate_factor_applied
    """
    scn = setup_retail_scenario(is_medical=True, product_category="CONCENTRATE",
                                package_quantity=100, thc_pct=60.0)
    sale = open_sale(scn["ret"]["id"], scn["customer"]["id"],
                     sale_date="2026-06-13T00:00:00Z")
    line = add_sale_line(sale["id"], scn["package"]["id"], 2.0)
    assert line["flower_equiv_grams"] == 10.0  # 2.0 * 5.0


# ---------------------------------------------------------------------------
# Corner: daily-limit window excludes VOIDED sales
# ---------------------------------------------------------------------------
def test_daily_limit_excludes_voided_sale(api):
    """PRD §3.7: "the system gathers all of the customer's `FINALIZED` sales for
    the same `customer_id` and the same `sale_date`, sums their
    `flower_equiv_grams` to obtain the prior total (open and voided sales are
    excluded)"

    Design: Corner/calculations/daily_limit_excludes_voided_sales
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=200)
    ret_id, cust_id, pkg_id = scn["ret"]["id"], scn["customer"]["id"], scn["package"]["id"]
    # A prior VOIDED 20g sale on the same date must not count.
    void_sale = open_sale(ret_id, cust_id, sale_date="2026-06-14T00:00:00Z")
    add_sale_line(void_sale["id"], pkg_id, 20.0)
    validate_success(api.void_sale(void_sale["id"], bud_h()))
    # Fresh 28.5g sale same date should still pass at the boundary.
    sale = open_sale_with_line(ret_id, cust_id, pkg_id, 28.5,
                               sale_date="2026-06-14T00:00:00Z")
    resp = finalize_sale(sale["id"], expected_version=sale["version"])
    data = validate_success(resp)
    assert data["status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Corner: lab-hold blocks sale line
# ---------------------------------------------------------------------------
def test_sale_line_for_lab_held_package_rejected(api):
    """PRD §3.7: "the dispensed package must not be on lab hold — a package with
    `lab_hold` true cannot be sold and triggers `ERR_LAB_HOLD_ACTIVE`."

    Design: Corner/validations/sell_package_under_lab_hold_rejected
    """
    ret = create_retail_license(daily_purchase_limit_grams=28.5)
    cul = create_cultivation_license()
    harvest = create_cured_harvest(cul["id"], dry_weight_grams=500)
    pkg = create_package(harvest["id"], quantity_grams=50)  # still TESTING, lab_hold true
    cust = create_customer(is_medical=False)
    sale = open_sale(ret["id"], cust["id"], sale_date="2026-06-15T00:00:00Z")
    resp = api.add_sale_line(sale["id"], {"package_id": pkg["id"], "grams": 5.0}, bud_h())
    validate_error(resp, ApiErrorId.ERR_LAB_HOLD_ACTIVE.value)


# ---------------------------------------------------------------------------
# Corner: age verification on finalize
# ---------------------------------------------------------------------------
def test_underage_customer_finalize_rejected(api):
    """PRD §3.7: "the customer must be at least 21 years old at the `sale_date`,
    computed from the customer's `birthdate`; a customer below that age is
    rejected with `ERR_AGE_VERIFICATION_FAILED`, and this safety check is
    evaluated before the fiscal daily-limit check."

    Design: Corner/validations/age_verification_failed_on_finalize
    """
    ret = create_retail_license(daily_purchase_limit_grams=28.5)
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=50,
                                product_category="FLOWER")
    minor = create_customer(is_medical=False, birthdate="2010-01-01T00:00:00Z")
    sale = open_sale_with_line(ret["id"], minor["id"], pkg["id"], 5.0,
                               sale_date="2026-06-16T00:00:00Z")
    resp = finalize_sale(sale["id"], expected_version=sale["version"])
    validate_error(resp, ApiErrorId.ERR_AGE_VERIFICATION_FAILED.value)


# ---------------------------------------------------------------------------
# Corner: finalize already-finalized sale rejected
# ---------------------------------------------------------------------------
def test_finalize_already_finalized_sale_rejected(api):
    """PRD §3.7: "Finalizing a sale moves it from `OPEN` to the terminal
    `FINALIZED` state"
    PRD §2.11: "the target resource must be in a legal state for the requested
    transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/finalize_already_finalized_sale_rejected
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=200)
    sale = open_sale_with_line(scn["ret"]["id"], scn["customer"]["id"],
                               scn["package"]["id"], 5.0,
                               sale_date="2026-06-12T00:00:00Z")
    first = validate_success(finalize_sale(sale["id"], expected_version=sale["version"]))
    assert first["status"] == "FINALIZED"
    # Second finalize against the now-terminal sale.
    resp2 = finalize_sale(sale["id"], expected_version=first["version"])
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_sale(sale["id"], bud_h()))
    assert after["status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Rule 8 (resource_temporal_overlap): one OPEN sale per customer per day
# ---------------------------------------------------------------------------
def test_second_open_sale_same_customer_same_day_rejected(api):
    """PRD §3.7: "A customer may have at most one open sale per retail license
    per `sale_date`; opening a second overlapping same-day sale window for that
    customer at that license is rejected with `ERR_SALE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/customer_single_open_sale_same_day
    """
    ret = create_retail_license(daily_purchase_limit_grams=28.5)
    cust = create_customer(is_medical=False, birthdate="1990-01-01T00:00:00Z")
    open_sale(ret["id"], cust["id"], sale_date="2026-06-10T00:00:00Z")
    resp = api.create_sale({
        "retail_license_id": ret["id"], "customer_id": cust["id"],
        "sale_date": "2026-06-10T00:00:00Z",
    }, bud_h())
    validate_error(resp, ApiErrorId.ERR_SALE_WINDOW_OVERLAP.value)


def test_first_open_sale_same_day_succeeds_then_blocks(api):
    """PRD §3.7: "A sale is born in `OPEN` status with its `flower_equiv_grams`
    at 0. A customer may have at most one open sale per retail license per
    `sale_date`; opening a second overlapping same-day sale window for that
    customer at that license is rejected with `ERR_SALE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/customer_single_open_sale_same_day
    """
    ret = create_retail_license(daily_purchase_limit_grams=28.5)
    cust = create_customer(is_medical=False, birthdate="1990-01-01T00:00:00Z")
    first = validate_success(api.create_sale({
        "retail_license_id": ret["id"], "customer_id": cust["id"],
        "sale_date": "2026-06-10T00:00:00Z",
    }, bud_h()), 201)
    assert first["status"] == "OPEN"
    # Second same-day open for the same customer at the same license is blocked.
    resp = api.create_sale({
        "retail_license_id": ret["id"], "customer_id": cust["id"],
        "sale_date": "2026-06-10T00:00:00Z",
    }, bud_h())
    validate_error(resp, ApiErrorId.ERR_SALE_WINDOW_OVERLAP.value)
