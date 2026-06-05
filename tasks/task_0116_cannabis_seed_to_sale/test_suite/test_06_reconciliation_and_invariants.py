"""Reconciliation counts (match vs discrepancy, tolerance boundary), plus
inventory-conservation and sale-OCC invariants."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_cultivation_license, create_testing_license,
    create_active_package, setup_retail_scenario,
    open_sale_with_line, finalize_sale, add_sale_line, open_sale,
    record_reconciliation_count,
    cult_h, bud_h, audit_h,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Rule 1 (dual_variant_calc): reconciliation MATCH vs DISCREPANCY
# ---------------------------------------------------------------------------
def test_reconciliation_match_keeps_package_active(api):
    """PRD §3.8: "The outcome is `MATCH` when the absolute value of the variance
    is at or below the tolerance of 0.5 grams (the boundary of exactly 0.5 is a
    match)"
    PRD §3.8: "A `MATCH` leaves the package `ACTIVE` and places no hold."

    Design: Difficulty/dual_variant_calc/reconciliation_match_vs_discrepancy_diverge
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100)
    rc = record_reconciliation_count(pkg["id"], counted_grams=99.5,
                                     counted_at="2026-06-02T00:00:00Z")
    assert rc["outcome"] == "MATCH"  # |99.5 - 100.0| = 0.5 <= 0.5
    data = validate_success(api.get_package(pkg["id"], cult_h()))
    assert data["status"] == "ACTIVE"


def test_reconciliation_discrepancy_holds_package(api):
    """PRD §3.8: "and `DISCREPANCY` when the absolute variance exceeds 0.5
    grams."
    PRD §3.8: "A `DISCREPANCY` drives the package from `ACTIVE` to `ON_HOLD` as
    a cross-entity cascade and increments the package's `version`."

    Design: Difficulty/dual_variant_calc/reconciliation_match_vs_discrepancy_diverge
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100)
    rc = record_reconciliation_count(pkg["id"], counted_grams=99.4,
                                     counted_at="2026-06-02T00:00:00Z")
    assert rc["outcome"] == "DISCREPANCY"  # |99.4 - 100.0| = 0.6 > 0.5
    data = validate_success(api.get_package(pkg["id"], cult_h()))
    assert data["status"] == "ON_HOLD"


# ---------------------------------------------------------------------------
# Rule 6 (boundary_precision_check): tolerance equal-boundary is MATCH
# ---------------------------------------------------------------------------
def test_reconciliation_variance_exactly_half_gram_matches(api):
    """PRD §3.8: "computes the signed `variance_grams` as the counted grams minus
    the expected grams rounded to 2 decimal places"
    PRD §3.8: "The outcome is `MATCH` when the absolute value of the variance is
    at or below the tolerance of 0.5 grams (the boundary of exactly 0.5 is a
    match)"

    Design: Difficulty/boundary_precision_check/recon_tolerance_equal_boundary_matches
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100)
    rc = record_reconciliation_count(pkg["id"], counted_grams=99.5,
                                     counted_at="2026-06-08T00:00:00Z")
    assert rc["variance_grams"] == -0.5
    assert rc["outcome"] == "MATCH"


def test_reconciliation_at_boundary_keeps_active(api):
    """PRD §3.8: "A `MATCH` leaves the package `ACTIVE` and places no hold."

    Design: Difficulty/boundary_precision_check/recon_tolerance_equal_boundary_matches
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(cul["id"], lab["id"], quantity_grams=100)
    record_reconciliation_count(pkg["id"], counted_grams=99.5,
                                counted_at="2026-06-08T00:00:00Z")
    data = validate_success(api.get_package(pkg["id"], cult_h()))
    assert data["status"] == "ACTIVE", "no hold at the inclusive 0.5 boundary"


# ---------------------------------------------------------------------------
# Rule 9 (compensating_invariant): sale void conserves package remaining
# ---------------------------------------------------------------------------
def test_void_open_sale_leaves_package_remaining_unchanged(api):
    """PRD §3.7: "A `Budtender` may instead void an `OPEN` sale, moving it to the
    terminal `VOIDED` state and incrementing its `version`; because an open
    sale's lines never decremented any package's remaining grams, voiding
    releases no inventory."

    Design: Difficulty/compensating_invariant/sale_void_conserves_package_remaining
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=100)
    pkg_id = scn["package"]["id"]
    sale = open_sale(scn["ret"]["id"], scn["customer"]["id"],
                     sale_date="2026-06-11T00:00:00Z")
    add_sale_line(sale["id"], pkg_id, 30.0)
    voided = validate_success(api.void_sale(sale["id"], bud_h()))
    assert voided["status"] == "VOIDED"
    data = validate_success(api.get_package(pkg_id, cult_h()))
    assert data["remaining_grams"] == 100.0, "OPEN lines never decremented; zero drift"


def test_void_open_sale_keeps_package_active(api):
    """PRD §3.7: "because an open sale's lines never decremented any package's
    remaining grams, voiding releases no inventory."

    Design: Difficulty/compensating_invariant/sale_void_conserves_package_remaining
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=100)
    pkg_id = scn["package"]["id"]
    sale = open_sale(scn["ret"]["id"], scn["customer"]["id"],
                     sale_date="2026-06-11T00:00:00Z")
    add_sale_line(sale["id"], pkg_id, 30.0)
    validate_success(api.void_sale(sale["id"], bud_h()))
    data = validate_success(api.get_package(pkg_id, cult_h()))
    assert data["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: correct sale version finalizes (OCC happy path)
# ---------------------------------------------------------------------------
def test_finalize_with_current_sale_version_succeeds(api):
    """PRD §2.10: "Finalizing a sale requires the request to carry
    `expected_sale_version`, which must equal the sale's current `version`."
    PRD §3.7: "Finalizing a sale moves it from `OPEN` to the terminal
    `FINALIZED` state and is performed by a `Budtender`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_sale_version_finalizes
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=100)
    sale = open_sale_with_line(scn["ret"]["id"], scn["customer"]["id"],
                               scn["package"]["id"], 5.0,
                               sale_date="2026-06-20T00:00:00Z")
    before_v = sale["version"]
    data = validate_success(finalize_sale(sale["id"], expected_version=before_v))
    assert data["status"] == "FINALIZED"
    assert data["version"] > before_v, "finalize must advance the sale version"
