"""Branching state machines with divergent side effects: HoldOrder dispose-branch
(destroys the covered lot) and ProductionRun abort-branch (no inventory drawn).

Queue A — Difficulty/non_linear_state_machine.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    setup_released_lot_under_hold, resolve_hold,
    setup_facility_supplier_ingredient, receive_lot, release_lot,
    open_run, add_consumed_lot,
    TEST_USERS,
)
from test_helpers import create_consumed_lot_payload  # noqa: F401 (kept for parity)

QM = TEST_USERS["quality_manager_headers"]
OP = TEST_USERS["production_operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/hold_order_branch_release_vs_dispose
# ---------------------------------------------------------------------------

def test_hold_dispose_branch_sets_hold_disposed():
    """PRD 3.7: "A dispose disposition sets the hold's `disposition` to `DISPOSED` and
    its `status` to `DISPOSED`, then destroys product."

    Design: Difficulty/non_linear_state_machine/hold_order_branch_release_vs_dispose
    """
    facility, ingredient, lot_id, hold = setup_released_lot_under_hold(
        reason="PATHOGEN", received_qty=40)
    resolved = resolve_hold(hold["id"], "DISPOSE", hold["version"])
    assert resolved["status"] == "DISPOSED"
    assert resolved["disposition"] == "DISPOSED"


def test_hold_dispose_branch_destroys_covered_lot():
    """PRD 3.7: "Every lot in the covered set that is not already terminal transitions
    to `DESTROYED` and has its `available_qty` set to zero."

    Design: Difficulty/non_linear_state_machine/hold_order_branch_release_vs_dispose
    """
    facility, ingredient, lot_id, hold = setup_released_lot_under_hold(
        reason="PATHOGEN", received_qty=40)
    resolve_hold(hold["id"], "DISPOSE", hold["version"])

    lot = validate_success(api_client.get_lot(lot_id, QM), 200)
    assert lot["status"] == "DESTROYED"
    assert lot["available_qty"] == 0.0


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/production_run_branch_finalize_vs_abort
# ---------------------------------------------------------------------------

def test_abort_branch_sets_run_aborted():
    """PRD 3.4: "Aborting a run is the sibling branch from `OPEN`, available to a
    `ProductionOperator` and permitted only while the run is `OPEN` (otherwise
    `ERR_RUN_NOT_OPEN`)."

    Design: Difficulty/non_linear_state_machine/production_run_branch_finalize_vs_abort
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        coa_required=False, ingredient_overrides={"storage_target_c": 20,
                                                   "storage_tolerance_c": 5,
                                                   "shelf_life_days": 365})
    lotR = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                       received_qty=100)
    release_lot(lotR["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=60)
    add_consumed_lot(run["id"], lotR["id"], 60)

    aborted = validate_success(api_client.abort_production_run(run["id"], OP), 200)
    assert aborted["status"] == "ABORTED"


def test_abort_branch_draws_no_inventory():
    """PRD 3.4: "An abort draws no inventory — the consumed-lot lines have no effect on
    any `available_qty` — sets the run's `status` to `ABORTED`, and increments its
    `version`."

    Design: Difficulty/non_linear_state_machine/production_run_branch_finalize_vs_abort
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        coa_required=False, ingredient_overrides={"storage_target_c": 20,
                                                   "storage_tolerance_c": 5,
                                                   "shelf_life_days": 365})
    lotR = receive_lot(facility["id"], ingredient["id"], "R", supplier_id=supplier["id"],
                       received_qty=100)
    release_lot(lotR["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=60)
    add_consumed_lot(run["id"], lotR["id"], 60)
    api_client.abort_production_run(run["id"], OP)

    lot = validate_success(api_client.get_lot(lotR["id"], QM), 200)
    assert lot["available_qty"] == 100.0   # unchanged by abort
    assert lot["status"] == "RELEASED"      # not consumed
