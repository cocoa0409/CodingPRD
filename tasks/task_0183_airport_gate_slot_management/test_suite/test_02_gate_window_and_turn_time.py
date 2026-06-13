"""Gate-window conflict (two-sided buffer), minimum-turn-time floor, and
remote-stand closed-interval capacity overlap.

Queue A: dual_variant_calc (GATE turn variant), combinatorial_formula
(buffer two-sided), boundary_precision_check (turn-time 44 fails),
resource_temporal_overlap (gate buffer + remote closed-interval).
Queue B: remote_stand_capacity_two_allows_second_overlap, wingspan_exceeded.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures

GATE_CTRL = TEST_USERS["gate_controller_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc: GATE turn variant pins occupancy_minutes == 45 at boundary
# ---------------------------------------------------------------------------
def test_turn_time_gate_variant_exact_boundary_passes(api):
    """PRD §3.3: "Minimum turn time requires that the assignment's
    occupancy_minutes be at least the flight's min_turn_minutes — equality passes,
    a strictly shorter window fails."
    PRD §2.6: "On a GateAssignment, occupancy_minutes is the planned window length
    — the difference between end_utc and start_utc in whole minutes."

    Design: Difficulty/dual_variant_calc/turn_time_gate_vs_remote_variant_on_gateassignment
    """
    gate = fixtures.register_gate(code="A12", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    flight = fixtures.create_flight(
        flight_no="AA482", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:45:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T10:45:00Z",
         "expected_gate_version": gate["version"]}, GATE_CTRL)
    data = validate_success(resp, 201)
    assert data["occupancy_minutes"] == 45
    assert data["status"] == "PLANNED"
    flight_after = validate_success(api.get_flight(flight["id"], GATE_CTRL), 200)
    assert flight_after["handling_status"] == "ASSIGNED"


def test_turn_time_gate_variant_window_assigns_flight(api):
    """PRD §3.3: "When this is the first assignment for the flight, the flight's
    handling_status advances from UNASSIGNED to ASSIGNED."

    Design: Difficulty/dual_variant_calc/turn_time_gate_vs_remote_variant_on_gateassignment
    """
    gate = fixtures.register_gate(code="A13", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    flight = fixtures.create_flight(
        flight_no="AA483", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:45:00Z", min_turn_minutes=45)
    data = validate_success(api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T10:45:00Z",
         "expected_gate_version": gate["version"]}, GATE_CTRL), 201)
    assert data["occupancy_minutes"] == 45
    flight_after = validate_success(api.get_flight(flight["id"], GATE_CTRL), 200)
    assert flight_after["handling_status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check: turn-time 44 (one under 45) FAILS
# ---------------------------------------------------------------------------
def test_turn_time_one_minute_under_floor_rejected(api):
    """PRD §3.3: "Minimum turn time requires that the assignment's
    occupancy_minutes be at least the flight's min_turn_minutes — equality passes,
    a strictly shorter window fails — and a too-short window is rejected with
    ERR_TURN_TIME_TOO_SHORT (HTTP 422)."

    Design: Difficulty/boundary_precision_check/turn_time_exact_min_passes_one_under_fails
    """
    gate = fixtures.register_gate(code="G1", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    flight = fixtures.create_flight(
        flight_no="EK4", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:44:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T10:44:00Z",
         "expected_gate_version": gate["version"]}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_TURN_TIME_TOO_SHORT.value, 422)


def test_turn_time_exact_min_passes(api):
    """PRD §3.3: "Minimum turn time requires that the assignment's
    occupancy_minutes be at least the flight's min_turn_minutes — equality passes,
    a strictly shorter window fails."

    Design: Difficulty/boundary_precision_check/turn_time_exact_min_passes_one_under_fails
    """
    gate = fixtures.register_gate(code="G1b", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    flight = fixtures.create_flight(
        flight_no="EK5", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:45:00Z", min_turn_minutes=45)
    data = validate_success(api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T10:45:00Z",
         "expected_gate_version": gate["version"]}, GATE_CTRL), 201)
    assert data["occupancy_minutes"] == 45
    assert data["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula (mode a): 9-min gap < buffer 10 -> conflict
# ---------------------------------------------------------------------------
def test_gate_window_gap_under_buffer_conflicts(api):
    """PRD §3.4: "a new window beginning at s and ending at e conflicts with an
    existing window from s2 to e2 when s is earlier than e2 plus the buffer and s2
    is earlier than e plus the buffer."
    PRD §3.4: "with a positive buffer, any gap strictly smaller than the buffer is
    a conflict. Any such collision is rejected with ERR_GATE_WINDOW_CONFLICT (HTTP 409)."

    Design: Difficulty/combinatorial_formula/gate_window_buffer_two_sided_mode_a
    """
    gate = fixtures.register_gate(code="B5", terminal="T2", max_wingspan_m=80, buffer_minutes=10)
    f1 = fixtures.create_flight(
        flight_no="UA1", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:45:00Z", min_turn_minutes=45)
    fixtures.create_gate_assignment(f1["id"], gate["id"],
                                    "2026-06-10T10:00:00Z", "2026-06-10T10:45:00Z",
                                    gate["version"])
    g_v2 = fixtures.current_gate_version(gate["id"])
    f2 = fixtures.create_flight(
        flight_no="UA2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:54:00Z",
        sched_departure_utc="2026-06-10T11:40:00Z", min_turn_minutes=45)
    # 10:45 end + buffer 10 = 10:55; new start 10:54 < 10:55 -> conflict (9-min gap).
    resp = api.create_gate_assignment(
        {"flight_id": f2["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:54:00Z", "end_utc": "2026-06-10T11:40:00Z",
         "expected_gate_version": g_v2}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_GATE_WINDOW_CONFLICT.value, 409)


def test_gate_window_exact_buffer_gap_does_not_conflict(api):
    """PRD §3.4: "a new window beginning at s and ending at e conflicts with an
    existing window from s2 to e2 when s is earlier than e2 plus the buffer and s2
    is earlier than e plus the buffer."
    PRD §3.4: "With a zero buffer this reduces to plain half-open overlap, so a new
    window that begins exactly when an existing one ends does not conflict; with a
    positive buffer, any gap strictly smaller than the buffer is a conflict."

    Design: Difficulty/combinatorial_formula/gate_window_buffer_two_sided_mode_a
    """
    gate = fixtures.register_gate(code="B6", terminal="T2", max_wingspan_m=80, buffer_minutes=10)
    f1 = fixtures.create_flight(
        flight_no="UA3", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:45:00Z", min_turn_minutes=45)
    fixtures.create_gate_assignment(f1["id"], gate["id"],
                                    "2026-06-10T10:00:00Z", "2026-06-10T10:45:00Z",
                                    gate["version"])
    g_v2 = fixtures.current_gate_version(gate["id"])
    f2 = fixtures.create_flight(
        flight_no="UA4", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:55:00Z",
        sched_departure_utc="2026-06-10T11:40:00Z", min_turn_minutes=45)
    # 10:45 end + buffer 10 = 10:55; new start 10:55 is NOT < 10:55 -> no conflict.
    data = validate_success(api.create_gate_assignment(
        {"flight_id": f2["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:55:00Z", "end_utc": "2026-06-10T11:40:00Z",
         "expected_gate_version": g_v2}, GATE_CTRL), 201)
    assert data["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap: gate two-sided buffer (5-min gap < 10)
# ---------------------------------------------------------------------------
def test_gate_two_sided_buffer_overlap_rejected(api):
    """PRD §3.4: "the gate's buffer_minutes clean time must separate consecutive
    occupancies, so the buffer is added to both ends."
    PRD §3.4: "with a positive buffer, any gap strictly smaller than the buffer is
    a conflict. Any such collision is rejected with ERR_GATE_WINDOW_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/gate_two_sided_buffer_overlap_on_gate
    """
    gate = fixtures.register_gate(code="I1", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    f1 = fixtures.create_flight(
        flight_no="WN1", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:45:00Z", min_turn_minutes=45)
    fixtures.create_gate_assignment(f1["id"], gate["id"],
                                    "2026-06-10T10:00:00Z", "2026-06-10T10:45:00Z",
                                    gate["version"])
    g_v2 = fixtures.current_gate_version(gate["id"])
    f2 = fixtures.create_flight(
        flight_no="WN2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:50:00Z",
        sched_departure_utc="2026-06-10T11:30:00Z", min_turn_minutes=40)
    # 5-minute gap (10:45 -> 10:50) < buffer 10 -> conflict.
    resp = api.create_gate_assignment(
        {"flight_id": f2["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T10:50:00Z", "end_utc": "2026-06-10T11:30:00Z",
         "expected_gate_version": g_v2}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_GATE_WINDOW_CONFLICT.value, 409)


def test_gate_buffer_sufficient_gap_passes(api):
    """PRD §3.4: "the gate's buffer_minutes clean time must separate consecutive
    occupancies, so the buffer is added to both ends."
    PRD §3.4: "With a zero buffer this reduces to plain half-open overlap, so a new
    window that begins exactly when an existing one ends does not conflict; with a
    positive buffer, any gap strictly smaller than the buffer is a conflict."

    Design: Difficulty/resource_temporal_overlap/gate_two_sided_buffer_overlap_on_gate
    """
    gate = fixtures.register_gate(code="I2", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    f1 = fixtures.create_flight(
        flight_no="WN3", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T10:45:00Z", min_turn_minutes=45)
    fixtures.create_gate_assignment(f1["id"], gate["id"],
                                    "2026-06-10T10:00:00Z", "2026-06-10T10:45:00Z",
                                    gate["version"])
    g_v2 = fixtures.current_gate_version(gate["id"])
    f2 = fixtures.create_flight(
        flight_no="WN4", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T11:00:00Z",
        sched_departure_utc="2026-06-10T11:45:00Z", min_turn_minutes=45)
    # 15-minute gap (10:45 -> 11:00) >= buffer 10 -> no conflict.
    data = validate_success(api.create_gate_assignment(
        {"flight_id": f2["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T11:00:00Z", "end_utc": "2026-06-10T11:45:00Z",
         "expected_gate_version": g_v2}, GATE_CTRL), 201)
    assert data["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap: remote stand CLOSED interval, cap 1
# ---------------------------------------------------------------------------
def test_remote_stand_closed_adjacency_overflows_capacity(api):
    """PRD §3.4: "Remote intervals are closed [start_utc, end_utc], so two windows
    that touch at an endpoint do overlap: an existing window from s2 to e2 and a
    new window from s to e overlap when s is at or before e2 and s2 is at or before e."
    PRD §3.4: "If that maximum, with the new window included, exceeds capacity, the
    request is rejected with ERR_REMOTE_STAND_FULL (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/remote_stand_closed_interval_capacity_overflow
    """
    remote = fixtures.register_remote_stand(code="R9", max_wingspan_m=80, capacity=1)
    f1 = fixtures.create_flight(
        flight_no="AS1", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T11:00:00Z", min_turn_minutes=45)
    fixtures.create_remote_assignment(f1["id"], remote["id"],
                                      "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    f2 = fixtures.create_flight(
        flight_no="AS2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T11:00:00Z",
        sched_departure_utc="2026-06-10T12:00:00Z", min_turn_minutes=45)
    # Closed adjacency at 11:00 collides; cap 1 -> overflow.
    resp = api.create_gate_assignment(
        {"flight_id": f2["id"], "stand_type": "REMOTE", "remote_stand_id": remote["id"],
         "start_utc": "2026-06-10T11:00:00Z", "end_utc": "2026-06-10T12:00:00Z"}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_REMOTE_STAND_FULL.value, 409)


def test_remote_stand_disjoint_window_after_overflow_blocked_window_not_booked(api):
    """PRD §3.4: "Remote intervals are closed [start_utc, end_utc], so two windows
    that touch at an endpoint do overlap."
    PRD §3.4: "If that maximum, with the new window included, exceeds capacity, the
    request is rejected with ERR_REMOTE_STAND_FULL (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/remote_stand_closed_interval_capacity_overflow
    """
    remote = fixtures.register_remote_stand(code="R9b", max_wingspan_m=80, capacity=1)
    f1 = fixtures.create_flight(
        flight_no="AS3", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T11:00:00Z", min_turn_minutes=45)
    fixtures.create_remote_assignment(f1["id"], remote["id"],
                                      "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    f2 = fixtures.create_flight(
        flight_no="AS4", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T11:00:00Z",
        sched_departure_utc="2026-06-10T12:00:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": f2["id"], "stand_type": "REMOTE", "remote_stand_id": remote["id"],
         "start_utc": "2026-06-10T11:00:00Z", "end_utc": "2026-06-10T12:00:00Z"}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_REMOTE_STAND_FULL.value, 409)
    # Only the first window remains live on the stand; the rejected one was not booked.
    listed, _ = validate_paginated(
        api.list_remote_stand_gate_assignments(remote["id"], GATE_CTRL))
    assert all(row["flight_id"] != f2["id"] for row in listed)


# ---------------------------------------------------------------------------
# Queue B — remote stand capacity 2 allows the second overlapping window
# ---------------------------------------------------------------------------
def test_remote_stand_capacity_two_allows_second_overlap(api):
    """PRD §3.4: "The stand admits up to capacity aircraft at once ... Where
    capacity is greater than 1, several windows may legitimately overlap; only the
    window that would push the simultaneous count past capacity is refused."

    Design: Corner/calculations/remote_stand_capacity_two_allows_second_overlap
    """
    remote = fixtures.register_remote_stand(code="CAP2", max_wingspan_m=80, capacity=2)
    f1 = fixtures.create_flight(
        flight_no="CP1", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T11:00:00Z", min_turn_minutes=45)
    f2 = fixtures.create_flight(
        flight_no="CP2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T11:00:00Z", min_turn_minutes=45)
    fixtures.create_remote_assignment(f1["id"], remote["id"],
                                      "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    resp = api.create_gate_assignment(
        {"flight_id": f2["id"], "stand_type": "REMOTE", "remote_stand_id": remote["id"],
         "start_utc": "2026-06-10T10:00:00Z", "end_utc": "2026-06-10T11:00:00Z"}, GATE_CTRL)
    data = validate_success(resp, 201)
    assert data["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Queue B — wingspan exceeded on create
# ---------------------------------------------------------------------------
def test_wingspan_exceeded_on_create(api):
    """PRD §3.3: "Wingspan fit requires that the chosen stand's max_wingspan_m be
    at least the flight's aircraft_wingspan_m; a stand too narrow for the aircraft
    is rejected with ERR_WINGSPAN_EXCEEDED (HTTP 422)."

    Design: Corner/validations/wingspan_exceeded_on_create
    """
    gate = fixtures.register_gate(code="WS1", terminal="T1", max_wingspan_m=60, buffer_minutes=10)
    flight = fixtures.create_flight(
        flight_no="WS9", aircraft_wingspan_m=75,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T09:00:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T08:00:00Z", "end_utc": "2026-06-10T09:00:00Z",
         "expected_gate_version": gate["version"]}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_WINGSPAN_EXCEEDED.value, 422)
