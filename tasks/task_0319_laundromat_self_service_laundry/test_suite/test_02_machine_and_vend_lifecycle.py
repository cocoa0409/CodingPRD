"""Machine operational cycle and vend transaction lifecycle tests."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    create_vend_payload,
    setup_active_plan_and_washer,
    set_clock,
    create_plan,
    create_machine,
    create_member,
    capture_coin_vend,
    capture_app_wallet_vend,
    file_refund_claim,
    setup_app_wallet_vend,
    get_machine_version,
    get_machine,
    get_vend,
    reload_wallet,
)
from test_helpers import api_client as _ac  # noqa

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]


def test_machine_cyclic_idle_running_done_idle(api):
    """PRD §3.2: "A captured vend takes an `IDLE` machine to `RUNNING`."
    PRD §3.2: "the machine moves `RUNNING → DONE` ... and `lifetime_vend_count`
    increments by one."
    PRD §3.2: "Clearing a `DONE` machine returns it `DONE → IDLE`".

    Design: Difficulty/non_linear_state_machine/machine_cyclic_idle_running_done_idle
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", machine_overrides={"label": "W1", "cycle_minutes": 30})
    # First full loop: vend -> complete-cycle -> clear back to IDLE.
    capture_coin_vend(washer["id"])
    validate_success(api.complete_cycle(washer["id"], ATTENDANT), 200)
    validate_success(api.clear_machine(washer["id"], ATTENDANT), 200)
    version = get_machine_version(washer["id"])
    # Second vend on the same machine after the loop.
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    vend2 = validate_success(resp, 201)
    machine = get_machine(washer["id"])
    assert machine["status"] == "RUNNING", "machine re-runs after a full cycle"
    assert machine["lifetime_vend_count"] == 1, "one completed cycle counted"
    assert vend2["cycle_status"] == "RUNNING"


def test_clock_advance_completes_running_cycle(api):
    """PRD §2.5: "any machine that is `RUNNING` whose `cycle_ends_at` is at or
    before the new clock value is completed automatically — the machine moves to
    `DONE`, its occupying vend's `cycle_status` moves from `RUNNING` to
    `COMPLETED`, and the machine's `lifetime_vend_count` increments by one."

    Design: Corner/state_machines/clock_advance_completes_running_cycle_bubble_up
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", machine_overrides={"label": "W1", "cycle_minutes": 30})
    vend = capture_coin_vend(washer["id"])
    # Advance past cycle_ends_at (10:00 + 30min = 10:30).
    set_clock("2026-06-01T10:30:00Z")
    machine = get_machine(washer["id"])
    assert machine["status"] == "DONE"
    assert get_vend(vend["id"])["cycle_status"] == "COMPLETED"
    assert machine["lifetime_vend_count"] == 1


def test_vend_parallel_payment_and_cycle_dimensions(api):
    """PRD §3.2: "if the occupying vend was still `RUNNING` its `cycle_status`
    moves to `ABORTED`."
    PRD §3.7: "On approval ... the vend's `payment_status` moves
    `CAPTURED → REFUNDED`."

    Design: Difficulty/non_linear_state_machine/vend_parallel_payment_and_cycle_dimensions
    """
    plan, washer, member, vend = setup_app_wallet_vend(
        charged_clock="2026-06-01T10:00:00Z", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    claim = file_refund_claim(vend["id"], member["id"], reason="MACHINE_FAULT",
                              refund_destination="WALLET", as_member_id=member["id"])
    # Declare-fault aborts the running cycle; payment stays CAPTURED.
    validate_success(api.declare_fault(washer["id"], ATTENDANT), 200)
    aborted = get_vend(vend["id"])
    assert aborted["cycle_status"] == "ABORTED"
    assert aborted["payment_status"] == "CAPTURED", "fault leaves payment dimension untouched"
    # Approve the refund -> payment_status REFUNDED, cycle stays ABORTED.
    validate_success(
        api.approve_refund_claim(claim["id"], {"expected_claim_version": claim["version"]}, MANAGER),
        200)
    final = get_vend(vend["id"])
    assert final["cycle_status"] == "ABORTED"
    assert final["payment_status"] == "REFUNDED"


def test_vend_on_running_machine_rejected_unavailable(api):
    """PRD §3.3: "The capture is allowed only against an `IDLE` machine; if the
    machine is `RUNNING`, `DONE`, `FAULT`, or `OUT_OF_SERVICE` the vend is
    rejected with `ERR_MACHINE_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/vend_requires_machine_idle
    """
    plan, washer = setup_active_plan_and_washer(clock="2026-06-01T10:00:00Z")
    capture_coin_vend(washer["id"])  # machine now RUNNING
    version = get_machine_version(washer["id"])
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value)
    assert get_machine(washer["id"])["status"] == "RUNNING"


def test_second_vend_inside_running_interval_rejected(api):
    """PRD §3.3: "The capture is allowed only against an `IDLE` machine; if the
    machine is `RUNNING`, `DONE`, `FAULT`, or `OUT_OF_SERVICE` the vend is
    rejected with `ERR_MACHINE_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/machine_cycle_interval_single_occupancy_reject
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", machine_overrides={"label": "W1", "cycle_minutes": 30})
    capture_coin_vend(washer["id"])  # occupies [10:00, 10:30)
    set_clock("2026-06-01T10:15:00Z")  # still inside the interval
    version = get_machine_version(washer["id"])
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value)
    assert get_machine(washer["id"])["status"] == "RUNNING"


def test_clear_idle_machine_rejected_invalid_state(api):
    """PRD §3.2: "Clearing a `DONE` machine returns it `DONE → IDLE`".
    PRD §2.10: "State validity is sixth: the target resource must be in a state
    that admits the requested transition, or `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/clear_machine_from_idle_returns_invalid_state
    """
    create_machine(label="W1")
    machine = api.list_machines(MANAGER)
    machine_id = validate_success(machine, 200)[0]["id"]
    resp = api.clear_machine(machine_id, ATTENDANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_machine(machine_id)["status"] == "IDLE"


def test_machine_create_defaults(api):
    """PRD §3.2: "A new machine starts `IDLE` with `lifetime_vend_count` and
    `fault_count` both at zero."
    PRD §2.4: "The `version` field is an integer that begins at its initial value".

    Design: Corner/entities/create_machine_returns_201_with_defaults
    """
    from test_helpers import create_machine_payload
    resp = api.create_machine(create_machine_payload(label="W1"), MANAGER)
    machine = validate_success(resp, 201)
    assert machine["status"] == "IDLE"
    assert machine["lifetime_vend_count"] == 0
    assert machine["fault_count"] == 0
    assert machine["version"] == 1


def test_machine_system_fields_server_minted(api):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix, used for
    identity only."
    PRD §2.4: "The `version` field is an integer that begins at its initial value".

    Design: Corner/entities/machine_system_fields_generated_not_client_set
    """
    from test_helpers import create_machine_payload, is_valid_uuid, is_iso8601_timestamp
    resp = api.create_machine(create_machine_payload(label="W1"), MANAGER)
    machine = validate_success(resp, 201)
    assert is_valid_uuid(machine["id"]), "id is a server-minted UUID"
    assert machine["version"] == 1
    assert is_iso8601_timestamp(machine["created_at"])


def test_get_machine_not_found(api):
    """PRD §2.9: "any referenced machine, member, plan, vend, shift, order, claim,
    or item that does not exist halts the request at that point ... with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_machine_not_found_returns_404
    """
    from test_helpers import NON_EXISTENT_UUID
    resp = api.get_machine(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_machine_invalid_enum_type_rejected(api):
    """PRD §3.2: "a `machine_type` of either `WASHER` or `DRYER`".
    PRD §2.10: "Request well-formedness is fourth: required fields present, enum
    values in range ... or `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/machine_invalid_enum_type_returns_422
    """
    resp = api.create_machine(
        {"label": "X1", "machine_type": "TUMBLER", "capacity_lb": 25}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_machines_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object."

    Design: Corner/entities/list_machines_pagination_envelope
    """
    from test_helpers import validate_paginated, create_machine_payload
    api.create_machine(create_machine_payload(label="W1"), MANAGER)
    api.create_machine(create_machine_payload(label="D1", machine_type="DRYER", capacity_lb=30), MANAGER)
    resp = api.list_machines(MANAGER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
