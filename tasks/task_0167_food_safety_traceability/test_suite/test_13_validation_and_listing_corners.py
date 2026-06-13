"""Validation corners (duplicate lot code, cross-facility FK, COA allergen
undisclosed), listing reverse-reachability corners, and the consistency-model /
OCC corners.

Queue B — Corner/validations, Corner/endpoints, Corner/cross_cutting_complexity_layers,
Corner/consistency_model.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_facility, create_supplier, create_ingredient, receive_lot, release_lot,
    attach_coa, post_reading, advance_clock,
    open_run, add_consumed_lot, current_run_version, finalize_run,
    issue_hold, resolve_hold,
    create_lot_payload, finalize_payload, ApiErrorId,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["production_operator_headers"]


# --- Corner/validations ----------------------------------------------------

def test_duplicate_lot_code_same_ingredient_rejected():
    """PRD 3.2: "The `lot_code` must be unique within the pairing of facility and
    ingredient; a collision is rejected with `ERR_DUPLICATE_LOT_CODE`."

    Design: Corner/validations/duplicate_lot_code_same_ingredient_rejected
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30)
    receive_lot(facility["id"], ingredient["id"], "DUP", supplier_id=supplier["id"],
                received_qty=5)
    payload = create_lot_payload(facility["id"], ingredient["id"], "DUP",
                                 received_qty=7, supplier_id=supplier["id"])
    res = api_client.create_lot(payload, CLERK)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_LOT_CODE.value)


def test_cross_facility_supplier_reference_rejected():
    """PRD 2.8: "Body foreign-key resolution and same-facility ownership come fifth,
    yielding `ERR_CROSS_FACILITY_REFERENCE` when a referenced entity belongs to a
    different facility."

    Design: Corner/validations/cross_facility_supplier_reference_rejected
    """
    f1 = create_facility(initial_utc="2026-01-01T00:00:00Z")
    f2 = create_facility(initial_utc="2026-01-01T00:00:00Z")
    sup2 = create_supplier(f2["id"], coa_required=False)
    ing1 = create_ingredient(f1["id"], storage_target_c=4, shelf_life_days=30)
    payload = create_lot_payload(f1["id"], ing1["id"], "X", received_qty=5,
                                 supplier_id=sup2["id"])   # supplier from f2
    res = api_client.create_lot(payload, CLERK)
    validate_error(res, ApiErrorId.ERR_CROSS_FACILITY_REFERENCE.value)


def test_coa_accept_allergen_undisclosed_blocked():
    """PRD 3.3: "First, the `measured_allergen_codes` must be a subset of the
    ingredient's `declared_allergen_codes`; if the lab detected an allergen the
    ingredient never declared, acceptance is blocked with
    `ERR_COA_ALLERGEN_UNDISCLOSED`."

    Design: Corner/validations/coa_accept_allergen_undisclosed_blocked
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30,
                                   declared_allergen_codes=["MILK"])
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    coa = attach_coa(lot["id"], measured_allergen_codes=["MILK", "SOY"], pathogen_pass=True,
                     declared_shelf_life_days=30)   # SOY not declared
    res = api_client.decide_coa(coa["id"], {"decision": "ACCEPT"}, QM)
    validate_error(res, ApiErrorId.ERR_COA_ALLERGEN_UNDISCLOSED.value)


# --- Corner/endpoints ------------------------------------------------------

def test_list_lots_filtered_by_supplier_returns_array():
    """PRD 4 (Endpoint Definitions): "GET | `/traceability/lots` | List lots, filterable
    by facility_id, supplier_id, ingredient_id, status"

    Design: Corner/endpoints/list_lots_filtered_by_supplier_returns_array
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    data, meta = validate_paginated(
        api_client.list_lots(QM, params={"supplier_id": supplier["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == lot["id"]


def test_list_ccp_readings_subresource_returns_array():
    """PRD 4 (Endpoint Definitions): "GET | `/traceability/lots/{id}/ccp-readings` |
    List a lot's CCP readings"

    Design: Corner/endpoints/list_ccp_readings_subresource_returns_array
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    advance_clock(facility["id"], "2026-01-02T01:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4,
                                   storage_tolerance_c=2, shelf_life_days=30)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    reading = post_reading(lot["id"], 4, "2026-01-02T00:00:00Z")
    data, meta = validate_paginated(api_client.list_lot_ccp_readings(lot["id"], OP))
    assert len(data) == 1
    assert data[0]["id"] == reading["id"]


# --- Corner/cross_cutting_complexity_layers --------------------------------

def test_occ_stale_hold_resolve_rejected():
    """PRD 2.7: "If that value does not match the hold order's current `version` — for
    instance because a prior writer has already resolved the hold, advancing its
    version since the client read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_hold_resolve_rejected
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    release_lot(lot["id"])
    hold = issue_hold(facility["id"], lot["id"], reason="OTHER")
    stale_version = hold["version"]
    resolve_hold(hold["id"], "RELEASE", stale_version)   # advances version
    # Second resolve carries the now-stale pre-resolution version.
    res = api_client.resolve_hold_order(
        hold["id"], {"disposition": "DISPOSE", "expected_hold_order_version": stale_version}, QM)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_correct_version_finalize_succeeds():
    """PRD 2.7: "Finalizing a production run requires the request body to carry
    `expected_production_run_version`, the `version` of the run that the client last
    observed."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_finalize_succeeds
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30)
    lotR = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                       received_qty=100)
    release_lot(lotR["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=10)
    add_consumed_lot(run["id"], lotR["id"], 10)
    run_v = current_run_version(run["id"])
    finalized = validate_success(
        api_client.finalize_production_run(run["id"], finalize_payload(run_v), OP), 200)
    assert finalized["status"] == "FINALIZED"


def test_derived_available_qty_reconciled_after_partial_draw():
    """PRD 3.4: "The available quantity of a source lot is, in steady state, its
    `received_qty` minus the sum of all consumed-lot quantities drawn from it by
    finalized runs, floored at zero; quantities drawn by open or aborted runs never
    count."

    Design: Corner/cross_cutting_complexity_layers/derived_available_qty_reconciled_after_partial_draw
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30)
    lotR = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                       received_qty=100)
    release_lot(lotR["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=30)
    add_consumed_lot(run["id"], lotR["id"], 30)
    finalize_run(run["id"], current_run_version(run["id"]))

    lot = validate_success(api_client.get_lot(lotR["id"], QM), 200)
    assert lot["available_qty"] == 70.0    # 100 - 30
    assert lot["status"] == "RELEASED"      # partial draw, not consumed


# --- Corner/consistency_model ----------------------------------------------

def test_immediate_consistency_hold_visible_in_same_flow():
    """PRD 2.5: "When that happens, every secondary effect is part of the same atomic
    operation, and each mutated resource independently refreshes its `updated_at` and
    increments its `version`."
    PRD 3.6: "Every lot in the covered set that is not already in a terminal status has
    its `hold_status` set to `HELD`."

    Design: Corner/consistency_model/immediate_consistency_hold_visible_in_same_flow
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    release_lot(lot["id"])
    issue_hold(facility["id"], lot["id"], reason="ALLERGEN")
    # hold_status is immediately observable on the next GET (no lag).
    after = validate_success(api_client.get_lot(lot["id"], QM), 200)
    assert after["hold_status"] == "HELD"
