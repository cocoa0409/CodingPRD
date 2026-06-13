"""State-machine corners: invalid transitions, terminal lockdown, precondition
enforcement, and the clock-driven expiry sweep (including the held-lot skip).

Queue B — Corner/state_machines.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_facility_supplier_ingredient, receive_lot, release_lot,
    create_facility, create_supplier, create_ingredient,
    attach_coa, decide_coa, open_run, current_run_version, advance_clock,
    issue_hold, finalize_payload, ApiErrorId,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["production_operator_headers"]


def test_release_already_released_lot_returns_not_received():
    """PRD 3.2: "Releasing a lot is a `QualityManager` action that advances it from
    `RECEIVED` to `RELEASED`, making it consumable by production. Release requires, in
    order: the lot is in `RECEIVED` status (otherwise `ERR_LOT_NOT_RECEIVED`)"

    Design: Corner/state_machines/release_already_released_lot_returns_not_received
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(coa_required=False)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    release_lot(lot["id"])
    # Second release: lot is no longer RECEIVED.
    res = api_client.release_lot(lot["id"], QM)
    validate_error(res, ApiErrorId.ERR_LOT_NOT_RECEIVED.value)


def test_decide_coa_already_decided_returns_not_pending():
    """PRD 3.3: "the certificate must be in `PENDING` status or the decision is rejected
    with `ERR_COA_NOT_PENDING`."

    Design: Corner/state_machines/decide_coa_already_decided_returns_not_pending
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30,
                                   declared_allergen_codes=["MILK"])
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    coa = attach_coa(lot["id"], measured_allergen_codes=["MILK"], pathogen_pass=True,
                     declared_shelf_life_days=30)
    decide_coa(coa["id"], "REJECT")
    # Second decision on a now-REJECTED certificate.
    res = api_client.decide_coa(coa["id"], {"decision": "ACCEPT"}, QM)
    validate_error(res, ApiErrorId.ERR_COA_NOT_PENDING.value)


def test_coa_accept_pathogen_fail_blocked():
    """PRD 3.3: "Second, `pathogen_pass` must be true, otherwise
    `ERR_COA_PATHOGEN_FAIL`."

    Design: Corner/state_machines/coa_accept_pathogen_fail_blocked
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30,
                                   declared_allergen_codes=["MILK"])
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    coa = attach_coa(lot["id"], measured_allergen_codes=["MILK"], pathogen_pass=False,
                     declared_shelf_life_days=30)
    res = api_client.decide_coa(coa["id"], {"decision": "ACCEPT"}, QM)
    validate_error(res, ApiErrorId.ERR_COA_PATHOGEN_FAIL.value)


def test_finalize_with_no_consumed_lots_returns_error():
    """PRD 3.4: "Next, the run must hold at least one consumed-lot line, otherwise
    `ERR_NO_CONSUMED_LOTS`."

    Design: Corner/state_machines/finalize_with_no_consumed_lots_returns_error
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30)
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=10)
    run_v = current_run_version(run["id"])
    res = api_client.finalize_production_run(run["id"], finalize_payload(run_v), OP)
    validate_error(res, ApiErrorId.ERR_NO_CONSUMED_LOTS.value)


def test_clock_advance_expires_released_free_lot():
    """PRD 3.5: "Every lot that is in `RELEASED` status and whose `hold_status` is
    `FREE` and whose `effective_expiration_date` is at or before the new clock value
    transitions to `EXPIRED` and has its `version` incremented."

    Design: Corner/state_machines/clock_advance_expires_released_free_lot
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=10)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    release_lot(lot["id"])   # effective_expiration 2026-01-11
    advance_clock(facility["id"], "2026-01-15T00:00:00Z")

    after = validate_success(api_client.get_lot(lot["id"], QM), 200)
    assert after["status"] == "EXPIRED"


def test_clock_advance_skips_held_lot_expiry():
    """PRD 3.5: "A held lot is frozen and is deliberately skipped by the sweep even if
    its date has passed, since a held lot must not change status out from under an
    active investigation."

    Design: Corner/state_machines/clock_advance_skips_held_lot_expiry
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=10)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    release_lot(lot["id"])
    issue_hold(facility["id"], lot["id"], reason="OTHER")   # lot now HELD
    advance_clock(facility["id"], "2026-01-15T00:00:00Z")

    after = validate_success(api_client.get_lot(lot["id"], QM), 200)
    assert after["status"] == "RELEASED"     # skipped by the sweep
    assert after["hold_status"] == "HELD"


def test_clock_non_monotonic_rejected():
    """PRD 3.1: "the new instant must be strictly greater than the current value, and a
    non-advancing or backward step is rejected with `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/state_machines/clock_non_monotonic_rejected
    """
    facility = create_facility(initial_utc="2026-01-05T00:00:00Z")
    res = api_client.advance_clock(facility["id"], {"to_utc": "2026-01-05T00:00:00Z"}, QM)
    validate_error(res, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)
