"""Resource-registry creation, retrieval, listing, defaults, and request well-formedness.

Queue B (Corner/entities, Corner/validations subset) translations.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_gate,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures

OPS = TEST_USERS["ops_admin_headers"]


def test_create_gate_returns_201_with_system_defaults(api):
    """PRD §3.1: "A newly registered gate starts in ACTIVE status with its
    active_assignment_count at 0 and its version at 1."

    Design: Corner/entities/create_gate_returns_201_with_system_defaults
    """
    resp = api.create_gate(
        {"code": "Z1", "terminal": "T9", "max_wingspan_m": 70}, OPS)
    data = validate_success(resp, 201)
    assert_gate(data)
    assert data["status"] == "ACTIVE"
    assert data["active_assignment_count"] == 0
    assert data["version"] == 1


def test_get_gate_returns_stored_entity(api):
    """PRD §2.4: "id — a unique, server-minted identifier formatted as a UUID,
    with no type prefix."
    PRD §3.1: "A gate is registered with a code such as "A12" (unique across all
    gates), a terminal label such as "T1"."

    Design: Corner/entities/get_gate_returns_stored_entity
    """
    created = validate_success(
        api.create_gate({"code": "Z2", "terminal": "T9", "max_wingspan_m": 70}, OPS), 201)
    resp = api.get_gate(created["id"], OPS)
    data = validate_success(resp, 200)
    assert data["code"] == "Z2"
    assert data["id"] == created["id"]


def test_list_gates_paginated_envelope(api):
    """PRD §2.3: "Every paginated list response includes the following fields in
    the meta object of the envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_gates_paginated_envelope
    """
    validate_success(api.create_gate({"code": "Z3", "terminal": "T9", "max_wingspan_m": 70}, OPS), 201)
    validate_success(api.create_gate({"code": "Z4", "terminal": "T9", "max_wingspan_m": 70}, OPS), 201)
    resp = api.list_gates(OPS)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] >= 2
    assert "has_more" in meta


def test_get_gate_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing
    resource produces the ERR_NOT_FOUND rejection."

    Design: Corner/entities/get_gate_not_found
    """
    resp = api.get_gate("00000000-0000-4000-8000-0000000000aa", OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_flight_missing_required_returns_invalid_request(api):
    """PRD §2.9: "Request well-formedness is fourth: a malformed body — a missing
    required field, an illegal enum value, an end_utc that is not strictly greater
    than start_utc, a numeric field outside its declared bounds, or a stand_type
    discriminator that does not match exactly one of gate_id or remote_stand_id —
    yields ERR_INVALID_REQUEST (priority 4)."

    Design: Corner/entities/create_flight_missing_required_returns_invalid_request
    """
    resp = api.create_flight({"flight_no": "XX1", "aircraft_wingspan_m": 60}, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_gate_buffer_default_applied(api):
    """PRD §3.1: "an optional buffer_minutes clean/buffer time enforced between
    consecutive occupancies on that gate (a non-negative integer defaulting to 10)."

    Design: Corner/entities/create_gate_buffer_default_applied
    """
    data = validate_success(
        api.create_gate({"code": "Z5", "terminal": "T9", "max_wingspan_m": 70}, OPS), 201)
    assert data["buffer_minutes"] == 10


def test_flight_scheduled_turn_minutes_computed(api):
    """PRD §2.6: "On a Flight, scheduled_turn_minutes is computed once at creation
    as the difference between sched_departure_utc and sched_arrival_utc expressed
    in whole minutes, and is left null when sched_arrival_utc is null."

    Design: Corner/entities/flight_scheduled_turn_minutes_computed
    """
    data = validate_success(api.create_flight(
        {"flight_no": "CT9", "aircraft_wingspan_m": 60,
         "sched_arrival_utc": "2026-06-10T09:00:00Z",
         "sched_departure_utc": "2026-06-10T10:30:00Z",
         "min_turn_minutes": 45}, OPS), 201)
    assert data["scheduled_turn_minutes"] == 90


def test_gate_assignment_system_id_and_status_minted(api):
    """PRD §3.3: "A new assignment is created in PLANNED status with its
    occupancy_minutes computed from the window."
    PRD §2.6: "On a GateAssignment, occupancy_minutes is the planned window length
    — the difference between end_utc and start_utc in whole minutes."

    Design: Corner/entities/gate_assignment_system_id_and_version_ignored_on_input
    """
    gate = fixtures.register_gate(code="Z6", terminal="T9", max_wingspan_m=80)
    flight = fixtures.create_flight(
        flight_no="CT1", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T09:00:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T08:00:00Z", "end_utc": "2026-06-10T09:00:00Z",
         "expected_gate_version": gate["version"]},
        TEST_USERS["gate_controller_headers"])
    data = validate_success(resp, 201)
    assert data["status"] == "PLANNED"
    assert data["occupancy_minutes"] == 60


def test_create_gse_invalid_enum_equipment_type(api):
    """PRD §3.1: "an equipment_type which is one of GPU, PUSHBACK_TUG, BELT_LOADER,
    or AIR_START."
    PRD §2.9: "a malformed body — a missing required field, an illegal enum value
    ... yields ERR_INVALID_REQUEST (priority 4)."

    Design: Corner/entities/create_gse_invalid_enum_equipment_type
    """
    resp = api.create_ground_equipment(
        {"asset_tag": "X1", "equipment_type": "FORKLIFT"}, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_assignment_end_before_start_rejected(api):
    """PRD §2.9: "an end_utc that is not strictly greater than start_utc ...
    yields ERR_INVALID_REQUEST (priority 4)."

    Design: Corner/entities/create_assignment_end_before_start_rejected
    """
    gate = fixtures.register_gate(code="Z7", terminal="T9", max_wingspan_m=80)
    flight = fixtures.create_flight(
        flight_no="CT2", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T09:00:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE", "gate_id": gate["id"],
         "start_utc": "2026-06-10T09:00:00Z", "end_utc": "2026-06-10T08:00:00Z",
         "expected_gate_version": gate["version"]},
        TEST_USERS["gate_controller_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_assignment_stand_type_discriminator_mismatch(api):
    """PRD §2.9: "a stand_type discriminator that does not match exactly one of
    gate_id or remote_stand_id — yields ERR_INVALID_REQUEST (priority 4)."
    PRD §3.3: "A discriminator that does not line up with exactly one of the two
    stand references is malformed and rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_assignment_stand_type_discriminator_mismatch
    """
    remote = fixtures.register_remote_stand(code="Z8R", max_wingspan_m=80, capacity=1)
    flight = fixtures.create_flight(
        flight_no="CT3", aircraft_wingspan_m=60,
        sched_arrival_utc="2026-06-10T08:00:00Z",
        sched_departure_utc="2026-06-10T09:00:00Z", min_turn_minutes=45)
    resp = api.create_gate_assignment(
        {"flight_id": flight["id"], "stand_type": "GATE",
         "remote_stand_id": remote["id"],
         "start_utc": "2026-06-10T08:00:00Z", "end_utc": "2026-06-10T09:00:00Z"},
        TEST_USERS["gate_controller_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
