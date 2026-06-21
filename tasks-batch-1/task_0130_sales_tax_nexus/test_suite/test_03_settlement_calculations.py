"""Settlement calculations: sourcing-variant divergence, marketplace-vs-seller
responsibility, mixed-taxability line resolution, round-then-sum precision,
use-tax accrual, certificate exemption, and immediate consistency.

Queue A: dual_variant_calc, combinatorial_formula.
Queue B: calculations + consistency_model sections.
"""
import pytest

from test_helpers import (
    make_seller_headers,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================

def test_destination_sourcing_applies_destination_combined_rate(api):
    """PRD §3.4: "If that jurisdiction's `sourcing_rule` is `DESTINATION`, then `sourcing_used` is `DESTINATION`, the rate applied is the destination jurisdiction's `combined_rate`, and nexus accrues to the destination state."

    Design: Difficulty/dual_variant_calc/sourcing_origin_vs_destination_diverge_on_transaction
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(legal_name="Dest Seller", origin_state_code="TX")
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95},
         {"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="buyer-d", customer_exempt_requested=False)
    assert txn["sourcing_used"] == "DESTINATION", f"got {txn['sourcing_used']}"
    assert txn["applied_rate"] == 0.0825, f"expected applied_rate 0.0825, got {txn['applied_rate']}"
    # Two FULL lines 7.95 @ 0.0825 -> each rounds to 0.66; round-then-sum = 1.32.
    assert txn["tax_collected"] == 1.32, f"expected tax_collected 1.32, got {txn['tax_collected']}"


def test_origin_sourcing_applies_origin_combined_rate(api):
    """PRD §3.4: "If instead the destination jurisdiction's `sourcing_rule` is `ORIGIN`, then `sourcing_used` is `ORIGIN`, the rate applied is the `combined_rate` of the jurisdiction whose `state_code` equals the seller's `origin_state_code`, and nexus accrues to that origin state."

    Design: Difficulty/dual_variant_calc/sourcing_origin_vs_destination_diverge_on_transaction
    """
    fx.create_ca_jurisdiction()  # destination CA present, but this txn is to TX (ORIGIN)
    tx = fx.create_tx_jurisdiction()
    fx.create_category(tx["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(legal_name="Origin Seller", origin_state_code="TX")
    txn = fx.create_and_settle_transaction(
        seller["id"], tx["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95},
         {"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="buyer-o", customer_exempt_requested=False)
    assert txn["sourcing_used"] == "ORIGIN", f"got {txn['sourcing_used']}"
    assert txn["applied_rate"] == 0.0625, f"expected applied_rate 0.0625, got {txn['applied_rate']}"
    # Two FULL lines 7.95 @ 0.0625 -> each rounds to 0.50; round-then-sum = 1.00.
    assert txn["tax_collected"] == 1.00, f"expected tax_collected 1.00, got {txn['tax_collected']}"


def test_marketplace_facilitated_sale_responsibility_is_marketplace_and_no_accrual(api):
    """PRD §3.5: "If the transaction has a `facilitator_id` set and the destination state's `state_code` appears in that facilitator's `collecting_state_codes`, then `remittance_responsibility` is `MARKETPLACE`: the facilitator collects and remits, the seller's nexus is not accrued".

    Design: Difficulty/dual_variant_calc/remittance_responsibility_marketplace_vs_seller_diverge
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    mp = fx.create_facilitator(name="MP", collecting_state_codes=["CA"])
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="b1", customer_exempt_requested=False, facilitator_id=mp["id"])
    assert txn["remittance_responsibility"] == "MARKETPLACE", f"got {txn['remittance_responsibility']}"
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_taxable_sales"] == 0, \
        f"marketplace sale must not accrue nexus, got {refreshed['cumulative_taxable_sales']}"
    assert refreshed["cumulative_txn_count"] == 0, \
        f"marketplace sale must not increment count, got {refreshed['cumulative_txn_count']}"


def test_seller_collected_sale_responsibility_is_seller_and_accrues_nexus(api):
    """PRD §3.5: "In every other case — no facilitator, or a facilitator that does not collect in the destination state — `remittance_responsibility` is `SELLER`: the seller owes remittance and nexus accrues."
    PRD §3.5: "the profile's `cumulative_taxable_sales` is increased by this transaction's `taxable_subtotal` and its `cumulative_txn_count` is increased by one".

    Design: Difficulty/dual_variant_calc/remittance_responsibility_marketplace_vs_seller_diverge
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    profile = fx.create_nexus_profile(seller["id"], ca["id"])
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="b2", customer_exempt_requested=False)
    assert txn["remittance_responsibility"] == "SELLER", f"got {txn['remittance_responsibility']}"
    refreshed = validate_success(
        api.get_nexus_profile(profile["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["cumulative_taxable_sales"] == 7.95, \
        f"expected accrual 7.95, got {refreshed['cumulative_taxable_sales']}"
    assert refreshed["cumulative_txn_count"] == 1, \
        f"expected count 1, got {refreshed['cumulative_txn_count']}"


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================

def test_mixed_taxability_lines_resolve_per_category(api):
    """PRD §3.4: "if the category's `taxability` is `REDUCED`, the line's `line_taxability` is `REDUCED` and its `line_tax` is the line's `quantity` multiplied by its `unit_price` multiplied by the sourced state's `reduced_rate`, rounded half-up to two decimal places. In all remaining cases the line's `line_taxability` is `FULL` and its `line_tax` is the line's `quantity` multiplied by its `unit_price` multiplied by the `applied_rate`, rounded half-up to two decimal places."
    PRD §3.4: "When a line is exempt by either route, its `line_taxability` is `EXEMPT` and its `line_tax` is 0.00, and the line contributes nothing to the taxable subtotal."

    Design: Difficulty/combinatorial_formula/mixed_taxability_lines_conditional_branch_mode_a
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    fx.create_category(ca["id"], "GROCERY", "REDUCED")
    fx.create_category(ca["id"], "DIGITAL", "EXEMPT")
    seller = fx.create_seller(origin_state_code="CA")
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 30.00},
         {"category_code": "GROCERY", "quantity": 1, "unit_price": 50.00},
         {"category_code": "DIGITAL", "quantity": 1, "unit_price": 20.00}],
        customer_ref="b1", customer_exempt_requested=False)
    # TANGIBLE 30 @0.0825 -> 2.48; GROCERY 50 @0.02 -> 1.00; DIGITAL EXEMPT -> 0.00.
    assert txn["tax_collected"] == 3.48, f"expected tax_collected 3.48, got {txn['tax_collected']}"
    # taxable_subtotal excludes the EXEMPT line: 30 + 50 = 80.00.
    assert txn["taxable_subtotal"] == 80.00, f"expected taxable_subtotal 80.00, got {txn['taxable_subtotal']}"


def test_mixed_taxability_subtotal_excludes_exempt_line(api):
    """PRD §3.4: "The transaction's `taxable_subtotal` is the sum, over every line whose resolved `line_taxability` is not `EXEMPT`, of that line's `quantity` multiplied by its `unit_price`, with the total rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/mixed_taxability_lines_conditional_branch_mode_a
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    fx.create_category(ca["id"], "GROCERY", "REDUCED")
    fx.create_category(ca["id"], "DIGITAL", "EXEMPT")
    seller = fx.create_seller(origin_state_code="CA")
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 30.00},
         {"category_code": "GROCERY", "quantity": 1, "unit_price": 50.00},
         {"category_code": "DIGITAL", "quantity": 1, "unit_price": 20.00}],
        customer_ref="b1", customer_exempt_requested=False)
    assert txn["taxable_subtotal"] == 80.00, \
        f"DIGITAL (EXEMPT) must be excluded; expected 80.00, got {txn['taxable_subtotal']}"


def test_round_then_sum_pinned_order_two_full_lines(api):
    """PRD §3.4: "The transaction's `tax_collected` is the sum of every line's already-rounded `line_tax`. This ordering is mandatory: each line's tax is rounded to two decimal places first, and only then are the per-line amounts summed — round-then-sum, never sum-then-round."

    Design: Difficulty/combinatorial_formula/round_then_sum_pinned_order_mode_b
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95},
         {"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="b1", customer_exempt_requested=False)
    # Each line 7.95 @ 0.0825 = 0.655875 -> 0.66; round-then-sum = 1.32 (sum-then-round would be 1.31).
    assert txn["tax_collected"] == 1.32, f"expected round-then-sum 1.32, got {txn['tax_collected']}"


def test_round_then_sum_taxable_subtotal_two_full_lines(api):
    """PRD §3.4: "The transaction's `taxable_subtotal` is the sum, over every line whose resolved `line_taxability` is not `EXEMPT`, of that line's `quantity` multiplied by its `unit_price`, with the total rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/round_then_sum_pinned_order_mode_b
    """
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95},
         {"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="b1", customer_exempt_requested=False)
    assert txn["taxable_subtotal"] == 15.90, \
        f"expected taxable_subtotal 15.90, got {txn['taxable_subtotal']}"


# ===========================================================================
# Queue B — calculations section
# ===========================================================================

def test_use_tax_accrual_correct_result_and_precision(api):
    """PRD §3.8: "The system computes `accrued_use_tax` as the `purchase_amount` multiplied by the destination jurisdiction's `combined_rate`, rounded half-up to two decimal places. A new accrual's `status` is `ACCRUED`, and its `tax_return_id` is null until the accrual is swept into an accepted return."

    Design: Corner/calculations/use_tax_accrual_correct_result_and_precision
    """
    ca = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    res = api.create_use_tax_accrual(
        {"seller_id": seller["id"], "jurisdiction_id": ca["id"], "purchase_amount": 1200.00},
        make_seller_headers(seller["id"]))
    accrual = validate_success(res, 201)
    # 1200.00 * 0.0825 = 99.00.
    assert accrual["accrued_use_tax"] == 99.00, f"expected 99.00, got {accrual['accrued_use_tax']}"
    assert accrual["status"] == "ACCRUED", f"got {accrual['status']}"


def test_certificate_exemption_zeroes_matching_line_tax(api):
    """PRD §3.4: "A certificate exempts the line only when the transaction's `customer_exempt_requested` flag is true and there exists an `ExemptionCertificate` that is `ACTIVE`, belongs to the same `seller_id` as the transaction, is filed for the sourced state, has a `customer_ref` equal to the transaction's `customer_ref`, has an `exempt_category_code` equal to the line's `category_code`, and whose validity window contains the current clock".

    Design: Corner/calculations/certificate_exemption_zeroes_matching_line_tax
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    fx.create_certificate(seller["id"], ca["id"], customer_ref="b1",
                          exempt_category_code="TANGIBLE",
                          valid_from="2026-01-01T00:00:00Z", valid_to="2027-01-01T00:00:00Z")
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 100.00}],
        customer_ref="b1", customer_exempt_requested=True)
    assert txn["tax_collected"] == 0.00, f"expected 0.00, got {txn['tax_collected']}"
    assert txn["taxable_subtotal"] == 0.00, f"expected 0.00, got {txn['taxable_subtotal']}"


def test_revoked_certificate_does_not_exempt_at_settle(api):
    """PRD §3.7: "A revoked certificate no longer exempts future settlements, though transactions already settled against it are unaffected."

    Design: Corner/calculations/revoked_certificate_does_not_exempt_at_settle
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    cert = fx.create_certificate(seller["id"], ca["id"], customer_ref="b1",
                                 exempt_category_code="TANGIBLE",
                                 valid_from="2026-01-01T00:00:00Z",
                                 valid_to="2027-01-01T00:00:00Z")
    fx.revoke_certificate(seller["id"], cert["id"])
    txn = fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 100.00}],
        customer_ref="b1", customer_exempt_requested=True)
    # FULL line 100.00 @ 0.0825 -> 8.25; revoked cert does not exempt.
    assert txn["tax_collected"] == 8.25, f"expected 8.25, got {txn['tax_collected']}"
    assert txn["taxable_subtotal"] == 100.00, f"expected 100.00, got {txn['taxable_subtotal']}"


# ===========================================================================
# Queue B — consistency_model section
# ===========================================================================

def test_settle_response_reflects_computed_tax_immediately(api):
    """PRD §3.4: "On success the settlement advances `PENDING → SETTLED`, appends an `AuditLogEntry` recording the settle, and increments the transaction's `version` by one."
    PRD §3.4: "In all remaining cases the line's `line_taxability` is `FULL` and its `line_tax` is the line's `quantity` multiplied by its `unit_price` multiplied by the `applied_rate`, rounded half-up to two decimal places."

    Design: Corner/consistency_model/settle_response_reflects_computed_tax_immediately
    """
    jur, seller = fx.setup_ca_seller(with_category=True)
    txn = fx.create_transaction_with_lines(
        seller["id"], jur["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 10.00}],
        customer_ref="b1", customer_exempt_requested=False)
    res = api.settle_transaction(txn["id"], make_seller_headers(seller["id"]))
    settled = validate_success(res, 200)
    # The settle response itself carries the computed tax (no re-read needed).
    assert settled["tax_collected"] == 0.83, f"expected 0.83 in settle response, got {settled['tax_collected']}"
