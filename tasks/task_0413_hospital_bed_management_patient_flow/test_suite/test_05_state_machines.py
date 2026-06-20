"""State-machine transitions: invalid transitions, valid reverts, terminal lockdown,
side-effect-driven transitions, and the business-rule violations that gate them.

Queue B corner section: state_machines.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, create_unit, add_bed, add_clean_bed,
    create_unit_with_clean_bed, register_encounter, register_and_admit,
    create_queued_request, assign_request, confirm_request,
    create_transfer_payload, create_block_payload, create_evs_task,
    declare_surge,
    create_assign_payload, create_evs_task_payload,
)
from test_helpers.fixtures import ADMIN, BCC, NURSE, TCA, CM, EVS


# ============================================================================
# Corner: state_machines / admit_order_from_already_pending_returns_invalid_state
# ============================================================================

def test_double_admit_order_invalid_state(api, bed_control_headers):
    """PRD §2.6: "a transition requested from a state in which it is not defined
    yields ERR_INVALID_STATE (HTTP 409)." — PRD §3.3: "When a BedControlCoordinator or
    FlowAdmin places the admit order, a REGISTERED encounter advances to ADMIT_PENDING".

    Design: Corner/state_machines/admit_order_from_already_pending_returns_invalid_state
    """
    enc = register_encounter(mrn="MS1", sex="MALE", origin="DIRECT")
    api.admit_order(enc["id"], bed_control_headers)  # REGISTERED -> ADMIT_PENDING
    res = api.admit_order(enc["id"], bed_control_headers)
    validate_error(res, "ERR_INVALID_STATE")
    fetched = validate_success(api.get_encounter(enc["id"], bed_control_headers), 200)
    assert fetched["status"] == "ADMIT_PENDING"


# ============================================================================
# Corner: state_machines / discharge_from_placed_without_order_returns_invalid_state
# ============================================================================

def test_discharge_from_placed_without_order_invalid_state(api, case_manager_headers):
    """PRD §3.6: "The actual discharge is permitted only from DISCHARGE_ORDERED".

    Design: Corner/state_machines/discharge_from_placed_without_order_returns_invalid_state
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="DWard", unit_type="MEDSURG",
                                           bed_label="DD1")
    enc = register_and_admit(mrn="MS2", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])  # PLACED, no discharge order

    res = api.discharge(enc["id"], case_manager_headers)
    validate_error(res, "ERR_INVALID_STATE")
    fetched = validate_success(api.get_encounter(enc["id"], case_manager_headers), 200)
    assert fetched["status"] == "PLACED"


# ============================================================================
# Corner: state_machines / rescind_discharge_revert_loop_to_placed
# ============================================================================

def test_rescind_discharge_reverts_to_placed(api, case_manager_headers):
    """PRD §3.6: "A discharge order can be rescinded — the DISCHARGE_ORDERED → PLACED
    revert clears discharge_order_at back to null while the patient is still in the
    bed."

    Design: Corner/state_machines/rescind_discharge_revert_loop_to_placed
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="RWard", unit_type="MEDSURG",
                                           bed_label="RR1")
    enc = register_and_admit(mrn="MS3", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)

    res = api.rescind_discharge(enc["id"], case_manager_headers)
    reverted = validate_success(res, 200)
    assert reverted["status"] == "PLACED"
    assert reverted["discharge_order_at"] is None


# ============================================================================
# Corner: state_machines / terminal_discharged_lockdown_no_further_transitions
# ============================================================================

def test_discharged_encounter_rejects_discharge_order(api, case_manager_headers):
    """PRD §2.6: "a transition requested from a state in which it is not defined yields
    ERR_INVALID_STATE (HTTP 409)." — PRD §3.6: "first orders discharge on a PLACED
    patient, advancing PLACED → DISCHARGE_ORDERED".

    Design: Corner/state_machines/terminal_discharged_lockdown_no_further_transitions
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="TWard", unit_type="MEDSURG",
                                           bed_label="TT1")
    enc = register_and_admit(mrn="MS4", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])
    api.discharge_order(enc["id"], case_manager_headers)
    api.discharge(enc["id"], case_manager_headers)  # DISCHARGED (terminal)

    res = api.discharge_order(enc["id"], case_manager_headers)
    validate_error(res, "ERR_INVALID_STATE")
    fetched = validate_success(api.get_encounter(enc["id"], case_manager_headers), 200)
    assert fetched["status"] == "DISCHARGED"


# ============================================================================
# Corner: state_machines / retire_from_clean_bed_returns_invalid_state
# ============================================================================

def test_retire_clean_bed_invalid_state(api, flow_admin_headers, charge_nurse_headers):
    """PRD §3.2: "a FlowAdmin may retire a BLOCKED bed, which is terminal" — "Each of
    these block, unblock, and retire transitions is defined only from the stated
    source state, and a request from any other state is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/retire_from_clean_bed_returns_invalid_state
    """
    unit, bed = create_unit_with_clean_bed(unit_name="RtWard", unit_type="MEDSURG",
                                           bed_label="RT1")
    res = api.retire_bed(unit["id"], bed["id"], flow_admin_headers)
    validate_error(res, "ERR_INVALID_STATE")
    fetched = validate_success(api.get_bed(unit["id"], bed["id"], charge_nurse_headers), 200)
    assert fetched["status"] == "CLEAN"


# ============================================================================
# Corner: state_machines / evstask_complete_marks_bed_clean
# ============================================================================

def test_evs_complete_marks_bed_clean(api, flow_admin_headers, charge_nurse_headers, evs_tech_headers):
    """PRD §3.9: "then completes it IN_PROGRESS → COMPLETED, which is permitted only
    when the target bed is DIRTY; completion drives that bed DIRTY → CLEAN (preserving
    sex_cohort, as routine turnover does)".

    Design: Corner/state_machines/evstask_complete_marks_bed_clean
    """
    unit = validate_success(
        api.create_unit({"name": "EWard", "unit_type": "MEDSURG"}, flow_admin_headers), 201)
    bed = validate_success(
        api.create_bed(unit["id"], {"unit_id": unit["id"], "label": "EE1"},
                       charge_nurse_headers), 201)  # DIRTY
    task = validate_success(
        api.create_evs_task({"bed_id": bed["id"], "task_type": "ROUTINE"},
                            charge_nurse_headers), 201)
    api.assign_evs_task(task["id"], {}, evs_tech_headers)
    api.start_evs_task(task["id"], evs_tech_headers)

    completed = validate_success(api.complete_evs_task(task["id"], evs_tech_headers), 200)
    assert completed["status"] == "COMPLETED"
    fetched_bed = validate_success(api.get_bed(unit["id"], bed["id"], charge_nurse_headers), 200)
    assert fetched_bed["status"] == "CLEAN"
    assert fetched_bed["sex_cohort"] == "NONE"


# ============================================================================
# Corner: state_machines / block_dirty_bed_cancels_open_evstask
# ============================================================================

def test_block_dirty_bed_cancels_open_evs_task(api, flow_admin_headers, charge_nurse_headers):
    """PRD §3.2: "Blocking a bed that was DIRTY also cancels any open turnover task on
    it."

    Design: Corner/state_machines/block_dirty_bed_cancels_open_evstask
    """
    unit = validate_success(
        api.create_unit({"name": "BWard", "unit_type": "MEDSURG"}, flow_admin_headers), 201)
    bed = validate_success(
        api.create_bed(unit["id"], {"unit_id": unit["id"], "label": "BB1"},
                       charge_nurse_headers), 201)  # DIRTY
    task = validate_success(
        api.create_evs_task({"bed_id": bed["id"], "task_type": "ROUTINE"},
                            charge_nurse_headers), 201)

    api.block_bed(unit["id"], bed["id"], create_block_payload("INFECTION_CONTROL"), charge_nurse_headers)
    fetched_task = validate_success(api.get_evs_task(task["id"], charge_nurse_headers), 200)
    assert fetched_task["status"] == "CANCELLED"
    fetched_bed = validate_success(api.get_bed(unit["id"], bed["id"], charge_nurse_headers), 200)
    assert fetched_bed["status"] == "BLOCKED"


# ============================================================================
# Corner: state_machines / surge_stand_down_drops_declared_level
# ============================================================================

def test_surge_stand_down_drops_declared_level(api, flow_admin_headers, bed_control_headers):
    """PRD §3.10: "Standing a surge down advances it OPEN → STOOD_DOWN, stamps
    stood_down_at, and recomputes the unit's declared_surge_level and
    effective_posture, which drop back if no other surge remains open."

    Design: Corner/state_machines/surge_stand_down_drops_declared_level
    """
    unit = validate_success(
        api.create_unit({"name": "SWard", "unit_type": "MEDSURG"}, flow_admin_headers), 201)
    surge = declare_surge(unit["id"], "YELLOW")

    stood = validate_success(api.stand_down_surge(surge["id"], bed_control_headers), 200)
    assert stood["status"] == "STOOD_DOWN"
    fetched_unit = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched_unit["declared_surge_level"] == "GREEN"


# ============================================================================
# Corner: state_machines / error_bed_not_dirty_on_evs_create
# ============================================================================

def test_evs_create_on_clean_bed_rejected(api, charge_nurse_headers):
    """PRD §3.9: "A manually created task is allowed only when the target bed is DIRTY
    at creation time — otherwise the request is rejected with ERR_BED_NOT_DIRTY
    (HTTP 409)".

    Design: Corner/state_machines/error_bed_not_dirty_on_evs_create
    """
    unit, bed = create_unit_with_clean_bed(unit_name="CWard", unit_type="MEDSURG",
                                           bed_label="CC9")
    res = api.create_evs_task({"bed_id": bed["id"]}, charge_nurse_headers)
    validate_error(res, "ERR_BED_NOT_DIRTY")


# ============================================================================
# Corner: state_machines / error_bed_occupied_on_block
# ============================================================================

def test_block_occupied_bed_rejected(api, charge_nurse_headers):
    """PRD §3.2: "A bed cannot be blocked while OCCUPIED, and an attempt to do so — or
    a block request missing its blocked_reason — is rejected with ERR_BED_OCCUPIED
    (HTTP 409)."

    Design: Corner/state_machines/error_bed_occupied_on_block
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="OWard", unit_type="MEDSURG",
                                           bed_label="OO1")
    enc = register_and_admit(mrn="MS5", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])  # bed OCCUPIED

    res = api.block_bed(unit["id"], bed["id"], create_block_payload("MAINTENANCE"), charge_nurse_headers)
    validate_error(res, "ERR_BED_OCCUPIED")
    fetched = validate_success(api.get_bed(unit["id"], bed["id"], charge_nurse_headers), 200)
    assert fetched["status"] == "OCCUPIED"


# ============================================================================
# Corner: state_machines / error_telemetry_required_on_assign
# ============================================================================

def test_assign_non_telemetry_bed_to_telemetry_patient_rejected(api, bed_control_headers):
    """PRD §2.11: "A patient flagged as requiring telemetry may not land on a bed that
    is not telemetry_capable — rejected with ERR_TELEMETRY_REQUIRED (HTTP 409)."

    Design: Corner/state_machines/error_telemetry_required_on_assign
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="TeWard", unit_type="MEDSURG",
                                           bed_label="TE1", telemetry_capable=False)
    enc = register_and_admit(mrn="MS7", sex="FEMALE",
                             requires_telemetry=True, origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])

    res = api.assign_bed_request(req["id"], create_assign_payload(bed["id"]), bed_control_headers)
    validate_error(res, "ERR_TELEMETRY_REQUIRED")
    fetched = validate_success(api.get_bed_request(req["id"], bed_control_headers), 200)
    assert fetched["status"] == "QUEUED"


# ============================================================================
# Corner: state_machines / error_cohort_conflict_on_assign_semiprivate
# ============================================================================

def test_assign_semiprivate_cohort_conflict_rejected(api, bed_control_headers, charge_nurse_headers):
    """PRD §2.11: "For a SEMIPRIVATE target bed, the bed's sex_cohort must be either
    NONE or equal to the patient's sex; a conflicting cohort is rejected with
    ERR_COHORT_CONFLICT (HTTP 409)". PRD §3.2: "it preserves the bed's sex_cohort
    (routine turnover keeps whatever cohort the room last held)".

    Design: Corner/state_machines/error_cohort_conflict_on_assign_semiprivate
    """
    set_clock("2026-06-05T08:00:00Z")
    unit = create_unit(name="CoWard", unit_type="MEDSURG")
    b1 = add_clean_bed(unit["id"], label="CO1", room_type="SEMIPRIVATE")
    b2 = add_clean_bed(unit["id"], label="CO2", room_type="SEMIPRIVATE")
    # Place a MALE in B1 (cohort -> MALE), transfer to B2, re-clean B1 (cohort MALE preserved).
    em = register_and_admit(mrn="MS8", sex="MALE", origin="DIRECT")
    rm = create_queued_request(em["id"])
    assign_request(rm["id"], b1["id"])
    confirm_request(rm["id"], b1["version"])
    api.transfer_encounter(em["id"], create_transfer_payload(b2["id"]), bed_control_headers)
    api.mark_clean_bed(unit["id"], b1["id"], charge_nurse_headers)  # CLEAN, cohort MALE
    # FEMALE patient now wants B1.
    ef = register_and_admit(mrn="MS9", sex="FEMALE", origin="DIRECT")
    rf = create_queued_request(ef["id"])

    res = api.assign_bed_request(rf["id"], create_assign_payload(b1["id"]), bed_control_headers)
    validate_error(res, "ERR_COHORT_CONFLICT")
    fetched = validate_success(api.get_bed_request(rf["id"], bed_control_headers), 200)
    assert fetched["status"] == "QUEUED"


# ============================================================================
# Corner: state_machines / bedrequest_expires_after_two_ops_runs
# ============================================================================

def test_bedrequest_expires_after_two_ops_runs(api, transfer_agent_headers, flow_admin_headers):
    """PRD §3.4: "The operations run (described in Section 3.9) advances a logical
    counter and sweeps the queue: any request still QUEUED whose age — the current
    operations counter minus its queued_ops_index — has reached 2 or more is moved to
    EXPIRED."

    Design: Corner/state_machines/bedrequest_expires_after_two_ops_runs
    """
    enc = register_and_admit(mrn="MS10", sex="MALE", origin="ED")
    req = validate_success(
        api.create_bed_request({"encounter_id": enc["id"]}, transfer_agent_headers), 201)
    api.ops_run(flow_admin_headers)  # run 1
    api.ops_run(flow_admin_headers)  # run 2 -> age 2 >= 2 -> EXPIRED

    fetched = validate_success(api.get_bed_request(req["id"], transfer_agent_headers), 200)
    assert fetched["status"] == "EXPIRED"
