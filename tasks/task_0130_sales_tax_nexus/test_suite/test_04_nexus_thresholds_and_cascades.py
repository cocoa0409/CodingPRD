"""Nexus accrual: inclusive thresholds, the settle→accrue→posture-flip cascade,
void compensation invariants, and derived-field reconciliation on read.

Queue A: boundary_precision_check, transitive_cascade (settle path),
compensating_invariant.
Queue B: cross_cutting derived_field_reconciliation.
"""
import pytest

from test_helpers import (
    make_seller_headers,
    validate_success,
)
from test_helpers import fixtures as fx


def _settle_count_path_jurisdiction():
    """NY jurisdiction with txn threshold 3, plus TANGIBLE=FULL and a profiled seller."""
    ny = fx.create_ny_jurisdiction()
    fx.create_category(ny["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="NY")
    profile = fx.create_nexus_profile(seller["id"], ny["id"])
    return ny, seller, profile


# ===========================================================================
# Queue A — boundary_precision_check
# ===========================================================================

def test_nexus_sales_threshold_inclusive_at_exact_value_flips_posture(api):
    """PRD §2.5: "The sales test is met when `cumulative_taxable_sales` is greater than or equal to the jurisdiction's `economic_nexus_sales_threshold`; this comparison is inclusive, so reaching the threshold exactly counts as met."

    Design: Difficulty/boundary_precision_check/nexus_sales_threshold_inclusive_at_exact_value
    """
    ca = fx.create_ca_jurisdiction()  # sales threshold 100000.00
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    fx.settle_one_full_line(seller["id"], ca["id"], 100000.00, customer_ref="b1")
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_taxable_sales"] == 100000.00, \
        f"got {refreshed['cumulative_taxable_sales']}"
    assert refreshed["nexus_status"] == "THRESHOLD_MET", \
        f"exact threshold is inclusive -> THRESHOLD_MET, got {refreshed['nexus_status']}"


def test_nexus_sales_threshold_below_value_stays_no_nexus(api):
    """PRD §2.5: "Otherwise, if the threshold is crossed the posture is `THRESHOLD_MET`, and if it is not crossed the posture is `NO_NEXUS`."

    Design: Difficulty/boundary_precision_check/nexus_sales_threshold_inclusive_at_exact_value
    """
    ca = fx.create_ca_jurisdiction()  # sales threshold 100000.00
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    fx.settle_one_full_line(seller["id"], ca["id"], 99999.99, customer_ref="b1")
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_taxable_sales"] == 99999.99, \
        f"got {refreshed['cumulative_taxable_sales']}"
    assert refreshed["nexus_status"] == "NO_NEXUS", \
        f"below threshold -> NO_NEXUS, got {refreshed['nexus_status']}"


def test_nexus_txn_count_threshold_inclusive_on_third_settle(api):
    """PRD §2.5: "The count test is met only when the jurisdiction's `economic_nexus_txn_threshold` is greater than zero and `cumulative_txn_count` is greater than or equal to that threshold".

    Design: Difficulty/boundary_precision_check/nexus_txn_count_threshold_inclusive_on_third_settle
    """
    ny, seller, profile = _settle_count_path_jurisdiction()
    for ref in ("b1", "b2", "b3"):
        fx.settle_one_full_line(seller["id"], ny["id"], 10.00, customer_ref=ref)
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_txn_count"] == 3, f"got {refreshed['cumulative_txn_count']}"
    assert refreshed["nexus_status"] == "THRESHOLD_MET", \
        f"count threshold 3 reached -> THRESHOLD_MET, got {refreshed['nexus_status']}"
    assert refreshed["cumulative_taxable_sales"] == 30.00, \
        f"sales stay far below the sales threshold, got {refreshed['cumulative_taxable_sales']}"


def test_nexus_txn_count_threshold_not_met_on_second_settle(api):
    """PRD §2.5: "a threshold of zero disables the count test entirely. The threshold is considered crossed when either the sales test or the count test is met."

    Design: Difficulty/boundary_precision_check/nexus_txn_count_threshold_inclusive_on_third_settle
    """
    ny, seller, profile = _settle_count_path_jurisdiction()
    for ref in ("b1", "b2"):
        fx.settle_one_full_line(seller["id"], ny["id"], 10.00, customer_ref=ref)
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_txn_count"] == 2, f"got {refreshed['cumulative_txn_count']}"
    assert refreshed["nexus_status"] == "NO_NEXUS", \
        f"count 2 < threshold 3 -> NO_NEXUS, got {refreshed['nexus_status']}"


# ===========================================================================
# Queue A — transitive_cascade (settle accrue -> posture flip)
# ===========================================================================

def test_settle_accrues_then_flips_posture_same_call(api):
    """PRD §3.5: "the profile's `cumulative_taxable_sales` is increased by this transaction's `taxable_subtotal` and its `cumulative_txn_count` is increased by one, after which `nexus_status` is recomputed by the rule in §2.5. If that recomputation flips the posture `NO_NEXUS → THRESHOLD_MET` within the same settle call, that flip is the cascade triggered by the sale."

    Design: Difficulty/transitive_cascade/settle_accrue_then_posture_flip_depth3
    """
    ca = fx.create_ca_jurisdiction()  # sales threshold 100000.00
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    fx.settle_one_full_line(seller["id"], ca["id"], 100000.00, customer_ref="b1")
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_taxable_sales"] == 100000.00, \
        f"got {refreshed['cumulative_taxable_sales']}"
    assert refreshed["nexus_status"] == "THRESHOLD_MET", \
        f"settle should cascade the posture flip, got {refreshed['nexus_status']}"


def test_settle_large_full_line_records_expected_tax(api):
    """PRD §3.4: "In all remaining cases the line's `line_taxability` is `FULL` and its `line_tax` is the line's `quantity` multiplied by its `unit_price` multiplied by the `applied_rate`, rounded half-up to two decimal places."

    Design: Difficulty/transitive_cascade/settle_accrue_then_posture_flip_depth3
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    fx.create_nexus_profile(seller["id"], ca["id"])
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 100000.00}],
        customer_ref="b1", customer_exempt_requested=False)
    # 100000.00 @ 0.0825 = 8250.00.
    assert txn["tax_collected"] == 8250.00, f"expected 8250.00, got {txn['tax_collected']}"


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================

def test_void_restores_cumulative_taxable_sales_to_zero(api):
    """PRD §3.5: "when the voided transaction was `SELLER`-responsible, the system decreases the sourced-state profile's `cumulative_taxable_sales` by that transaction's `taxable_subtotal` and decreases `cumulative_txn_count` by one".
    PRD §3.5: "The conserved quantity across a settle/void pair is the profile's `cumulative_taxable_sales`."

    Design: Difficulty/compensating_invariant/void_restores_cumulative_taxable_sales
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="b1", customer_exempt_requested=False)
    voided = validate_success(api.void_transaction(txn["id"], make_seller_headers(seller["id"])), 200)
    assert voided["settlement_status"] == "VOIDED", f"got {voided['settlement_status']}"
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_taxable_sales"] == 0, \
        f"void must restore to 0.00, got {refreshed['cumulative_taxable_sales']}"
    assert refreshed["cumulative_txn_count"] == 0, \
        f"void must restore count to 0, got {refreshed['cumulative_txn_count']}"


def test_void_one_of_two_leaves_only_the_live_contribution(api):
    """PRD §3.5: "when the voided transaction was `SELLER`-responsible, the system decreases the sourced-state profile's `cumulative_taxable_sales` by that transaction's `taxable_subtotal` and decreases `cumulative_txn_count` by one".
    PRD §3.5: "The conserved quantity across a settle/void pair is the profile's `cumulative_taxable_sales`."

    Design: Difficulty/compensating_invariant/void_restores_cumulative_taxable_sales
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    keep = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 100.00}],
        customer_ref="keep", customer_exempt_requested=False)
    drop = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="drop", customer_exempt_requested=False)
    # After two SELLER settles: 100.00 + 7.95 = 107.95, count 2.
    mid = validate_success(api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert mid["cumulative_taxable_sales"] == 107.95, f"setup got {mid['cumulative_taxable_sales']}"
    validate_success(api.void_transaction(drop["id"], make_seller_headers(seller["id"])), 200)
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_taxable_sales"] == 100.00, \
        f"voiding only the 7.95 sale must leave 100.00, got {refreshed['cumulative_taxable_sales']}"
    assert refreshed["cumulative_txn_count"] == 1, \
        f"count decremented by one to 1, got {refreshed['cumulative_txn_count']}"
    assert keep["id"] != drop["id"]


def test_void_restores_threshold_posture_when_not_registered(api):
    """PRD §3.5: "This de-accrual may step the posture `THRESHOLD_MET → NO_NEXUS`, but it can never pull it below `REGISTERED` — once a seller has registered, the posture is sticky and a void leaves it `REGISTERED`."

    Design: Difficulty/compensating_invariant/void_restores_threshold_posture_when_not_registered
    """
    ca = fx.create_ca_jurisdiction()  # sales threshold 100000.00
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 100000.00}],
        customer_ref="b1", customer_exempt_requested=False)
    # Sanity: posture flipped to THRESHOLD_MET (not registered).
    mid = validate_success(api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert mid["nexus_status"] == "THRESHOLD_MET", f"setup expected THRESHOLD_MET, got {mid['nexus_status']}"
    validate_success(api.void_transaction(txn["id"], make_seller_headers(seller["id"])), 200)
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["nexus_status"] == "NO_NEXUS", \
        f"un-registered void must restore NO_NEXUS, got {refreshed['nexus_status']}"
    assert refreshed["cumulative_taxable_sales"] == 0, \
        f"got {refreshed['cumulative_taxable_sales']}"


def test_void_keeps_posture_registered_when_already_registered(api):
    """PRD §3.5: "it can never pull it below `REGISTERED` — once a seller has registered, the posture is sticky and a void leaves it `REGISTERED`."

    Design: Difficulty/compensating_invariant/void_restores_threshold_posture_when_not_registered
    """
    ca, seller, profile = fx.setup_registered_seller_ca(big_unit_price=100000.00)
    assert profile["nexus_status"] == "REGISTERED", f"setup expected REGISTERED, got {profile['nexus_status']}"
    # Settle and then void a second SELLER transaction; sticky registration must hold.
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 50.00}],
        customer_ref="b2", customer_exempt_requested=False)
    validate_success(api.void_transaction(txn["id"], make_seller_headers(seller["id"])), 200)
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["nexus_status"] == "REGISTERED", \
        f"registration is sticky across a void, got {refreshed['nexus_status']}"


# ===========================================================================
# Queue B — cross_cutting derived_field_reconciliation
# ===========================================================================

def test_derived_nexus_status_reconciled_on_read_after_settle(api):
    """PRD §2.5: "The posture is recomputed from the profile's own accumulators and its jurisdiction's thresholds every time the accumulators move."

    Design: Corner/cross_cutting/derived_nexus_status_reconciled_on_read_after_settle
    """
    ca = fx.create_ca_jurisdiction()  # sales threshold 100000.00
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    fx.settle_one_full_line(seller["id"], ca["id"], 7.95, customer_ref="b1")
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_taxable_sales"] == 7.95, f"got {refreshed['cumulative_taxable_sales']}"
    assert refreshed["nexus_status"] == "NO_NEXUS", \
        f"7.95 < 100000 threshold -> NO_NEXUS, got {refreshed['nexus_status']}"
