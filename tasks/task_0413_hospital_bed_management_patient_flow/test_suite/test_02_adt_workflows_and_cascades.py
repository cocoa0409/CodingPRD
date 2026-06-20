"""ADT workflows, transfer self-loop, placement cascades, and conservation invariants.

Queue A difficulty rules: non_linear_state_machine, transitive_cascade,
compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    set_clock, create_unit, add_clean_bed, add_bed,
    create_unit_with_clean_bed, register_and_admit,
    create_queued_request, assign_request, confirm_request,
    create_transfer_payload, create_block_payload,
)
from test_helpers.fixtures import ADMIN, BCC, NURSE, TCA, CM


def _place(unit, bed, enc, preferred_unit=None):
    """Assign+confirm enc (already ADMIT_PENDING/BOARDING) into a CLEAN bed."""
    overrides = {}
    if preferred_unit is not None:
        overrides["preferred_unit_id"] = preferred_unit
    req = create_queued_request(enc["id"], **overrides)
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    return req


# ============================================================================
# Difficulty: non_linear_state_machine / encounter_transfer_self_loop_on_placed
# ============================================================================

def test_transfer_keeps_encounter_placed_and_swaps_bed(api, bed_control_headers):
    """PRD §3.6: "A transfer is a self-loop that keeps the encounter PLACED while
    swapping beds." — "sets current_bed_id to the target bed and takes that target
    OCCUPIED".

    Design: Difficulty/non_linear_state_machine/encounter_transfer_self_loop_on_placed
    """
    set_clock("2026-06-04T08:00:00Z")
    unit = create_unit(name="MS2", unit_type="MEDSURG", gmlos_days=3)
    b1 = add_clean_bed(unit["id"], label="T1")
    b2 = add_clean_bed(unit["id"], label="T2")
    enc = register_and_admit(mrn="M300", sex="MALE", origin="DIRECT")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], b1["id"])
    confirm_request(req["id"], b1["version"])

    res = api.transfer_encounter(enc["id"], create_transfer_payload(b2["id"]),
                                 bed_control_headers)
    moved = validate_success(res, 200)
    assert moved["status"] == "PLACED"
    assert moved["current_bed_id"] == b2["id"]


def test_transfer_records_transferred_from_bed(api, bed_control_headers):
    """PRD §3.6: "On a valid transfer the system records transferred_from_bed_id as
    the patient's current bed".

    Design: Difficulty/non_linear_state_machine/encounter_transfer_self_loop_on_placed
    """
    set_clock("2026-06-04T08:00:00Z")
    unit = create_unit(name="MS2", unit_type="MEDSURG", gmlos_days=3)
    b1 = add_clean_bed(unit["id"], label="T1")
    b2 = add_clean_bed(unit["id"], label="T2")
    enc = register_and_admit(mrn="M300", sex="MALE", origin="DIRECT")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], b1["id"])
    confirm_request(req["id"], b1["version"])

    moved = validate_success(
        api.transfer_encounter(enc["id"], create_transfer_payload(b2["id"]),
                               bed_control_headers), 200)
    assert moved["transferred_from_bed_id"] == b1["id"]


# ============================================================================
# Difficulty: non_linear_state_machine / bedrequest_release_revert_loop
# ============================================================================

def test_release_reverts_assigned_request_to_queued(api, bed_control_headers):
    """PRD §3.4: "An assigned request can be released back to the queue by a
    BedControlCoordinator or TransferCenterAgent: the ASSIGNED → QUEUED transition
    clears assigned_bed_id and match_score to null, releases the bed reservation".

    Design: Difficulty/non_linear_state_machine/bedrequest_release_revert_loop
    """
    set_clock("2026-06-04T10:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS3", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="R1B")
    enc = register_and_admit(mrn="M400", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], bed["id"])

    res = api.release_bed_request(req["id"], bed_control_headers)
    released = validate_success(res, 200)
    assert released["status"] == "QUEUED"


def test_release_nulls_assigned_bed_and_score(api, bed_control_headers):
    """PRD §3.4: "the ASSIGNED → QUEUED transition clears assigned_bed_id and
    match_score to null, releases the bed reservation".

    Design: Difficulty/non_linear_state_machine/bedrequest_release_revert_loop
    """
    set_clock("2026-06-04T10:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS3", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="R1B")
    enc = register_and_admit(mrn="M400", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], bed["id"])

    released = validate_success(api.release_bed_request(req["id"], bed_control_headers), 200)
    assert released["assigned_bed_id"] is None
    assert released["match_score"] is None


# ============================================================================
# Difficulty: transitive_cascade / discharge_cascade_depth3_bed_evstask_unit
# ============================================================================

def test_discharge_cascades_bed_to_dirty_and_unit_count(api, bed_control_headers,
                                                         charge_nurse_headers, case_manager_headers):
    """PRD §3.6: "A successful discharge stamps discharged_at, freezes
    length_of_stay_hours, returns the bed to DIRTY (auto-creating a turnover task),
    clears current_bed_id to null".

    Design: Difficulty/transitive_cascade/discharge_cascade_depth3_bed_evstask_unit
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS4", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="D1",
                                           isolation_capable=False)
    enc = register_and_admit(mrn="M500", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)
    set_clock("2026-06-05T15:00:00Z")

    discharged = validate_success(api.discharge(enc["id"], case_manager_headers), 200)
    assert discharged["status"] == "DISCHARGED"

    fetched_bed = validate_success(api.get_bed(unit["id"], bed["id"], charge_nurse_headers), 200)
    assert fetched_bed["status"] == "DIRTY"
    fetched_unit = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched_unit["occupied_bed_count"] == 0


def test_discharge_auto_creates_routine_evs_task(api, charge_nurse_headers, case_manager_headers):
    """PRD §3.2: "the system automatically opens a turnover task for that bed (a fresh
    task in REQUESTED status, typed ISOLATION if the departing patient required
    isolation and ROUTINE otherwise)."

    Design: Difficulty/transitive_cascade/discharge_cascade_depth3_bed_evstask_unit
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS4", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="D1",
                                           isolation_capable=False)
    enc = register_and_admit(mrn="M500", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)
    set_clock("2026-06-05T15:00:00Z")
    api.discharge(enc["id"], case_manager_headers)

    from test_helpers import validate_paginated
    tasks, _ = validate_paginated(api.list_evs_tasks(charge_nurse_headers, params={"bed_id": bed["id"]}))
    assert len(tasks) >= 1, "discharge auto-creates a turnover task"
    task = tasks[0]
    assert task["status"] == "REQUESTED"
    assert task["task_type"] == "ROUTINE", "non-isolation patient -> ROUTINE task"


# ============================================================================
# Difficulty: transitive_cascade / transfer_cascade_depth2_old_bed_evstask
# ============================================================================

def test_transfer_returns_old_bed_to_dirty(api, bed_control_headers):
    """PRD §3.6: "On a valid transfer the system records transferred_from_bed_id as
    the patient's current bed, returns that old bed to DIRTY (auto-creating a turnover
    task for it)".

    Design: Difficulty/transitive_cascade/transfer_cascade_depth2_old_bed_evstask
    """
    set_clock("2026-06-04T12:00:00Z")
    unit = create_unit(name="ICU2", unit_type="ICU", gmlos_days=5)
    b1 = add_clean_bed(unit["id"], label="I1", isolation_capable=True)
    b2 = add_clean_bed(unit["id"], label="I2", isolation_capable=True)
    enc = register_and_admit(mrn="M600", sex="MALE",
                             requires_isolation=True, origin="DIRECT")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], b1["id"])
    confirm_request(req["id"], b1["version"])

    moved = validate_success(
        api.transfer_encounter(enc["id"], create_transfer_payload(b2["id"]),
                               bed_control_headers), 200)
    assert moved["current_bed_id"] == b2["id"]
    fetched_b1 = validate_success(api.get_bed(unit["id"], b1["id"], bed_control_headers), 200)
    assert fetched_b1["status"] == "DIRTY"


def test_transfer_old_bed_evs_task_typed_isolation(api, bed_control_headers, charge_nurse_headers):
    """PRD §3.2: "the system automatically opens a turnover task for that bed (a fresh
    task in REQUESTED status, typed ISOLATION if the departing patient required
    isolation and ROUTINE otherwise)."

    Design: Difficulty/transitive_cascade/transfer_cascade_depth2_old_bed_evstask
    """
    set_clock("2026-06-04T12:00:00Z")
    unit = create_unit(name="ICU2", unit_type="ICU", gmlos_days=5)
    b1 = add_clean_bed(unit["id"], label="I1", isolation_capable=True)
    b2 = add_clean_bed(unit["id"], label="I2", isolation_capable=True)
    enc = register_and_admit(mrn="M600", sex="MALE",
                             requires_isolation=True, origin="DIRECT")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], b1["id"])
    confirm_request(req["id"], b1["version"])
    api.transfer_encounter(enc["id"], create_transfer_payload(b2["id"]), bed_control_headers)

    from test_helpers import validate_paginated
    tasks, _ = validate_paginated(
        api.list_evs_tasks(charge_nurse_headers, params={"bed_id": b1["id"]}))
    assert len(tasks) >= 1
    task = tasks[0]
    assert task["task_type"] == "ISOLATION", "isolation patient departed -> ISOLATION task"
    assert task["status"] == "REQUESTED"


# ============================================================================
# Difficulty: compensating_invariant / bed_occupancy_conservation_place_then_discharge
# ============================================================================

def test_occupied_count_returns_to_zero_after_place_then_discharge(api, bed_control_headers,
                                                                   charge_nurse_headers, case_manager_headers):
    """PRD §2.8: "occupied_bed_count is the number of beds in OCCUPIED status" —
    PRD §3.6: "A successful discharge ... returns the bed to DIRTY ... clears
    current_bed_id to null".

    Design: Difficulty/compensating_invariant/bed_occupancy_conservation_place_then_discharge
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS11", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="K1")
    enc = register_and_admit(mrn="M555", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)

    discharged = validate_success(api.discharge(enc["id"], case_manager_headers), 200)
    assert discharged["status"] == "DISCHARGED"
    assert discharged["current_bed_id"] is None

    fetched_unit = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched_unit["occupied_bed_count"] == 0
    fetched_bed = validate_success(api.get_bed(unit["id"], bed["id"], charge_nurse_headers), 200)
    assert fetched_bed["status"] == "DIRTY"


def test_occupied_count_one_while_placed(api, bed_control_headers):
    """PRD §3.5: "the assigned bed flips to OCCUPIED" — PRD §2.8: "occupied_bed_count
    is the number of beds in OCCUPIED status".

    Design: Difficulty/compensating_invariant/bed_occupancy_conservation_place_then_discharge
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS11", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="K1")
    enc = register_and_admit(mrn="M555", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])

    fetched_unit = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched_unit["occupied_bed_count"] == 1


# ============================================================================
# Difficulty: compensating_invariant / unit_staffed_bed_conservation_block_then_unblock
# ============================================================================

def test_staffed_count_restored_after_block_then_unblock(api, bed_control_headers, charge_nurse_headers):
    """PRD §3.2: "the bed moves to BLOCKED, leaves staffed inventory so
    staffed_bed_count decrements" — "Unblocking a BLOCKED bed returns it to DIRTY ...
    restores it to staffed inventory".

    Design: Difficulty/compensating_invariant/unit_staffed_bed_conservation_block_then_unblock
    """
    set_clock("2026-06-04T08:00:00Z")
    unit = create_unit(name="MS12", unit_type="MEDSURG", gmlos_days=3)
    ba = add_clean_bed(unit["id"], label="G1")
    add_clean_bed(unit["id"], label="G2")
    api.block_bed(unit["id"], ba["id"], create_block_payload("STAFFING"), charge_nurse_headers)

    api.unblock_bed(unit["id"], ba["id"], charge_nurse_headers)
    fetched_unit = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched_unit["staffed_bed_count"] == 2, "block then unblock conserves staffed count"


def test_unblock_returns_bed_to_dirty(api, charge_nurse_headers):
    """PRD §3.2: "Unblocking a BLOCKED bed returns it to DIRTY, clears blocked_reason
    back to null".

    Design: Difficulty/compensating_invariant/unit_staffed_bed_conservation_block_then_unblock
    """
    set_clock("2026-06-04T08:00:00Z")
    unit = create_unit(name="MS12", unit_type="MEDSURG", gmlos_days=3)
    ba = add_clean_bed(unit["id"], label="G1")
    add_clean_bed(unit["id"], label="G2")
    api.block_bed(unit["id"], ba["id"], create_block_payload("STAFFING"), charge_nurse_headers)

    unblocked = validate_success(api.unblock_bed(unit["id"], ba["id"], charge_nurse_headers), 200)
    assert unblocked["status"] == "DIRTY"
