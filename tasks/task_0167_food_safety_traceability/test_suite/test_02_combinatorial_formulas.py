"""Combinatorial formulas: temperature-excursion classification/accrual (a nested
conditional + floor + threshold selection) and the pinned available-quantity draw
order on finalize.

Queue A — Difficulty/combinatorial_formula.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    setup_released_lot_for_readings, post_reading,
    setup_facility_supplier_ingredient, receive_lot, release_lot,
    open_run, add_consumed_lot, finalize_run, current_run_version,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/excursion_classification_three_input_nonlinear
# ---------------------------------------------------------------------------

def test_excursion_first_deviation_has_zero_minutes_no_prior():
    """PRD 3.5: "When the reading is `IN_SPEC`, or when it is a `DEVIATION` but there
    is no prior reading, its `excursion_minutes` is 0."

    Design: Difficulty/combinatorial_formula/excursion_classification_three_input_nonlinear
    """
    facility, ingredient, lot_id = setup_released_lot_for_readings(
        target_c=4, tolerance_c=2, clock_utc="2026-01-02T03:00:00Z",
        shelf_life_days=365, declared_allergen_codes=["MILK"])
    # 8C: abs(8-4)=4 > tol 2 -> DEVIATION; no prior reading -> 0 minutes.
    r1 = post_reading(lot_id, 8, "2026-01-02T00:00:00Z")
    assert r1["classification"] == "DEVIATION"
    assert r1["excursion_minutes"] == 0


def test_excursion_minutes_floor_of_elapsed_and_cumulative():
    """PRD 3.5: "the reading's `excursion_minutes` is the whole number of minutes
    between the prior reading's `measured_at` and this reading's `measured_at`, taken
    as the floor of the elapsed minutes"

    Design: Difficulty/combinatorial_formula/excursion_classification_three_input_nonlinear
    """
    facility, ingredient, lot_id = setup_released_lot_for_readings(
        target_c=4, tolerance_c=2, clock_utc="2026-01-02T03:00:00Z",
        shelf_life_days=365, declared_allergen_codes=["MILK"])
    post_reading(lot_id, 8, "2026-01-02T00:00:00Z")                  # DEVIATION, 0 min
    r2 = post_reading(lot_id, 9, "2026-01-02T00:30:00Z")             # +30 min DEVIATION
    assert r2["excursion_minutes"] == 30
    r3 = post_reading(lot_id, 9, "2026-01-02T02:10:00Z")             # +100 min DEVIATION
    assert r3["classification"] == "DEVIATION"
    assert r3["excursion_minutes"] == 100

    lot = validate_success(api_client.get_lot(lot_id, QM), 200)
    assert lot["cumulative_excursion_minutes"] == 130   # 0 + 30 + 100


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/available_quantity_draw_order_evaluation_pinned
# ---------------------------------------------------------------------------

def test_finalize_draws_both_lines_to_zero_available():
    """PRD 3.4: "For each line the source lot's `available_qty` is reduced by the
    line's `quantity`, floored at zero."

    Design: Difficulty/combinatorial_formula/available_quantity_draw_order_evaluation_pinned
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        coa_required=False, ingredient_overrides={"storage_target_c": 20,
                                                   "storage_tolerance_c": 5,
                                                   "shelf_life_days": 365})
    lotR = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                       received_qty=100)
    release_lot(lotR["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=100)
    add_consumed_lot(run["id"], lotR["id"], 60)
    add_consumed_lot(run["id"], lotR["id"], 40)
    finalize_run(run["id"], current_run_version(run["id"]))

    lot = validate_success(api_client.get_lot(lotR["id"], QM), 200)
    assert lot["available_qty"] == 0.0   # 100 - 60 - 40


def test_source_lot_auto_consumed_when_available_reaches_zero():
    """PRD 3.4: "Any source lot whose `available_qty` reaches exactly zero after its
    draw and that is currently `RELEASED` transitions to `CONSUMED`, the second hop of
    this cascade."

    Design: Difficulty/combinatorial_formula/available_quantity_draw_order_evaluation_pinned
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        coa_required=False, ingredient_overrides={"storage_target_c": 20,
                                                   "storage_tolerance_c": 5,
                                                   "shelf_life_days": 365})
    lotR = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                       received_qty=100)
    release_lot(lotR["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=100)
    add_consumed_lot(run["id"], lotR["id"], 60)
    add_consumed_lot(run["id"], lotR["id"], 40)
    finalize_run(run["id"], current_run_version(run["id"]))

    lot = validate_success(api_client.get_lot(lotR["id"], QM), 200)
    assert lot["status"] == "CONSUMED"
