"""Validation precedence: when two finalize/release gates both fail, the higher-
priority gate's error is returned. The PRD states the order explicitly.

Queue A — Difficulty/priority_pair_validation_conflict.
"""
import pytest
from test_helpers import (
    api_client, validate_error,
    setup_facility_supplier_ingredient, receive_lot, release_lot, issue_hold,
    resolve_hold, attach_coa, decide_coa,
    open_run, add_consumed_lot, current_run_version, advance_clock,
    create_supplier, create_ingredient, create_facility,
    finalize_payload, ApiErrorId,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
OP = TEST_USERS["production_operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/hold_beats_insufficient_qty_on_finalize
# ---------------------------------------------------------------------------

def test_finalize_hold_error_beats_insufficient_quantity():
    """PRD 3.4: "Then every source lot's `hold_status` must be `FREE`, otherwise
    `ERR_LOT_ON_HOLD`."
    PRD 3.4: "Finally, every line's `quantity` must not exceed its source lot's
    `available_qty`, otherwise `ERR_INSUFFICIENT_LOT_QTY`."

    Design: Difficulty/priority_pair_validation_conflict/hold_beats_insufficient_qty_on_finalize
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        coa_required=False, ingredient_overrides={"storage_target_c": 20,
                                                   "storage_tolerance_c": 5,
                                                   "shelf_life_days": 365})
    lotR = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                       received_qty=10)
    release_lot(lotR["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=5)
    add_consumed_lot(run["id"], lotR["id"], 999)        # exceeds available_qty
    issue_hold(facility["id"], lotR["id"], reason="ALLERGEN")   # source lot now HELD

    run_v = current_run_version(run["id"])
    res = api_client.finalize_production_run(run["id"], finalize_payload(run_v), OP)
    # Hold gate (earlier in the precondition list) wins over the quantity gate.
    validate_error(res, ApiErrorId.ERR_LOT_ON_HOLD.value)


def test_finalize_quantity_error_surfaces_once_hold_cleared():
    """PRD 3.4: "Then every source lot's `hold_status` must be `FREE`, otherwise
    `ERR_LOT_ON_HOLD`."
    PRD 3.4: "Finally, every line's `quantity` must not exceed its source lot's
    `available_qty`, otherwise `ERR_INSUFFICIENT_LOT_QTY`."

    Design: Difficulty/priority_pair_validation_conflict/hold_beats_insufficient_qty_on_finalize
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        coa_required=False, ingredient_overrides={"storage_target_c": 20,
                                                   "storage_tolerance_c": 5,
                                                   "shelf_life_days": 365})
    lotR = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                       received_qty=10)
    release_lot(lotR["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=5)
    add_consumed_lot(run["id"], lotR["id"], 999)        # exceeds available_qty
    hold = issue_hold(facility["id"], lotR["id"], reason="ALLERGEN")

    # With the hold ACTIVE, the safety error pre-empts the quantity error.
    res_held = api_client.finalize_production_run(
        run["id"], finalize_payload(current_run_version(run["id"])), OP)
    validate_error(res_held, ApiErrorId.ERR_LOT_ON_HOLD.value)

    # Release the hold so hold_status returns to FREE; now the lower-priority
    # quantity gate is reached and its error surfaces.
    resolve_hold(hold["id"], "RELEASE", hold["version"])
    res_qty = api_client.finalize_production_run(
        run["id"], finalize_payload(current_run_version(run["id"])), OP)
    validate_error(res_qty, ApiErrorId.ERR_INSUFFICIENT_LOT_QTY.value)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/coa_gate_beats_expiry_on_release
# ---------------------------------------------------------------------------

def test_release_coa_error_beats_expiry():
    """PRD 3.2: "if the supplier requires a certificate and the lot is raw material,
    its `coa_status` is `ACCEPTED`, otherwise `ERR_COA_NOT_ACCEPTED`; and the
    facility's `current_utc` is strictly earlier than the lot's
    `effective_expiration_date`, otherwise `ERR_LOT_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/coa_gate_beats_expiry_on_release
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=4,
                                   storage_tolerance_c=2, shelf_life_days=10,
                                   declared_allergen_codes=["MILK"])
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5, production_date="2026-01-01T00:00:00Z")
    # effective_expiration 2026-01-11; advance clock past it, coa_status still PENDING.
    advance_clock(facility["id"], "2026-01-20T00:00:00Z")

    res = api_client.release_lot(lot["id"], QM)
    # COA-acceptance gate precedes the expiry gate in the ordered release checks.
    validate_error(res, ApiErrorId.ERR_COA_NOT_ACCEPTED.value)


def test_release_expiry_error_surfaces_once_coa_accepted():
    """PRD 3.2: "if the supplier requires a certificate and the lot is raw material,
    its `coa_status` is `ACCEPTED`, otherwise `ERR_COA_NOT_ACCEPTED`; and the
    facility's `current_utc` is strictly earlier than the lot's
    `effective_expiration_date`, otherwise `ERR_LOT_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/coa_gate_beats_expiry_on_release
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=4,
                                   storage_tolerance_c=2, shelf_life_days=10,
                                   declared_allergen_codes=["MILK"])
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5, production_date="2026-01-01T00:00:00Z")
    # Accept a COA attesting a >= ingredient shelf life so effective_expiration stays
    # 2026-01-11, then advance the clock past it. COA gate now satisfied -> expiry fires.
    coa = attach_coa(lot["id"], measured_allergen_codes=["MILK"], pathogen_pass=True,
                     declared_shelf_life_days=10)
    decide_coa(coa["id"], "ACCEPT")
    advance_clock(facility["id"], "2026-01-20T00:00:00Z")

    res = api_client.release_lot(lot["id"], QM)
    # With the COA gate satisfied, the lower-priority expiry gate is reached.
    validate_error(res, ApiErrorId.ERR_LOT_EXPIRED.value)
