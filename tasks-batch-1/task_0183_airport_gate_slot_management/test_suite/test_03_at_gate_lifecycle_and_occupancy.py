"""At-gate lifecycle (occupy, tow, return, depart, cancel), the tow cycle,
occupancy-counter reconciliation, and the compensating-occupancy invariants.

Queue A: non_linear_state_machine (tow cycle), combinatorial_formula
(occupancy_reconcile pinned order, mode c), compensating_invariant
(occupy/release and tow/return).
Queue B: derived_counter_visible_immediately_after_occupy,
occupy_twice_idempotency_rejected.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures

GATE_CTRL = TEST_USERS["gate_controller_headers"]
RAMP = TEST_USERS["ramp_agent_headers"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine: OCCUPIED -> TOWED_AWAY -> OCCUPIED cycle
# ---------------------------------------------------------------------------
def test_tow_return_cycle_clears_tow_target(api):
    """PRD §3.5: "The controller later returns the aircraft to its gate, moving
    the assignment from TOWED_AWAY back to OCCUPIED. The return decrements the
    previous tow target's occupancy_count by 1, clears tow_target_stand_id back to
    null, and moves the flight's handling_status from TOWED_OFF back to AT_GATE."

    Design: Difficulty/non_linear_state_machine/gateassignment_tow_cycle_occupied_towed_occupied
    """
    gate, remote, flight, assignment = fixtures.setup_towed_assignment(
        gate_kwargs={"code": "D1", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "BA7", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T12:00:00Z", "min_turn_minutes": 45},
        remote_kwargs={"code": "R2", "max_wingspan_m": 80, "capacity": 1})
    data = validate_success(api.return_gate_assignment(assignment["id"], GATE_CTRL), 200)
    assert data["status"] == "OCCUPIED"
    assert data["tow_target_stand_id"] is None
    remote_after = validate_success(api.get_remote_stand(remote["id"], GATE_CTRL), 200)
    assert remote_after["occupancy_count"] == 0


def test_tow_return_cycle_restores_handling_at_gate(api):
    """PRD §3.5: "moves the flight's handling_status from TOWED_OFF back to AT_GATE."

    Design: Difficulty/non_linear_state_machine/gateassignment_tow_cycle_occupied_towed_occupied
    """
    gate, remote, flight, assignment = fixtures.setup_towed_assignment(
        gate_kwargs={"code": "D2", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "BA8", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T12:00:00Z", "min_turn_minutes": 45},
        remote_kwargs={"code": "R2b", "max_wingspan_m": 80, "capacity": 1})
    flight_towed = validate_success(api.get_flight(flight["id"], GATE_CTRL), 200)
    assert flight_towed["handling_status"] == "TOWED_OFF"
    validate_success(api.return_gate_assignment(assignment["id"], GATE_CTRL), 200)
    flight_after = validate_success(api.get_flight(flight["id"], GATE_CTRL), 200)
    assert flight_after["handling_status"] == "AT_GATE"


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula (mode c): cancel TOWED_AWAY, pinned reconcile order
# ---------------------------------------------------------------------------
def test_cancel_towed_assignment_clears_both_counters(api):
    """PRD §2.6: "first, if the assignment is currently TOWED_AWAY, decrement the
    tow target RemoteStand's occupancy_count by 1 and then clear tow_target_stand_id
    to null (unwinding the tow); second, decrement the source stand's counter by 1
    — active_assignment_count for a GATE assignment or occupancy_count for a REMOTE
    assignment; third, set the assignment's status to its terminal value."
    PRD §3.5: "if it was specifically TOWED_AWAY, the tow target RemoteStand's
    occupancy_count is also decremented as the tow is unwound."

    Design: Difficulty/combinatorial_formula/occupancy_reconcile_pinned_order_mode_c
    """
    gate, remote, flight, assignment = fixtures.setup_towed_assignment(
        gate_kwargs={"code": "C1", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "AA9", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T12:00:00Z", "min_turn_minutes": 45},
        remote_kwargs={"code": "R1", "max_wingspan_m": 80, "capacity": 1})
    data = validate_success(api.cancel_gate_assignment(assignment["id"], GATE_CTRL), 200)
    assert data["status"] == "CANCELLED"
    gate_after = validate_success(api.get_gate(gate["id"], GATE_CTRL), 200)
    remote_after = validate_success(api.get_remote_stand(remote["id"], GATE_CTRL), 200)
    assert gate_after["active_assignment_count"] == 0
    assert remote_after["occupancy_count"] == 0


def test_cancel_towed_assignment_lands_cancelled(api):
    """PRD §3.5: "Cancellation is legal while the assignment is PLANNED, OCCUPIED,
    or TOWED_AWAY, and moves it to CANCELLED."

    Design: Difficulty/combinatorial_formula/occupancy_reconcile_pinned_order_mode_c
    """
    gate, remote, flight, assignment = fixtures.setup_towed_assignment(
        gate_kwargs={"code": "C2", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "AA10", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T12:00:00Z", "min_turn_minutes": 45},
        remote_kwargs={"code": "R1b", "max_wingspan_m": 80, "capacity": 1})
    data = validate_success(api.cancel_gate_assignment(assignment["id"], GATE_CTRL), 200)
    assert data["status"] == "CANCELLED"
    assert data["tow_target_stand_id"] is None


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant #1: gate occupancy conserved across occupy/depart
# ---------------------------------------------------------------------------
def test_gate_occupancy_conserved_across_occupy_depart(api):
    """PRD §3.5: "a RampAgent records the aircraft's departure by departing the
    assignment, which moves it from OCCUPIED to RELEASED, decrements the stand's
    occupancy counter by 1, and advances the flight's handling_status from AT_GATE
    to DEPARTED. Across the occupy-then-depart pair the net change to total
    occupancy (the gate's active_assignment_count plus the sum of remote-stand
    occupancy_count values) is zero relative to the pre-occupy baseline."

    Design: Difficulty/compensating_invariant/stand_occupancy_conserved_across_occupy_release
    """
    gate, flight, assignment = fixtures.setup_occupied_gate_assignment(
        gate_kwargs={"code": "J1", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "DL2", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z")
    data = validate_success(api.depart_gate_assignment(assignment["id"], RAMP), 200)
    assert data["status"] == "RELEASED"
    gate_after = validate_success(api.get_gate(gate["id"], GATE_CTRL), 200)
    assert gate_after["active_assignment_count"] == 0


def test_gate_occupancy_one_after_occupy_before_depart(api):
    """PRD §3.5: "Occupying increments the stand's occupancy counter by 1 —
    active_assignment_count on the gate or occupancy_count on the remote stand."

    Design: Difficulty/compensating_invariant/stand_occupancy_conserved_across_occupy_release
    """
    gate, flight, assignment = fixtures.setup_occupied_gate_assignment(
        gate_kwargs={"code": "J1b", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "DL2b", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z")
    gate_occupied = validate_success(api.get_gate(gate["id"], GATE_CTRL), 200)
    assert gate_occupied["active_assignment_count"] == 1
    validate_success(api.depart_gate_assignment(assignment["id"], RAMP), 200)
    gate_after = validate_success(api.get_gate(gate["id"], GATE_CTRL), 200)
    assert gate_after["active_assignment_count"] == 0


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant #2: tow-target occupancy conserved across tow/return
# ---------------------------------------------------------------------------
def test_tow_target_occupancy_conserved_across_tow_return(api):
    """PRD §3.5: "The tow and its return are an exact compensating pair: the
    increment on tow and the decrement on return leave the target stand's
    occupancy_count precisely at the value it held before the tow, with no drift."

    Design: Difficulty/compensating_invariant/tow_target_occupancy_conserved_across_tow_return
    """
    gate, remote, flight, assignment = fixtures.setup_towed_assignment(
        gate_kwargs={"code": "J2", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "DL3", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T12:00:00Z", "min_turn_minutes": 45},
        remote_kwargs={"code": "R10", "max_wingspan_m": 80, "capacity": 1})
    remote_towed = validate_success(api.get_remote_stand(remote["id"], GATE_CTRL), 200)
    assert remote_towed["occupancy_count"] == 1
    data = validate_success(api.return_gate_assignment(assignment["id"], GATE_CTRL), 200)
    assert data["status"] == "OCCUPIED"
    remote_after = validate_success(api.get_remote_stand(remote["id"], GATE_CTRL), 200)
    assert remote_after["occupancy_count"] == 0


def test_tow_increments_target_occupancy_count(api):
    """PRD §3.5: "A successful tow records the destination in tow_target_stand_id,
    increments that target RemoteStand's occupancy_count by 1 while the source
    gate's count remains held."

    Design: Difficulty/compensating_invariant/tow_target_occupancy_conserved_across_tow_return
    """
    gate, remote, flight, assignment = fixtures.setup_towed_assignment(
        gate_kwargs={"code": "J3", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "DL4", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T12:00:00Z", "min_turn_minutes": 45},
        remote_kwargs={"code": "R10b", "max_wingspan_m": 80, "capacity": 1})
    remote_towed = validate_success(api.get_remote_stand(remote["id"], GATE_CTRL), 200)
    assert remote_towed["occupancy_count"] == 1
    assert assignment["tow_target_stand_id"] is None  # pre-tow snapshot
    ga = validate_success(api.get_gate_assignment(assignment["id"], GATE_CTRL), 200)
    assert ga["tow_target_stand_id"] == remote["id"]
    gate_after = validate_success(api.get_gate(gate["id"], GATE_CTRL), 200)
    assert gate_after["active_assignment_count"] == 1


# ---------------------------------------------------------------------------
# Queue B — consistency: derived counter visible immediately after occupy
# ---------------------------------------------------------------------------
def test_derived_counter_visible_immediately_after_occupy(api):
    """PRD §2.6: "On a Gate, active_assignment_count is the number of
    GateAssignment rows on that gate whose status is either OCCUPIED or TOWED_AWAY
    ... Both counters start at 0 and are reconciled on every assignment create,
    occupy, tow, return, depart, cancel, and on the IROPS cascades."

    Design: Corner/consistency_model/derived_counter_visible_immediately_after_occupy
    """
    gate, flight, assignment = fixtures.setup_occupied_gate_assignment(
        gate_kwargs={"code": "CM1", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "CM9", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z")
    data = validate_success(api.get_gate(gate["id"], GATE_CTRL), 200)
    assert data["active_assignment_count"] == 1


# ---------------------------------------------------------------------------
# Queue B — idempotency: occupy twice rejected
# ---------------------------------------------------------------------------
def test_occupy_twice_idempotency_rejected(api):
    """PRD §3.5: "Each of occupy, tow, return, and depart requires the assignment
    to be in the specific from-state named above; attempting any of them from the
    wrong state is an ERR_INVALID_STATE rejection."

    Design: Corner/state_machines/occupy_twice_idempotency_rejected
    """
    gate, flight, assignment = fixtures.setup_occupied_gate_assignment(
        gate_kwargs={"code": "SMG1", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "SM4", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z")
    resp = api.occupy_gate_assignment(assignment["id"], RAMP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
