"""Sterilization lifecycle, the 72-hour expiration boundary, and the sweep capability."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    create_instrument_set,
    advance_clock,
    setup_sterilization_at_boundary,
    api_client,
)


SCHED = TEST_USERS["scheduler_headers"]


# ─── Basic transitions ────────────────────────────────────────────────────

def test_start_sterilization_from_soiled(api):
    """PRD §3.5: 'A `Scheduler` initiates sterilization on a `SOILED` or `EXPIRED`
    set, advancing its `sterilization_status` to `IN_STERILIZATION`'."""
    inst = create_instrument_set(specialty="GENERAL", sterilize=False)
    res = api.start_sterilization(inst["id"], SCHED)
    started = validate_success(res, 200)
    assert started["sterilization_status"] == "IN_STERILIZATION"


def test_complete_sterilization_sets_last_sterilized(api):
    """PRD §3.5: 'Completion of sterilization advances the set from
    `IN_STERILIZATION` to `CLEAN_STERILIZED`, sets `last_sterilized_at_minute`
    equal to the value of `current_minute` at the moment of completion,
    increments `cycle_count` by one'."""
    inst = create_instrument_set(specialty="GENERAL", sterilize=False)
    api.start_sterilization(inst["id"], SCHED)
    res = api.complete_sterilization(inst["id"], SCHED)
    cleaned = validate_success(res, 200)
    assert cleaned["sterilization_status"] == "CLEAN_STERILIZED"
    assert cleaned["last_sterilized_at_minute"] is not None
    assert cleaned["cycle_count"] == 1


def test_start_sterilization_in_wrong_state_rejected(api):
    """PRD §3.5: 'A request to begin sterilization on a set in any other state is
    rejected with `ERR_INVALID_STATE`'."""
    inst = create_instrument_set(specialty="GENERAL", sterilize=True)  # CLEAN_STERILIZED
    validate_error(api.start_sterilization(inst["id"], SCHED), "ERR_INVALID_STATE")


# ─── Difficulty Rule 6.1: 72-hour expiration boundary ─────────────────────

def test_sterilization_at_4319_minutes_remains_clean(api):
    """# difficulty: boundary_precision_check/sterilization_expiration_72h_boundary_on_get_instrument

    PRD §3.5: 'a set whose elapsed time is 4319 minutes remains
    `CLEAN_STERILIZED`'."""
    bundle = setup_sterilization_at_boundary()
    advance_clock(4319)  # current_minute -> 4319, last_sterilized = 0
    res = api.get_instrument_set(bundle["instrument"]["id"], SCHED)
    inst = validate_success(res, 200)
    assert inst["sterilization_status"] == "CLEAN_STERILIZED"


def test_sterilization_at_4320_minutes_flips_to_expired(api):
    """# difficulty: boundary_precision_check/sterilization_expiration_72h_boundary_on_get_instrument

    PRD §3.5: 'a set whose elapsed time is exactly 4320 minutes is `EXPIRED`'.

    PRD §3.5: 'Expiry is enforced lazily on every read of the set — both the
    get-by-id and the list capability auto-flip any qualifying `CLEAN_STERILIZED`
    set to `EXPIRED` before responding'."""
    bundle = setup_sterilization_at_boundary()
    advance_clock(4320)
    res = api.get_instrument_set(bundle["instrument"]["id"], SCHED)
    inst = validate_success(res, 200)
    assert inst["sterilization_status"] == "EXPIRED"


def test_expired_set_can_re_enter_sterilization(api):
    """PRD §3.5: '`EXPIRED` → `IN_STERILIZATION` as the path back. ... A
    `Scheduler` initiates sterilization on a `SOILED` or `EXPIRED` set'."""
    bundle = setup_sterilization_at_boundary()
    advance_clock(4320)  # set goes EXPIRED on next read
    api.get_instrument_set(bundle["instrument"]["id"], SCHED)  # trigger lazy flip
    res = api.start_sterilization(bundle["instrument"]["id"], SCHED)
    started = validate_success(res, 200)
    assert started["sterilization_status"] == "IN_STERILIZATION"


def test_sweep_endpoint_flips_qualifying_clean_sets(api):
    """PRD §3.5: '... eagerly via the sterilization sweep capability described in
    §2.5, which iterates every `CLEAN_STERILIZED` set, flips qualifying ones to
    `EXPIRED`, appends one `AuditEntry` per affected set with `action`
    `'STERILIZATION_EXPIRED'`, and reports the `expired_count` on the response'."""
    bundle = setup_sterilization_at_boundary()
    advance_clock(4320)
    res = api.sweep_sterilization(SCHED)
    body = validate_success(res, 200)
    # body["expired_count"] is the reported count (≥1)
    assert "expired_count" in body
    assert body["expired_count"] >= 1


# ─── Scheduling-against-expired ─────────────────────────────────────────

def test_scheduling_against_expired_set_rejected(api):
    """PRD §3.5: 'When the set is `EXPIRED`, the call is rejected with
    `ERR_INSTRUMENT_EXPIRED`'."""
    from test_helpers import (
        create_operating_room,
        create_anesthesiologist,
        create_surgical_case,
        approve_case,
        create_schedule_payload,
        make_staff_assignment,
    )
    inst = create_instrument_set(specialty="GENERAL", sterilize=True)
    advance_clock(4320)  # set will flip to EXPIRED on next read
    api.get_instrument_set(inst["id"], SCHED)  # ensure flip is observed
    room = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    anesth = create_anesthesiologist()
    case = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    payload = create_schedule_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=4320,
        planned_end_minute=4380,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst["id"],
    )
    validate_error(api.schedule_case(case["id"], payload, SCHED), "ERR_INSTRUMENT_EXPIRED")
