"""CUTE/GSE allocation conflict rules, optimistic-concurrency on gate booking,
RBAC denials, FK reverse-reachability lists, pagination bounds, and a remaining
state-machine precondition corner.

Queue B: gse_cooldown_exact_gap_passes, cute_busy_overlap_on_unit,
cute_adjacent_back_to_back_allowed, gse_busy_cooldown_violation,
tow_remote_assignment_returns_invalid_state, occ_stale/correct,
rbac denials, missing-auth, list/filter reverse-reachability, pagination.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, build_user_headers,
)
from test_helpers import fixtures

OPS = TEST_USERS["ops_admin_headers"]
GATE_CTRL = TEST_USERS["gate_controller_headers"]
RAMP = TEST_USERS["ramp_agent_headers"]
SLOT = TEST_USERS["slot_coordinator_headers"]


# ---------------------------------------------------------------------------
# CUTE allocation conflict semantics
# ---------------------------------------------------------------------------
def test_cute_busy_overlap_on_unit(api):
    """PRD §3.8: "A new allocation from s to e conflicts with an existing HELD
    allocation on the same cute_unit_id from s2 to e2 when s is strictly earlier
    than e2 and s2 is strictly earlier than e ... Any genuine overlap is rejected
    with ERR_CUTE_BUSY (HTTP 409)."

    Design: Corner/validations/cute_busy_overlap_on_unit
    """
    unit = fixtures.register_cute_unit(label="CUTE-1", terminal="T1")
    flight = fixtures.create_flight(
        flight_no="CU1", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T11:00:00Z", min_turn_minutes=45)
    fixtures.create_cute_allocation(flight["id"], unit["id"],
                                    "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    resp = api.create_cute_allocation(
        {"flight_id": flight["id"], "cute_unit_id": unit["id"],
         "start_utc": "2026-06-10T10:30:00Z", "end_utc": "2026-06-10T11:00:00Z"}, RAMP)
    validate_error(resp, ApiErrorId.ERR_CUTE_BUSY.value, 409)


def test_cute_adjacent_back_to_back_allowed(api):
    """PRD §3.8: "touching endpoints do not conflict, so a back-to-back allocation
    beginning exactly when the prior one ends is allowed."

    Design: Corner/validations/cute_adjacent_back_to_back_allowed
    """
    unit = fixtures.register_cute_unit(label="CUTE-2", terminal="T1")
    flight = fixtures.create_flight(
        flight_no="CU2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T10:00:00Z",
        sched_departure_utc="2026-06-10T12:00:00Z", min_turn_minutes=45)
    fixtures.create_cute_allocation(flight["id"], unit["id"],
                                    "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    resp = api.create_cute_allocation(
        {"flight_id": flight["id"], "cute_unit_id": unit["id"],
         "start_utc": "2026-06-10T11:00:00Z", "end_utc": "2026-06-10T12:00:00Z"}, RAMP)
    data = validate_success(resp, 201)
    assert data["status"] == "HELD"


# ---------------------------------------------------------------------------
# GSE cooldown semantics
# ---------------------------------------------------------------------------
def test_gse_cooldown_exact_gap_passes(api):
    """PRD §3.8: "the rule requires that of any two windows the later one's start be
    at or after the earlier one's end plus turnaround_minutes; if that separation
    is not met, the allocation is rejected with ERR_EQUIPMENT_BUSY (HTTP 409)."

    Design: Corner/calculations/gse_cooldown_exact_gap_passes
    """
    eq = fixtures.register_ground_equipment(asset_tag="GPU-CD", equipment_type="GPU",
                                            turnaround_minutes=20)
    flight = fixtures.create_flight(
        flight_no="CD1", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T12:00:00Z", min_turn_minutes=45)
    fixtures.create_gse_allocation(flight["id"], eq["id"],
                                   "2026-06-10T10:00:00Z", "2026-06-10T10:40:00Z")
    # new start 11:00 == 10:40 end + 20 turnaround -> exactly meets, passes.
    resp = api.create_gse_allocation(
        {"flight_id": flight["id"], "equipment_id": eq["id"],
         "start_utc": "2026-06-10T11:00:00Z", "end_utc": "2026-06-10T11:30:00Z"}, RAMP)
    data = validate_success(resp, 201)
    assert data["status"] == "HELD"


def test_gse_busy_cooldown_violation(api):
    """PRD §3.8: "When turnaround_minutes is positive, even a back-to-back
    allocation with zero gap is refused."
    PRD §3.8: "the rule requires that of any two windows the later one's start be at
    or after the earlier one's end plus turnaround_minutes; if that separation is
    not met, the allocation is rejected with ERR_EQUIPMENT_BUSY (HTTP 409)."

    Design: Corner/validations/gse_busy_cooldown_violation
    """
    eq = fixtures.register_ground_equipment(asset_tag="GPU-CD2", equipment_type="GPU",
                                            turnaround_minutes=20)
    flight = fixtures.create_flight(
        flight_no="CD9", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T12:00:00Z", min_turn_minutes=45)
    fixtures.create_gse_allocation(flight["id"], eq["id"],
                                   "2026-06-10T10:00:00Z", "2026-06-10T10:40:00Z")
    # new start 10:59 < 10:40 + 20 = 11:00 -> separation not met.
    resp = api.create_gse_allocation(
        {"flight_id": flight["id"], "equipment_id": eq["id"],
         "start_utc": "2026-06-10T10:59:00Z", "end_utc": "2026-06-10T11:30:00Z"}, RAMP)
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_BUSY.value, 409)


# ---------------------------------------------------------------------------
# State-machine precondition: tow a REMOTE assignment -> invalid state
# ---------------------------------------------------------------------------
def test_tow_remote_assignment_returns_invalid_state(api):
    """PRD §3.5: "Towing is permitted only when the assignment is currently
    OCCUPIED, only when the assignment's stand_type is GATE (only gate assignments
    can be towed)."
    PRD §3.5: "attempting any of them from the wrong state is an ERR_INVALID_STATE
    rejection."

    Design: Corner/state_machines/tow_remote_assignment_returns_invalid_state
    """
    r1 = fixtures.register_remote_stand(code="SMR1", max_wingspan_m=80, capacity=2)
    r2 = fixtures.register_remote_stand(code="SMR2", max_wingspan_m=80, capacity=1)
    flight = fixtures.create_flight(
        flight_no="SM2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T10:00:00Z", min_turn_minutes=45)
    ga = fixtures.create_remote_assignment(flight["id"], r1["id"],
                                           "2026-06-10T08:00:00Z", "2026-06-10T10:00:00Z")
    validate_success(api.occupy_gate_assignment(ga["id"], RAMP), 200)
    resp = api.tow_gate_assignment(ga["id"], {"target_remote_stand_id": r2["id"]}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---------------------------------------------------------------------------
# Optimistic concurrency on gate booking
# ---------------------------------------------------------------------------
def test_occ_stale_gate_version_rejected(api):
    """PRD §2.7: "In that case the create is rejected with ERR_STALE_GATE_VERSION
    (HTTP 412): the value the client sent in expected_gate_version is below — does
    not equal — the gate's current version, so the write is refused to keep the
    controller from overwriting a booking it never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_gate_version_rejected
    """
    gate = fixtures.register_gate(code="OCC1", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    v0 = gate["version"]
    f1 = fixtures.create_flight(
        flight_no="OC1", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T09:00:00Z", min_turn_minutes=45)
    f2 = fixtures.create_flight(
        flight_no="OC2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T12:00:00Z",
        sched_departure_utc="2026-06-10T13:00:00Z", min_turn_minutes=45)
    # first create bumps gate.version off v0.
    fixtures.create_gate_assignment(f1["id"], gate["id"],
                                    "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z", v0)
    # second create still carries stale v0.
    resp = api.create_gate_assignment(
        {"flight_id": f2["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T12:00:00Z", "end_utc": "2026-06-10T13:00:00Z",
         "expected_gate_version": v0}, GATE_CTRL)
    validate_error(resp, ApiErrorId.ERR_STALE_GATE_VERSION.value, 412)


def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §3.3: "When stand_type is GATE, a successful create increments the
    target Gate's version by 1."
    PRD §2.4: "version — a system-managed integer that begins at 1 on creation and
    increments by 1 with every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    gate = fixtures.register_gate(code="OCC2", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    v0 = gate["version"]
    assert v0 == 1
    flight = fixtures.create_flight(
        flight_no="OC3", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T09:00:00Z", min_turn_minutes=45)
    validate_success(api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T08:00:00Z", "end_utc": "2026-06-10T09:00:00Z",
         "expected_gate_version": v0}, GATE_CTRL), 201)
    gate_after = validate_success(api.get_gate(gate["id"], GATE_CTRL), 200)
    assert gate_after["version"] == 2


# ---------------------------------------------------------------------------
# RBAC denials
# ---------------------------------------------------------------------------
def test_rampagent_cannot_create_gate_assignment(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)."
    PRD §2.1: "A GateController owns gate and remote-stand assignment, towing,
    tow-return, and assignment cancellation."

    Design: Corner/rbac/rampagent_cannot_create_gate_assignment
    """
    gate = fixtures.register_gate(code="RB1", terminal="T1", max_wingspan_m=80, buffer_minutes=10)
    flight = fixtures.create_flight(
        flight_no="RB9", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T10:00:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T08:00:00Z", "end_utc": "2026-06-10T10:00:00Z",
         "expected_gate_version": gate["version"]}, RAMP)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_slotcoordinator_cannot_register_gate(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)."
    PRD §2.1: "An OpsAdmin is the cross-cutting operator: it owns the resource
    registry (registering gates, remote stands, CUTE units, and ground equipment)."

    Design: Corner/rbac/slotcoordinator_cannot_register_gate
    """
    resp = api.create_gate(
        {"code": "RB2", "terminal": "T1", "max_wingspan_m": 80}, SLOT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_missing_auth_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role does not name one
    of these four known roles, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    stranger = build_user_headers("someone", "Stranger")
    resp = api.list_gates(stranger)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ---------------------------------------------------------------------------
# FK reverse-reachability lists
# ---------------------------------------------------------------------------
def test_list_assignments_for_flight_subresource(api):
    """PRD §2.5: "Several read endpoints expose a resource's dependents by walking
    a foreign key in reverse — for instance, listing every assignment on a given
    gate, every slot permit for a given flight."

    Design: Corner/endpoints/list_assignments_for_flight_subresource
    """
    gate, flight, assignment = fixtures.setup_planned_gate_assignment(
        gate_kwargs={"code": "EP1", "terminal": "T1", "max_wingspan_m": 80, "buffer_minutes": 10},
        flight_kwargs={"flight_no": "EP9", "aircraft_wingspan_m": 60,
                       "sched_arrival_utc": "2026-06-10T08:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z", "min_turn_minutes": 45},
        start_utc="2026-06-10T08:00:00Z", end_utc="2026-06-10T10:00:00Z")
    resp = api.list_flight_gate_assignments(flight["id"], GATE_CTRL)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert any(row["id"] == assignment["id"] for row in data)


def test_filtered_list_assignments_by_remote_stand(api):
    """PRD §4: "/gate-assignments accepts flight_id, gate_id, remote_stand_id, and
    status."
    PRD §2.5: "Several read endpoints expose a resource's dependents by walking a
    foreign key in reverse."

    Design: Corner/endpoints/filtered_list_assignments_by_remote_stand
    """
    remote = fixtures.register_remote_stand(code="EPR1", max_wingspan_m=80, capacity=1)
    flight = fixtures.create_flight(
        flight_no="EP8", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T10:00:00Z", min_turn_minutes=45)
    ga = fixtures.create_remote_assignment(flight["id"], remote["id"],
                                           "2026-06-10T08:00:00Z", "2026-06-10T10:00:00Z")
    resp = api.list_gate_assignments(GATE_CTRL, params={"remote_stand_id": remote["id"]})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert any(row["id"] == ga["id"] for row in data)
    assert all(row["remote_stand_id"] == remote["id"] for row in data)


# ---------------------------------------------------------------------------
# Pagination bounds
# ---------------------------------------------------------------------------
def test_pagination_limit_out_of_range_returns_validation(api):
    """PRD §2.3: "if not provided it defaults to 10, with a minimum of 1 and a
    maximum of 100 ... A limit or offset value that falls outside its permitted
    range is rejected with ERR_VALIDATION (HTTP 422)."

    Design: Corner/validations/pagination_limit_out_of_range_returns_validation
    """
    resp = api.list_flights(OPS, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)
