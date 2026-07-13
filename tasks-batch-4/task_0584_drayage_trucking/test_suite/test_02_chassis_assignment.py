"""Chassis assignment, supersede, release, optimistic concurrency, and the
state-vs-referential priority ordering on assign-chassis.

Covers Difficulty rules: compensating_invariant, priority_pair_validation_conflict.
Covers Corner sections: cross_cutting_complexity_layers, state_machines.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    mk_terminal, mk_chassis, mk_booking, mk_confirmed_booking, mk_chassis_assigned_booking,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# --- compensating_invariant: assign then release conserves the pool ---------

def test_release_returns_chassis_to_available_with_zero_per_diem(api):
    """PRD §3.3: "On release, the assigned chassis moves from `ASSIGNED` back to
    `AVAILABLE`, the booking's `chassis_id` is cleared, and the booking's `version`
    increments."
    PRD §3.7: "the provisional figure is zero whenever the chassis is not `OUT`".

    Design: Difficulty/compensating_invariant/chassis_assign_release_pool_count_conserved
    """
    terminal = mk_terminal(api, name="Pier Q", code="PIERQ")
    chassis = mk_chassis(api, chassis_number="CHXE")
    before = validate_success(api.get_chassis(chassis["id"], DISPATCHER))
    assert before["status"] == "AVAILABLE"
    assigned = mk_chassis_assigned_booking(api, terminal["id"], chassis["id"], container_number="MSCUL")
    get_success_data(api.release_chassis(assigned["id"], DISPATCHER))
    after = validate_success(api.get_chassis(chassis["id"], DISPATCHER))
    assert after["status"] == "AVAILABLE", "released chassis must return to AVAILABLE"
    assert after["per_diem_provisional_cents"] == 0


def test_release_reverts_booking_to_confirmed_and_clears_chassis(api):
    """PRD §3.3: "Releasing a chassis is the compensating action while the booking
    is `CHASSIS_ASSIGNED`, returning it to `CONFIRMED`."
    PRD §3.3: "On release, the assigned chassis moves from `ASSIGNED` back to
    `AVAILABLE`, the booking's `chassis_id` is cleared, and the booking's `version`
    increments."

    Design: Difficulty/compensating_invariant/chassis_assign_release_pool_count_conserved
    """
    terminal = mk_terminal(api, name="Pier Q", code="PIERQ")
    chassis = mk_chassis(api, chassis_number="CHXE")
    assigned = mk_chassis_assigned_booking(api, terminal["id"], chassis["id"], container_number="MSCUL")
    released = get_success_data(api.release_chassis(assigned["id"], DISPATCHER))
    fetched = validate_success(api.get_booking(assigned["id"], DISPATCHER))
    assert fetched["status"] == "CONFIRMED"
    assert fetched["chassis_id"] is None, "chassis_id must be cleared on release"
    assert released["status"] == "CONFIRMED"


# --- OCC stale booking version --------------------------------------------

def test_reassign_with_stale_expected_version_rejected(api):
    """PRD §2.7: "If they do not match — because some earlier write has advanced
    the booking's `version` since the client last read it, for example a prior
    assignment that already set or superseded the chassis — the request is rejected
    with `ERR_STALE_BOOKING_VERSION` (HTTP 412), preventing the client from
    overwriting an assignment it never observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_booking_version_on_reassign
    """
    terminal = mk_terminal(api, name="Berth 75", code="B75")
    chx1 = mk_chassis(api, chassis_number="CHXP")
    chx2 = mk_chassis(api, chassis_number="CHXQ")
    _, confirmed = mk_confirmed_booking(api, terminal["id"], container_number="MSCU26")
    stale_version = confirmed["version"]
    # First assign advances the booking version past `stale_version`.
    get_success_data(api.assign_chassis(
        confirmed["id"], {"chassis_id": chx1["id"], "expected_booking_version": stale_version}, DISPATCHER))
    resp = api.assign_chassis(
        confirmed["id"], {"chassis_id": chx2["id"], "expected_booking_version": stale_version}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STALE_BOOKING_VERSION, expected_status=412)
    fetched = validate_success(api.get_booking(confirmed["id"], DISPATCHER))
    assert fetched["chassis_id"] == chx1["id"], "stale reassign must not overwrite the assignment"


# --- priority: state (p6) beats referential chassis (p8) on assign ---------

def _setup_canceled_booking_targeting_busy_chassis(api):
    terminal = mk_terminal(api, name="Pier J", code="PIERJ")
    busy = mk_chassis(api, chassis_number="CHXBUSY")
    # booking1 holds the chassis (ASSIGNED, i.e. not AVAILABLE).
    mk_chassis_assigned_booking(api, terminal["id"], busy["id"], container_number="MSCUA")
    # booking2 confirmed then canceled.
    _, confirmed2 = mk_confirmed_booking(api, terminal["id"], container_number="MSCUB")
    stale_v = confirmed2["version"]
    get_success_data(api.cancel_booking(confirmed2["id"], DISPATCHER))
    return confirmed2["id"], busy["id"], stale_v


def test_assign_on_canceled_booking_returns_invalid_state(api):
    """PRD §2.6: "For a chassis assignment, the booking's own state is checked
    (priority 6) before the target chassis's availability (priority 8), and both
    are checked before the optimistic-concurrency comparison (priority 13) — a
    stale-version rejection is the last thing considered."
    PRD §2.6 (priority 6): "the target resource is in a legal state for the
    requested transition, else `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_referential_chassis_on_assign
    """
    bkg2_id, busy_id, stale_v = _setup_canceled_booking_targeting_busy_chassis(api)
    resp = api.assign_chassis(
        bkg2_id, {"chassis_id": busy_id, "expected_booking_version": stale_v}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_state_check_precedes_chassis_availability_no_side_effects(api):
    """PRD §2.6: "For a chassis assignment, the booking's own state is checked
    (priority 6) before the target chassis's availability (priority 8), and both
    are checked before the optimistic-concurrency comparison (priority 13) — a
    stale-version rejection is the last thing considered."

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_referential_chassis_on_assign
    """
    bkg2_id, busy_id, stale_v = _setup_canceled_booking_targeting_busy_chassis(api)
    api.assign_chassis(bkg2_id, {"chassis_id": busy_id, "expected_booking_version": stale_v}, DISPATCHER)
    booking = validate_success(api.get_booking(bkg2_id, DISPATCHER))
    assert booking["status"] == "CANCELED"
    chassis = validate_success(api.get_chassis(busy_id, DISPATCHER))
    assert chassis["status"] == "ASSIGNED", "the busy chassis must remain owned by booking1"


# --- Corner: release on a CONFIRMED (no-chassis) booking is invalid --------

def test_release_chassis_from_confirmed_booking_rejected(api):
    """PRD §3.3: "Releasing a chassis is the compensating action while the booking
    is `CHASSIS_ASSIGNED`, returning it to `CONFIRMED`."
    PRD §2.6 (priority 6): "the target resource is in a legal state for the
    requested transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/release_chassis_from_confirmed_rejected
    """
    terminal = mk_terminal(api, name="Berth 61", code="B61")
    _, confirmed = mk_confirmed_booking(api, terminal["id"], container_number="MSCU12")
    resp = api.release_chassis(confirmed["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_booking(confirmed["id"], DISPATCHER))
    assert after["status"] == "CONFIRMED"
