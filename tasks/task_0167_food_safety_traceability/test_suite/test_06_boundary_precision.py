"""Boundary precision: the strict temperature-tolerance boundary (== tolerance is
IN_SPEC, just over is DEVIATION) and the supplier suspend-streak boundary (2 stays
APPROVED, 3 flips SUSPENDED).

Queue A — Difficulty/boundary_precision_check.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    setup_released_lot_for_readings, post_reading,
    create_facility, create_supplier, create_ingredient, receive_lot,
    attach_coa, decide_coa,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/temperature_tolerance_strict_boundary
# ---------------------------------------------------------------------------

def test_reading_exactly_at_tolerance_is_in_spec():
    """PRD 3.5: "The reading's `classification` is `DEVIATION` when the absolute
    difference between `measured_value_c` and the ingredient's `storage_target_c` is
    strictly greater than the ingredient's `storage_tolerance_c`; a difference exactly
    equal to the tolerance is `IN_SPEC`."

    Design: Difficulty/boundary_precision_check/temperature_tolerance_strict_boundary
    """
    facility, ingredient, lot_id = setup_released_lot_for_readings(
        target_c=4, tolerance_c=2, clock_utc="2026-01-02T01:00:00Z",
        shelf_life_days=30, declared_allergen_codes=["MILK"])
    # abs(6 - 4) == 2 == tolerance -> IN_SPEC (not strictly greater).
    r = post_reading(lot_id, 6, "2026-01-02T00:00:00Z")
    assert r["classification"] == "IN_SPEC"


def test_reading_just_over_tolerance_is_deviation():
    """PRD 3.5: "The reading's `classification` is `DEVIATION` when the absolute
    difference between `measured_value_c` and the ingredient's `storage_target_c` is
    strictly greater than the ingredient's `storage_tolerance_c`; a difference exactly
    equal to the tolerance is `IN_SPEC`."

    Design: Difficulty/boundary_precision_check/temperature_tolerance_strict_boundary
    """
    facility, ingredient, lot_id = setup_released_lot_for_readings(
        target_c=4, tolerance_c=2, clock_utc="2026-01-02T01:00:00Z",
        shelf_life_days=30, declared_allergen_codes=["MILK"])
    post_reading(lot_id, 6, "2026-01-02T00:00:00Z")
    # abs(6.5 - 4) = 2.5 > 2 -> DEVIATION.
    r = post_reading(lot_id, 6.5, "2026-01-02T00:30:00Z")
    assert r["classification"] == "DEVIATION"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/supplier_suspend_streak_boundary
# ---------------------------------------------------------------------------

def _reject_nth_coa(facility_id, ingredient_id, supplier_id, n):
    lot = receive_lot(facility_id, ingredient_id, f"S{n}", supplier_id=supplier_id,
                      received_qty=5)
    coa = attach_coa(lot["id"], measured_allergen_codes=["TREE_NUT"], pathogen_pass=True,
                     declared_shelf_life_days=365)
    decide_coa(coa["id"], "REJECT")


def test_second_consecutive_reject_keeps_supplier_approved():
    """PRD 2.10: "A second consecutive rejection (streak of two) does not."

    Design: Difficulty/boundary_precision_check/supplier_suspend_streak_boundary
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=365,
                                   declared_allergen_codes=["TREE_NUT"])
    _reject_nth_coa(facility["id"], ingredient["id"], supplier["id"], 1)
    _reject_nth_coa(facility["id"], ingredient["id"], supplier["id"], 2)

    sup = validate_success(api_client.get_supplier(supplier["id"], QM), 200)
    assert sup["failed_coa_streak"] == 2
    assert sup["approval_status"] == "APPROVED"


def test_third_consecutive_reject_suspends_supplier():
    """PRD 2.10: "The third consecutive rejection suspends the supplier; more precisely,
    when the streak reaches three or more it flips `approval_status` to `SUSPENDED`."

    Design: Difficulty/boundary_precision_check/supplier_suspend_streak_boundary
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=365,
                                   declared_allergen_codes=["TREE_NUT"])
    _reject_nth_coa(facility["id"], ingredient["id"], supplier["id"], 1)
    _reject_nth_coa(facility["id"], ingredient["id"], supplier["id"], 2)
    _reject_nth_coa(facility["id"], ingredient["id"], supplier["id"], 3)

    sup = validate_success(api_client.get_supplier(supplier["id"], QM), 200)
    assert sup["failed_coa_streak"] == 3
    assert sup["approval_status"] == "SUSPENDED"
