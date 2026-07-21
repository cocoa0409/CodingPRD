"""Fabric bolt inventory and the cutting counter: reorder-threshold boundaries, the
cut/void yardage-conservation invariant, insufficient-yardage and non-positive guards,
immediate reconciliation, defaults, void lockdown, discontinue cascade, and the
state-beats-fiscal validation-priority pair."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_bolt, create_cut, create_bolt_with_cut, create_kit_for_bolt,
    ApiErrorId, TEST_USERS,
)
from test_helpers import factories as f

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# =========================================================================
# Difficulty/boundary_precision_check/bolt_reorder_threshold_exact_low_stock
# =========================================================================
def test_remaining_exactly_at_threshold_is_low_stock(api):
    """PRD §3.2: "when it falls to the threshold or below while still greater than zero it
    becomes LOW_STOCK". A bolt of 10 yards with reorder_threshold 3, after a 7-yard cut, sits
    at yards_remaining 3 — exactly the threshold — so it is LOW_STOCK, not IN_STOCK.

    Design: Difficulty/boundary_precision_check/bolt_reorder_threshold_exact_low_stock
    """
    bolt = create_bolt(api, price_per_yard=1.00, original_yards=10, reorder_threshold=3)
    create_cut(api, bolt["id"], 7)
    data = validate_success(api.get_fabric_bolt(bolt["id"], CLERK), 200)
    assert data["yards_remaining"] == 3, f"expected 3, got {data['yards_remaining']}"
    assert data["status"] == "LOW_STOCK", f"expected LOW_STOCK, got {data['status']}"


def test_remaining_above_threshold_stays_in_stock(api):
    """PRD §3.2: "While remaining yardage sits above the reorder threshold the bolt is
    IN_STOCK". A bolt of 10 yards with reorder_threshold 3, after a 6-yard cut, sits at
    yards_remaining 4 — strictly above the threshold — so it remains IN_STOCK.

    Design: Difficulty/boundary_precision_check/bolt_reorder_threshold_exact_low_stock
    """
    bolt = create_bolt(api, price_per_yard=1.00, original_yards=10, reorder_threshold=3)
    create_cut(api, bolt["id"], 6)
    data = validate_success(api.get_fabric_bolt(bolt["id"], CLERK), 200)
    assert data["yards_remaining"] == 4, f"expected 4, got {data['yards_remaining']}"
    assert data["status"] == "IN_STOCK", f"expected IN_STOCK, got {data['status']}"


# =========================================================================
# Difficulty/compensating_invariant/fabric_yardage_conserved_on_cut_void
# =========================================================================
def test_void_restores_full_yardage(api):
    """PRD §3.2: "Voiding moves the cut to VOIDED, returns its yards_requested to the bolt's
    remaining yardage, and reconciles the bolt's status." A 4-yard cut on a 10-yard bolt
    (remaining 6), once voided, returns the bolt to yards_remaining 10 and IN_STOCK.

    Design: Difficulty/compensating_invariant/fabric_yardage_conserved_on_cut_void
    """
    bolt = create_bolt(api, price_per_yard=2.00, original_yards=10, reorder_threshold=2)
    cut = create_cut(api, bolt["id"], 4)
    data = validate_success(api.void_fabric_cut(cut["id"], CLERK), 200)
    assert data["status"] == "VOIDED"
    bolt_after = validate_success(api.get_fabric_bolt(bolt["id"], CLERK), 200)
    assert bolt_after["yards_remaining"] == 10, f"expected 10, got {bolt_after['yards_remaining']}"
    assert bolt_after["status"] == "IN_STOCK"


def test_voided_cut_excluded_from_remaining_sum(api):
    """PRD §3.2: "A bolt's yards_remaining is always its original_yards minus the total
    yards_requested across all of its cuts that remain in CUT status; voided cuts are
    excluded from that sum". Two cuts of 4 and 3 on a 10-yard bolt leave 3; voiding the
    4-yard cut excludes it from the sum, leaving 10 - 3 = 7.

    Design: Difficulty/compensating_invariant/fabric_yardage_conserved_on_cut_void
    """
    bolt = create_bolt(api, price_per_yard=2.00, original_yards=10, reorder_threshold=2)
    cut4 = create_cut(api, bolt["id"], 4)
    create_cut(api, bolt["id"], 3)
    api.void_fabric_cut(cut4["id"], CLERK)
    bolt_after = validate_success(api.get_fabric_bolt(bolt["id"], CLERK), 200)
    assert bolt_after["yards_remaining"] == 7, f"expected 7, got {bolt_after['yards_remaining']}"


# =========================================================================
# Corner/validations/cut_exceeding_remaining_returns_insufficient_yardage
# =========================================================================
def test_cut_exceeding_remaining_rejected(api):
    """PRD §3.2: "the bolt must have at least the requested yardage remaining, or the cut is
    refused with ERR_INSUFFICIENT_YARDAGE." A 25-yard cut against a 20-yard IN_STOCK bolt is
    refused.

    Design: Corner/validations/cut_exceeding_remaining_returns_insufficient_yardage
    """
    bolt = create_bolt(api, price_per_yard=6.00, original_yards=20)
    resp = api.create_fabric_cut(f.create_fabric_cut_payload(bolt["id"], 25), CLERK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_YARDAGE.value)


# =========================================================================
# Corner/validations/non_positive_yards_returns_amount_error
# =========================================================================
def test_non_positive_yards_rejected(api):
    """PRD §3.2: "The requested yardage must be greater than zero". PRD §2.5: "quantities that
    must be positive (a cut's yards_requested, an order's quantity, measured dimensions, a
    class capacity, and unit costs) must be greater than zero; violations yield
    ERR_NON_POSITIVE_AMOUNT for a non-positive numeric amount".

    Design: Corner/validations/non_positive_yards_returns_amount_error
    """
    bolt = create_bolt(api, price_per_yard=2.00, original_yards=30)
    resp = api.create_fabric_cut(f.create_fabric_cut_payload(bolt["id"], 0), CLERK)
    validate_error(resp, ApiErrorId.ERR_NON_POSITIVE_AMOUNT.value)


# =========================================================================
# Corner/consistency_model/cut_immediately_reconciles_bolt_yards
# =========================================================================
def test_cut_immediately_reconciles_remaining_yards(api):
    """PRD §2.8: "Whenever an operation changes an input those fields depend on, the server
    reconciles the derived fields immediately, in the same request, so a returned resource
    always reflects the current state." After a 4-yard cut on a 30-yard bolt, an immediate
    GET of the bolt shows yards_remaining 26.

    Design: Corner/consistency_model/cut_immediately_reconciles_bolt_yards
    """
    bolt = create_bolt(api, price_per_yard=3.50, original_yards=30)
    create_cut(api, bolt["id"], 4)
    data = validate_success(api.get_fabric_bolt(bolt["id"], CLERK), 200)
    assert data["yards_remaining"] == 26, f"expected 26, got {data['yards_remaining']}"


# =========================================================================
# Corner/entities/bolt_create_default_reorder_threshold_applied
# =========================================================================
def test_bolt_default_reorder_threshold_applied(api):
    """PRD §3.2: "may set a reorder_threshold that defaults to 5 yards. On creation the bolt's
    yards_remaining is initialized to its original_yards, and its status is derived from the
    stock levels below — normally IN_STOCK." A 50-yard bolt created without reorder_threshold
    defaults to 5 and is IN_STOCK.

    Design: Corner/entities/bolt_create_default_reorder_threshold_applied
    """
    resp = api.create_fabric_bolt(
        {"sku": "DF-1", "color": "Cream", "price_per_yard": 9.50, "original_yards": 50}, CLERK)
    data = validate_success(resp, 201)
    assert data["reorder_threshold"] == 5, f"expected 5, got {data['reorder_threshold']}"
    assert data["yards_remaining"] == 50
    assert data["status"] == "IN_STOCK"


# =========================================================================
# Corner/state_machines/void_already_voided_cut_rejected
# =========================================================================
def test_void_already_voided_cut_rejected(api):
    """PRD §3.2: "A cut may be voided by staff only while it is in CUT status; a void attempt
    on a cut that is not currently CUT is rejected with ERR_CUT_NOT_VOIDABLE." Voiding an
    already-VOIDED cut a second time is rejected.

    Design: Corner/state_machines/void_already_voided_cut_rejected
    """
    bolt = create_bolt(api, price_per_yard=4.00, original_yards=20)
    cut = create_cut(api, bolt["id"], 3)
    validate_success(api.void_fabric_cut(cut["id"], CLERK), 200)
    resp = api.void_fabric_cut(cut["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_CUT_NOT_VOIDABLE.value)


# =========================================================================
# Corner/cross_cutting/bolt_discontinue_cascades_kit_unavailable
# =========================================================================
def test_discontinue_bolt_cascades_kit_to_unavailable(api):
    """PRD §3.2: "Discontinuing a bolt cascades: every kit whose component list references
    that bolt is marked UNAVAILABLE". PRD §3.3: "A kit is AVAILABLE on creation and remains so
    until one of its component bolts is discontinued, at which point the discontinuation
    cascade of §3.2 flips the kit to UNAVAILABLE."

    Design: Corner/cross_cutting/bolt_discontinue_cascades_kit_unavailable
    """
    bolt = create_bolt(api, price_per_yard=5.00, original_yards=30, color="Mint")
    kit = create_kit_for_bolt(api, bolt["id"], yards_per_kit=2, quantity=1, name="Mint Kit")
    assert kit["status"] == "AVAILABLE"
    data = validate_success(api.discontinue_fabric_bolt(bolt["id"], MANAGER), 200)
    assert data["status"] == "DISCONTINUED"
    kit_after = validate_success(api.get_kit(kit["id"], CLERK), 200)
    assert kit_after["status"] == "UNAVAILABLE", f"expected UNAVAILABLE, got {kit_after['status']}"


# =========================================================================
# Difficulty/priority_pair_validation_conflict/cut_discontinued_beats_insufficient_yardage
# =========================================================================
def test_discontinued_bolt_beats_insufficient_yardage(api):
    """PRD §2.5: "the checks are evaluated in a fixed priority order, and the first failure
    determines the error returned". The state precondition (priority 5) — PRD §3.2: "the bolt
    must not be DISCONTINUED (otherwise ERR_BOLT_DISCONTINUED)" — is checked before the
    capacity/quota check (priority 9) — PRD §3.2: "the bolt must have at least the requested
    yardage remaining, or the cut is refused with ERR_INSUFFICIENT_YARDAGE." A 20-yard cut on
    a DISCONTINUED 10-yard bolt violates both, and ERR_BOLT_DISCONTINUED wins.

    Design: Difficulty/priority_pair_validation_conflict/cut_discontinued_beats_insufficient_yardage
    """
    bolt = create_bolt(api, price_per_yard=5.00, original_yards=10, reorder_threshold=2, color="Retired")
    validate_success(api.discontinue_fabric_bolt(bolt["id"], MANAGER), 200)
    resp = api.create_fabric_cut(f.create_fabric_cut_payload(bolt["id"], 20), CLERK)
    validate_error(resp, ApiErrorId.ERR_BOLT_DISCONTINUED.value)


def test_discontinued_state_error_fires_even_with_sufficient_yardage(api):
    """PRD §3.2: "the bolt must not be DISCONTINUED (otherwise ERR_BOLT_DISCONTINUED)." The
    state precondition (priority 5) rejects a cut on a DISCONTINUED bolt independently of the
    yardage/quota check: even a 5-yard cut that a 10-yard bolt could satisfy is rejected with
    ERR_BOLT_DISCONTINUED, confirming the state check pre-empts the fiscal one.

    Design: Difficulty/priority_pair_validation_conflict/cut_discontinued_beats_insufficient_yardage
    """
    bolt = create_bolt(api, price_per_yard=5.00, original_yards=10, reorder_threshold=2, color="Retired2")
    validate_success(api.discontinue_fabric_bolt(bolt["id"], MANAGER), 200)
    resp = api.create_fabric_cut(f.create_fabric_cut_payload(bolt["id"], 5), CLERK)
    validate_error(resp, ApiErrorId.ERR_BOLT_DISCONTINUED.value)
