"""Compensating invariants: a DISPOSE zeroes a lot's available_qty (units conserved
as destroyed), and a RELEASE-resolve restores the lot to FREE (frozen-lot count
returns to zero).

Queue A — Difficulty/compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_facility, create_supplier, create_ingredient, receive_lot, release_lot,
    issue_hold, resolve_hold,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/dispose_conserves_lot_quantity_ledger
# ---------------------------------------------------------------------------

def test_received_lot_available_equals_received_qty():
    """PRD 3.2: "On receipt the lot's `status` is set to `RECEIVED`, its `available_qty`
    is initialized to the `received_qty`, and its `hold_status` is `FREE`."

    Design: Difficulty/compensating_invariant/dispose_conserves_lot_quantity_ledger
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=365)
    lot = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                      received_qty=100)
    assert lot["available_qty"] == 100.0   # destroyed 0; invariant 0 + 100 = 100


def test_dispose_zeroes_available_qty_and_destroys():
    """PRD 3.7: "Every lot in the covered set that is not already terminal transitions
    to `DESTROYED` and has its `available_qty` set to zero."

    Design: Difficulty/compensating_invariant/dispose_conserves_lot_quantity_ledger
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=365)
    lot = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                      received_qty=100)
    release_lot(lot["id"])
    hold = issue_hold(facility["id"], lot["id"], reason="RECALL")
    resolve_hold(hold["id"], "DISPOSE", hold["version"])

    after = validate_success(api_client.get_lot(lot["id"], QM), 200)
    # destroyed 100; invariant 100 + 0 = 100 unchanged.
    assert after["available_qty"] == 0.0
    assert after["status"] == "DESTROYED"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/release_then_release_conserves_held_count_freeze_set
# ---------------------------------------------------------------------------

def test_hold_freezes_single_lot_held_count_one():
    """PRD 3.6: "Every lot in the covered set that is not already in a terminal status
    has its `hold_status` set to `HELD`."
    PRD 3.6: "The hold records the number of distinct lots in the covered set as
    `held_lot_count`, a snapshot taken at issue time, and its `status` is set to
    `ACTIVE`."

    Design: Difficulty/compensating_invariant/release_then_release_conserves_held_count_freeze_set
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=365)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=20)
    release_lot(lot["id"])
    hold = issue_hold(facility["id"], lot["id"], reason="OTHER")
    assert hold["held_lot_count"] == 1

    during = validate_success(api_client.get_lot(lot["id"], QM), 200)
    assert during["hold_status"] == "HELD"


def test_release_resolve_restores_lot_to_free():
    """PRD 3.7: "A release disposition sets the hold's `disposition` to `RELEASED` and
    its `status` to `RELEASED`, then recomputes the `hold_status` of every lot in the
    covered set: a lot becomes `FREE` if no other active hold still covers it, and
    remains `HELD` if some other active hold does."

    Design: Difficulty/compensating_invariant/release_then_release_conserves_held_count_freeze_set
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=365)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=20)
    release_lot(lot["id"])
    hold = issue_hold(facility["id"], lot["id"], reason="OTHER")
    resolve_hold(hold["id"], "RELEASE", hold["version"])

    after = validate_success(api_client.get_lot(lot["id"], QM), 200)
    # No other active hold -> FREE; the lot survives (still RELEASED).
    assert after["hold_status"] == "FREE"
    assert after["status"] == "RELEASED"
