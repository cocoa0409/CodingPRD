"""Placement safety checks, validation precedence, cross-entity gating, and
single-occupancy / single-task resource exclusivity.

Queue A difficulty rules: priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, create_unit, add_clean_bed, add_bed,
    create_unit_with_clean_bed, register_and_admit,
    create_queued_request, assign_request, confirm_request,
    create_transfer_payload, create_block_payload, open_barrier,
    create_assign_payload, create_confirm_payload, create_evs_task_payload,
)
from test_helpers.fixtures import ADMIN, BCC, NURSE, TCA, CM


# ============================================================================
# Difficulty: priority_pair_validation_conflict / isolation_safety_beats_bed_availability
# ============================================================================

def test_isolation_error_wins_over_availability_on_transfer(api, bed_control_headers):
    """PRD §2.11: "When several of these conditions could apply, they are evaluated
    in the order listed here — isolation, then telemetry, then cohort, then
    availability — so the returned error is deterministic".

    Design: Difficulty/priority_pair_validation_conflict/isolation_safety_beats_bed_availability
    """
    set_clock("2026-06-04T13:00:00Z")
    unit = create_unit(name="ICU3", unit_type="ICU", gmlos_days=5)
    b1 = add_clean_bed(unit["id"], label="X1", isolation_capable=True)
    b2 = add_bed(unit["id"], label="X2", isolation_capable=False)  # DIRTY + non-iso
    enc = register_and_admit(mrn="M700", sex="FEMALE",
                             requires_isolation=True, origin="DIRECT")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], b1["id"])
    confirm_request(req["id"], b1["version"])

    res = api.transfer_encounter(enc["id"], create_transfer_payload(b2["id"]),
                                 bed_control_headers)
    validate_error(res, "ERR_ISOLATION_REQUIRED")


def test_isolation_conflict_leaves_patient_in_current_bed(api, bed_control_headers):
    """PRD §2.11: "a patient flagged as requiring isolation may not land on a bed
    that is not isolation_capable — a violation is rejected with
    ERR_ISOLATION_REQUIRED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/isolation_safety_beats_bed_availability
    """
    set_clock("2026-06-04T13:00:00Z")
    unit = create_unit(name="ICU3", unit_type="ICU", gmlos_days=5)
    b1 = add_clean_bed(unit["id"], label="X1", isolation_capable=True)
    b2 = add_bed(unit["id"], label="X2", isolation_capable=False)
    enc = register_and_admit(mrn="M700", sex="FEMALE",
                             requires_isolation=True, origin="DIRECT")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], b1["id"])
    confirm_request(req["id"], b1["version"])
    api.transfer_encounter(enc["id"], create_transfer_payload(b2["id"]), bed_control_headers)

    fetched = validate_success(api.get_encounter(enc["id"], bed_control_headers), 200)
    assert fetched["current_bed_id"] == b1["id"], "rejected transfer leaves patient in B1"


# ============================================================================
# Difficulty: priority_pair_validation_conflict / invalid_state_beats_open_barriers_on_discharge
# ============================================================================

def test_invalid_state_wins_over_open_barriers_on_discharge(api, case_manager_headers):
    """PRD §2.6: "Only after these structural checks pass does the system evaluate
    state legality: a transition requested from a state in which it is not defined
    yields ERR_INVALID_STATE (HTTP 409). Business-rule checks specific to each
    workflow — isolation, telemetry, cohort, bed availability, barriers, and so on,
    described in Section 3 — are evaluated after the state check."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_open_barriers_on_discharge
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS5", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="P1")
    enc = register_and_admit(mrn="M800", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])  # now PLACED, not DISCHARGE_ORDERED
    open_barrier(enc["id"], "TRANSPORT", note="no ride")

    res = api.discharge(enc["id"], case_manager_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_discharge_from_placed_with_barrier_leaves_placed(api, case_manager_headers):
    """PRD §3.6: "The actual discharge is permitted only from DISCHARGE_ORDERED".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_open_barriers_on_discharge
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS5", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="P1")
    enc = register_and_admit(mrn="M800", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    open_barrier(enc["id"], "TRANSPORT")
    api.discharge(enc["id"], case_manager_headers)

    fetched = validate_success(api.get_encounter(enc["id"], case_manager_headers), 200)
    assert fetched["status"] == "PLACED"


# ============================================================================
# Difficulty: cross_entity_state_dependency / confirm_requires_bed_clean_bedrequest_to_bed
# ============================================================================

def test_confirm_blocked_bed_rejected_not_available(api, bed_control_headers, charge_nurse_headers):
    """PRD §3.5: "The confirmation is permitted only when the request is ASSIGNED,
    the assigned bed is still CLEAN" — PRD §2.11: "the target bed must be CLEAN; a bed
    in any other status is rejected with ERR_BED_NOT_AVAILABLE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_bed_clean_bedrequest_to_bed
    """
    set_clock("2026-06-04T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS7", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="C1")
    enc = register_and_admit(mrn="M111", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    blocked = validate_success(
        api.block_bed(unit["id"], bed["id"],
                      create_block_payload("MAINTENANCE"), charge_nurse_headers), 200)

    res = api.confirm_bed_request(req["id"], create_confirm_payload(blocked["version"]),
                                  bed_control_headers)
    validate_error(res, "ERR_BED_NOT_AVAILABLE")


def test_confirm_blocked_bed_leaves_request_assigned(api, bed_control_headers, charge_nurse_headers):
    """PRD §2.11: "the target bed must be CLEAN; a bed in any other status is rejected
    with ERR_BED_NOT_AVAILABLE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_bed_clean_bedrequest_to_bed
    """
    set_clock("2026-06-04T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS7", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="C1")
    enc = register_and_admit(mrn="M111", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    blocked = validate_success(
        api.block_bed(unit["id"], bed["id"],
                      create_block_payload("MAINTENANCE"), charge_nurse_headers), 200)
    api.confirm_bed_request(req["id"], create_confirm_payload(blocked["version"]),
                            bed_control_headers)

    fetched = validate_success(api.get_bed_request(req["id"], bed_control_headers), 200)
    assert fetched["status"] == "ASSIGNED"


# ============================================================================
# Difficulty: cross_entity_state_dependency / discharge_requires_zero_barriers_encounter_to_barrier
# ============================================================================

def test_discharge_with_open_barrier_rejected(api, case_manager_headers):
    """PRD §3.6: "The actual discharge is permitted only from DISCHARGE_ORDERED and
    only when the encounter has zero OPEN discharge barriers; a discharge attempted
    while any barrier remains open is rejected with ERR_OPEN_BARRIERS (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/discharge_requires_zero_barriers_encounter_to_barrier
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS8", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="B8")
    enc = register_and_admit(mrn="M222", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)
    open_barrier(enc["id"], "PHARMACY")

    res = api.discharge(enc["id"], case_manager_headers)
    validate_error(res, "ERR_OPEN_BARRIERS")


def test_discharge_succeeds_after_barrier_resolved(api, case_manager_headers):
    """PRD §3.8: "A CaseManager or FlowAdmin resolves an OPEN barrier, advancing it
    OPEN → RESOLVED, stamping resolved_at, and decrementing the encounter's
    open_barrier_count. Because discharge requires open_barrier_count to be zero,
    the resolve action is what ultimately clears the path to discharge."

    Design: Difficulty/cross_entity_state_dependency/discharge_requires_zero_barriers_encounter_to_barrier
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS8", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="B8")
    enc = register_and_admit(mrn="M222", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)
    barrier = open_barrier(enc["id"], "PHARMACY")
    # first attempt fails
    validate_error(api.discharge(enc["id"], case_manager_headers), "ERR_OPEN_BARRIERS")
    api.resolve_discharge_barrier(barrier["id"], case_manager_headers)

    discharged = validate_success(api.discharge(enc["id"], case_manager_headers), 200)
    assert discharged["status"] == "DISCHARGED"


# ============================================================================
# Difficulty: resource_temporal_overlap / bed_single_occupancy_confirm_into_taken_bed
# ============================================================================

def test_second_confirm_into_taken_bed_rejected(api, bed_control_headers):
    """PRD §2.11: "the target bed must be CLEAN; a bed in any other status is rejected
    with ERR_BED_NOT_AVAILABLE (HTTP 409)." — PRD §3.5: "the assigned bed flips to
    OCCUPIED and its version increments by 1".

    Design: Difficulty/resource_temporal_overlap/bed_single_occupancy_confirm_into_taken_bed
    """
    set_clock("2026-06-04T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS9", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="S1")
    e1 = register_and_admit(mrn="M333", sex="MALE", origin="ED")
    e2 = register_and_admit(mrn="M334", sex="MALE", origin="ED")
    r1 = create_queued_request(e1["id"], preferred_unit_id=unit["id"])
    r2 = create_queued_request(e2["id"], preferred_unit_id=unit["id"])
    assign_request(r1["id"], bed["id"])
    assign_request(r2["id"], bed["id"])
    confirm_request(r1["id"], bed["version"])  # takes the bed OCCUPIED

    # r2 re-reads the now-occupied bed's version and tries to confirm.
    bed_now = validate_success(api.get_bed(unit["id"], bed["id"], bed_control_headers), 200)
    res = api.confirm_bed_request(r2["id"], create_confirm_payload(bed_now["version"]),
                                  bed_control_headers)
    validate_error(res, "ERR_BED_NOT_AVAILABLE")


def test_first_confirm_takes_bed_occupied(api, bed_control_headers):
    """PRD §3.5: "On success the request advances ASSIGNED → CONFIRMED; the assigned
    bed flips to OCCUPIED and its version increments by 1".

    Design: Difficulty/resource_temporal_overlap/bed_single_occupancy_confirm_into_taken_bed
    """
    set_clock("2026-06-04T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS9", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="S1")
    e1 = register_and_admit(mrn="M333", sex="MALE", origin="ED")
    r1 = create_queued_request(e1["id"], preferred_unit_id=unit["id"])
    assign_request(r1["id"], bed["id"])
    confirmed = confirm_request(r1["id"], bed["version"])
    assert confirmed["status"] == "CONFIRMED"

    bed_now = validate_success(api.get_bed(unit["id"], bed["id"], bed_control_headers), 200)
    assert bed_now["status"] == "OCCUPIED"


# ============================================================================
# Difficulty: resource_temporal_overlap / evstask_single_slot_per_bed
# ============================================================================

def test_second_evs_task_on_same_bed_rejected(api, charge_nurse_headers, case_manager_headers):
    """PRD §3.9: "a bed may carry at most one non-terminal task (in REQUESTED,
    ASSIGNED, or IN_PROGRESS); a second one is rejected with ERR_EVS_TASK_EXISTS
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/evstask_single_slot_per_bed
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS10", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="V1")
    enc = register_and_admit(mrn="M444", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)
    api.discharge(enc["id"], case_manager_headers)  # bed -> DIRTY + auto ROUTINE task

    res = api.create_evs_task({"bed_id": bed["id"], "task_type": "STAT"}, charge_nurse_headers)
    validate_error(res, "ERR_EVS_TASK_EXISTS")


def test_bed_dirty_after_discharge_with_auto_task(api, charge_nurse_headers, case_manager_headers):
    """PRD §3.6: "A successful discharge stamps discharged_at, freezes
    length_of_stay_hours, returns the bed to DIRTY (auto-creating a turnover task),
    clears current_bed_id to null, and appends a discharge ADT event."

    Design: Difficulty/resource_temporal_overlap/evstask_single_slot_per_bed
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="MS10", unit_type="MEDSURG",
                                           gmlos_days=3, bed_label="V1")
    enc = register_and_admit(mrn="M444", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)
    api.discharge(enc["id"], case_manager_headers)

    fetched = validate_success(api.get_bed(unit["id"], bed["id"], charge_nurse_headers), 200)
    assert fetched["status"] == "DIRTY"
