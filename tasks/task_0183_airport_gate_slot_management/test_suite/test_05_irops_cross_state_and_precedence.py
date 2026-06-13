"""IROPS cancel/divert cascades, cross-axis/cross-entity state guards, and the
fixed validation-precedence ordering.

Queue A: transitive_cascade (irops-cancel depth-3, irops-divert depth-2),
cross_entity_state_dependency (occupy blocked when gate OOS; complete blocked
until handling DEPARTED), priority_pair_validation_conflict (cross-state beats
turn-time; existence beats wingspan).
Queue B: activate_completed_flight_terminal_lockdown.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures

OPS = TEST_USERS["ops_admin_headers"]
GATE_CTRL = TEST_USERS["gate_controller_headers"]
RAMP = TEST_USERS["ramp_agent_headers"]


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade: irops-cancel depth-3
# ---------------------------------------------------------------------------
def test_irops_cancel_cascade_tears_down_commitments(api):
    """PRD §3.9: "First, every GateAssignment of the flight whose status is
    PLANNED, OCCUPIED, or TOWED_AWAY is moved to CANCELLED; for each one that had
    been OCCUPIED or TOWED_AWAY, its source stand counter ... is decremented ...
    Next, every HELD CuteAllocation and every HELD GseAllocation of the flight is
    moved to CANCELLED ... Finally, every SlotPermit of the flight whose status is
    REQUESTED or CONFIRMED is moved to FORFEITED, freeing those slots."

    Design: Difficulty/transitive_cascade/irops_cancel_cascade_depth3
    """
    s = fixtures.setup_active_flight_full_commitments(with_gse=True)
    flight = validate_success(api.irops_cancel_flight(s["flight"]["id"], OPS), 200)
    assert flight["schedule_status"] == "CANCELLED"
    ga = validate_success(api.get_gate_assignment(s["assignment"]["id"], GATE_CTRL), 200)
    assert ga["status"] == "CANCELLED"
    gate = validate_success(api.get_gate(s["gate"]["id"], GATE_CTRL), 200)
    assert gate["active_assignment_count"] == 0
    permit = validate_success(api.get_slot_permit(s["permit"]["id"], OPS), 200)
    assert permit["status"] == "FORFEITED"
    gse = validate_success(api.get_gse_allocation(s["gse"]["id"], OPS), 200)
    assert gse["status"] == "CANCELLED"


def test_irops_cancel_sets_handling_unassigned(api):
    """PRD §3.9: "An IROPS cancel is permitted while the flight's schedule_status
    is SCHEDULED or ACTIVE and drives it to CANCELLED while setting handling_status
    back to UNASSIGNED."

    Design: Difficulty/transitive_cascade/irops_cancel_cascade_depth3
    """
    s = fixtures.setup_active_flight_full_commitments(with_gse=True)
    flight = validate_success(api.irops_cancel_flight(s["flight"]["id"], OPS), 200)
    assert flight["schedule_status"] == "CANCELLED"
    assert flight["handling_status"] == "UNASSIGNED"


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade: irops-divert depth-2 (slots kept)
# ---------------------------------------------------------------------------
def test_irops_divert_releases_assignment_keeps_slot(api):
    """PRD §3.9: "Its cascade moves every GateAssignment of the flight whose status
    is PLANNED or OCCUPIED to RELEASED, decrementing each released assignment's
    stand occupancy counter, and it does not touch the flight's CUTE allocations,
    GSE allocations, or slot permits — the slots are kept for possible
    re-coordination rather than forfeited."

    Design: Difficulty/transitive_cascade/irops_divert_cascade_depth2
    """
    s = fixtures.setup_active_flight_full_commitments(with_gse=False)
    flight = validate_success(api.irops_divert_flight(s["flight"]["id"], OPS), 200)
    assert flight["schedule_status"] == "DIVERTED"
    ga = validate_success(api.get_gate_assignment(s["assignment"]["id"], GATE_CTRL), 200)
    assert ga["status"] == "RELEASED"
    gate = validate_success(api.get_gate(s["gate"]["id"], GATE_CTRL), 200)
    assert gate["active_assignment_count"] == 0
    permit = validate_success(api.get_slot_permit(s["permit"]["id"], OPS), 200)
    assert permit["status"] == "CONFIRMED"


def test_irops_divert_sets_handling_unassigned(api):
    """PRD §3.9: "An IROPS divert is permitted only while the flight's
    schedule_status is ACTIVE and drives it to DIVERTED, again setting
    handling_status back to UNASSIGNED."

    Design: Difficulty/transitive_cascade/irops_divert_cascade_depth2
    """
    s = fixtures.setup_active_flight_full_commitments(with_gse=False)
    flight = validate_success(api.irops_divert_flight(s["flight"]["id"], OPS), 200)
    assert flight["schedule_status"] == "DIVERTED"
    assert flight["handling_status"] == "UNASSIGNED"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency: occupy blocked when gate OUT_OF_SERVICE
# ---------------------------------------------------------------------------
def test_occupy_blocked_when_gate_out_of_service(api):
    """PRD §3.1: "taking a gate out of service moves it to OUT_OF_SERVICE so that
    no new occupancies may be created or begun there."
    PRD §3.3: "The chosen stand must be ACTIVE — an assignment may not be created
    against a gate that is OUT_OF_SERVICE, and this stand-status guard is part of
    the ERR_CROSS_STATE_BLOCKED family."

    Design: Difficulty/cross_entity_state_dependency/occupy_blocked_when_gate_out_of_service
    """
    gate, flight, assignment = fixtures.setup_planned_gate_assignment(
        gate_kwargs={"code": "H1", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "BA22", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z")
    validate_success(api.out_of_service_gate(gate["id"], OPS), 200)
    resp = api.occupy_gate_assignment(assignment["id"], RAMP)
    validate_error(resp, ApiErrorId.ERR_CROSS_STATE_BLOCKED.value, 409)


def test_occupy_blocked_when_gate_oos_leaves_assignment_planned(api):
    """PRD §3.1: "taking a gate out of service moves it to OUT_OF_SERVICE so that
    no new occupancies may be created or begun there."
    PRD §3.5: "a RampAgent records the aircraft's arrival on stand by occupying the
    assignment, which moves the GateAssignment from PLANNED to OCCUPIED."

    Design: Difficulty/cross_entity_state_dependency/occupy_blocked_when_gate_out_of_service
    """
    gate, flight, assignment = fixtures.setup_planned_gate_assignment(
        gate_kwargs={"code": "H1b", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "BA24", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z")
    validate_success(api.out_of_service_gate(gate["id"], OPS), 200)
    resp = api.occupy_gate_assignment(assignment["id"], RAMP)
    validate_error(resp, ApiErrorId.ERR_CROSS_STATE_BLOCKED.value, 409)
    # the blocked occupy left the assignment in PLANNED (no transition occurred).
    after = validate_success(api.get_gate_assignment(assignment["id"], GATE_CTRL), 200)
    assert after["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency: complete blocked until handling DEPARTED
# ---------------------------------------------------------------------------
def test_complete_blocked_until_handling_departed(api):
    """PRD §3.2: "Completing a flight moves schedule_status from ACTIVE to
    COMPLETED, but it carries a cross-axis guard: it is permitted only when the
    flight is currently ACTIVE and its handling_status has already reached
    DEPARTED. A completion attempted before handling reaches DEPARTED is the
    canonical ERR_CROSS_STATE_BLOCKED case."

    Design: Difficulty/cross_entity_state_dependency/complete_blocked_until_handling_departed
    """
    gate, flight, assignment = fixtures.setup_occupied_gate_assignment(
        gate_kwargs={"code": "H2", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "BA23", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z", activate=True)
    flight_now = validate_success(api.get_flight(flight["id"], OPS), 200)
    assert flight_now["handling_status"] == "AT_GATE"
    resp = api.complete_flight(flight["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_CROSS_STATE_BLOCKED.value, 409)


def test_complete_succeeds_once_handling_departed(api):
    """PRD §3.2: "Completing a flight moves schedule_status from ACTIVE to
    COMPLETED, but it carries a cross-axis guard: it is permitted only when the
    flight is currently ACTIVE and its handling_status has already reached DEPARTED."

    Design: Difficulty/cross_entity_state_dependency/complete_blocked_until_handling_departed
    """
    gate, flight, assignment = fixtures.setup_occupied_gate_assignment(
        gate_kwargs={"code": "H3", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "BA25", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z", activate=True)
    # Drive handling to DEPARTED, then complete must pass.
    validate_success(api.depart_gate_assignment(assignment["id"], RAMP), 200)
    departed = validate_success(api.get_flight(flight["id"], OPS), 200)
    assert departed["handling_status"] == "DEPARTED"
    data = validate_success(api.complete_flight(flight["id"], OPS), 200)
    assert data["schedule_status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Queue A — priority_pair: cross-state (pri 6) beats turn-time (pri 13)
# ---------------------------------------------------------------------------
def test_cross_state_beats_turn_time_on_out_of_service_gate(api):
    """PRD §2.9: "The cross-axis and cross-entity guard is sixth, yielding
    ERR_CROSS_STATE_BLOCKED (priority 6). Only after all of these pass does the
    system evaluate the domain-specific business checks — wingspan fit (priority 7),
    gate window conflict (priority 8) ... minimum turn time (priority 13)."

    Design: Difficulty/priority_pair_validation_conflict/cross_state_beats_business_temporal_turn_time
    """
    gate = fixtures.register_gate(code="F1", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    validate_success(api.out_of_service_gate(gate["id"], OPS), 200)
    g_v2 = fixtures.current_gate_version(gate["id"])
    flight = fixtures.create_flight(
        flight_no="QF2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:30:00Z", min_turn_minutes=45)
    # window is 30 min (< min_turn 45) AND gate is OUT_OF_SERVICE; cross-state wins.
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T10:30:00Z",
         "expected_gate_version": g_v2}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_CROSS_STATE_BLOCKED.value, 409)


def test_cross_state_block_masks_turn_time_error_id(api):
    """PRD §2.9: "The effect of this ordering is that, for example, an
    authentication failure always masks a later business conflict."
    PRD §2.9: "The cross-axis and cross-entity guard is sixth, yielding
    ERR_CROSS_STATE_BLOCKED (priority 6). Only after all of these pass does the
    system evaluate the domain-specific business checks ... minimum turn time
    (priority 13)."

    Design: Difficulty/priority_pair_validation_conflict/cross_state_beats_business_temporal_turn_time
    """
    gate = fixtures.register_gate(code="F2", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    validate_success(api.out_of_service_gate(gate["id"], OPS), 200)
    g_v2 = fixtures.current_gate_version(gate["id"])
    flight = fixtures.create_flight(
        flight_no="QF3", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:30:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T10:30:00Z",
         "expected_gate_version": g_v2}, GATE_CTRL)
    # priority 6 wins: the turn-time error (priority 13) must NOT be the reported id.
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_CROSS_STATE_BLOCKED.value
    assert body["data"]["error_id"] != ApiErrorId.ERR_TURN_TIME_TOO_SHORT.value


# ---------------------------------------------------------------------------
# Queue A — priority_pair: existence (pri 3) beats wingspan (pri 7)
# ---------------------------------------------------------------------------
def test_existence_beats_wingspan_on_missing_gate(api):
    """PRD §2.9: "Existence is third: any missing path resource or referenced
    foreign key yields ERR_NOT_FOUND (priority 3) ... Only after all of these pass
    does the system evaluate the domain-specific business checks — wingspan fit
    (priority 7)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_constraint_wingspan
    """
    flight = fixtures.create_flight(
        flight_no="NZ8", aircraft_wingspan_m=95,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T10:00:00Z", min_turn_minutes=45)
    # gate_id does not exist AND wingspan would exceed; existence wins.
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE",
         "gate_id": "00000000-0000-4000-8000-000000000000",
         "start_utc": "2026-06-10T08:00:00Z", "end_utc": "2026-06-10T10:00:00Z"}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_existence_block_masks_wingspan_error_id(api):
    """PRD §2.9: "Existence is third: any missing path resource or referenced
    foreign key yields ERR_NOT_FOUND (priority 3)."
    PRD §2.9: "a non-existent flight is reported as ERR_NOT_FOUND rather than as
    any downstream conflict."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_constraint_wingspan
    """
    flight = fixtures.create_flight(
        flight_no="NZ9", aircraft_wingspan_m=95,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T10:00:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE",
         "gate_id": "00000000-0000-4000-8000-0000000000bb",
         "start_utc": "2026-06-10T08:00:00Z", "end_utc": "2026-06-10T10:00:00Z"}, GATE_CTRL)
    body = resp.json()
    # existence (priority 3) wins; wingspan (priority 7) must not be reported.
    assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
    assert body["data"]["error_id"] != ApiErrorId.ERR_WINGSPAN_EXCEEDED.value


# ---------------------------------------------------------------------------
# Queue B — terminal lockdown: activate a CANCELLED flight -> ERR_INVALID_STATE
# ---------------------------------------------------------------------------
def test_activate_cancelled_flight_terminal_lockdown(api):
    """PRD §3.2: "Activating a flight moves schedule_status from SCHEDULED to
    ACTIVE and touches nothing on the handling axis; it is permitted only while the
    flight is in SCHEDULED ... An attempt to activate or complete from any other
    state on the schedule axis is an ERR_INVALID_STATE rejection."

    Design: Corner/state_machines/activate_completed_flight_terminal_lockdown
    """
    flight = fixtures.create_flight(
        flight_no="SM3", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T10:00:00Z", min_turn_minutes=45)
    validate_success(api.irops_cancel_flight(flight["id"], OPS), 200)
    resp = api.activate_flight(flight["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
