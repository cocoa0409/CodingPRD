"""Cancellation cascades and emergency-insertion preemption."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    api_client,
    create_emergency_insert_payload,
    make_staff_assignment,
    list_assignments_for_case,
    get_settlement_for_case,
    cancel_case,
    setup_cancel_cascade_general,
    setup_emergency_preempt_cardiac_cascade,
    setup_scheduled_general_case,
    create_surgical_case,
    approve_case,
)


SCHED = TEST_USERS["scheduler_headers"]


# ─── Difficulty Rule 4.2: cancel cascade depth 2 ──────────────────────────

def test_cancel_scheduled_case_cascades_assignments_released(api):
    """# difficulty: transitive_cascade/cancel_cascade_depth_two

    PRD §3.7: 'Cancellation of a `SCHEDULED` case unwinds the resource pinning.
    The case advances to `CANCELLED`. Every `CaseAssignment` on the case (in
    either `RESERVED` or `CONFIRMED`) cascades to `RELEASED`.'"""
    bundle = setup_cancel_cascade_general()
    cancel_case(bundle["case"]["id"])
    case_after = validate_success(api.get_surgical_case(bundle["case"]["id"], SCHED), 200)
    assert case_after["status"] == "CANCELLED"
    asgs = list_assignments_for_case(bundle["case"]["id"])
    assert len(asgs) > 0
    assert all(a["status"] == "RELEASED" for a in asgs)


def test_cancel_scheduled_case_settlement_refunded_with_estimated(api):
    """# difficulty: transitive_cascade/cancel_cascade_depth_two

    PRD §3.7: 'The owning `Settlement` cascades from `DRAFT` to `REFUNDED` with
    its `refund_amount` set to the value of `estimated_total_amount` at the
    moment of cancellation.'

    Recipe: room@500, anesth@200, scrub@80, planned 0..60, no implants:
      estimated = 500 + 200 + 80 + 150 + 0 = 930.00 → refund_amount = 930.00"""
    bundle = setup_cancel_cascade_general()
    cancel_case(bundle["case"]["id"])
    s = get_settlement_for_case(bundle["case"]["id"])
    assert s["status"] == "REFUNDED"
    assert s["refund_amount"] == 930.00


def test_cancel_scheduled_case_instrument_returns_to_soiled(api):
    """# difficulty: transitive_cascade/cancel_cascade_depth_two

    PRD §3.7: 'The underlying `InstrumentSet`'s `sterilization_status` flips
    from `CHECKED_OUT` to `SOILED` and its `current_case_id` is set back to
    `null`.'"""
    bundle = setup_cancel_cascade_general()
    cancel_case(bundle["case"]["id"])
    inst_after = validate_success(api.get_instrument_set(bundle["instrument"]["id"], SCHED), 200)
    assert inst_after["sterilization_status"] == "SOILED"
    assert inst_after["current_case_id"] is None


def test_cancel_approved_case_no_resources_pinned(api):
    """PRD §3.7: 'Cancellation of an `APPROVED` case has no resources pinned yet.
    The system advances the case to `CANCELLED` and cascades the owning
    `Settlement` from `DRAFT` to `REFUNDED`. Because no schedule has yet
    computed an `estimated_total_amount`, that field is still `null` at this
    point and the system treats it as `0.0` for the purpose of writing
    `refund_amount` on the settlement — the refund record carries `0.0`.'"""
    case = approve_case(create_surgical_case()["id"])
    cancel_case(case["id"])
    case_after = validate_success(api.get_surgical_case(case["id"], SCHED), 200)
    assert case_after["status"] == "CANCELLED"
    s = get_settlement_for_case(case["id"])
    assert s["status"] == "REFUNDED"
    assert s["refund_amount"] == 0.0


def test_cancel_terminal_state_rejected(api):
    """PRD §3.7: 'Cancellation of a case in any other state (`REQUESTED`,
    `REJECTED`, `COMPLETED`, `CANCELLED`, or `PREEMPTED`) is rejected with
    `ERR_CASE_NOT_CANCELLABLE`.'"""
    case = create_surgical_case()
    validate_error(api.cancel_case(case["id"], SCHED), "ERR_CASE_NOT_CANCELLABLE")


# ─── Difficulty Rule 4.1: emergency-insert cascade depth 3 ────────────────

def test_emergency_insert_preempts_scheduled_case_status(api):
    """# difficulty: transitive_cascade/emergency_preempt_cascade_depth_three

    PRD §3.8: 'For each preempted case, the system advances the case from
    `SCHEDULED` to `PREEMPTED`, sets `preempted_at_minute` to the current
    `current_minute`, sets `preempted_by_case_id` to the new emergency case's
    id'."""
    bundle = setup_emergency_preempt_cardiac_cascade()
    case_after = validate_success(api.get_surgical_case(bundle["preempted_case"]["id"], SCHED), 200)
    assert case_after["status"] == "PREEMPTED"
    assert case_after["preempted_by_case_id"] == bundle["emergency_case"]["id"]


def test_emergency_insert_cascades_assignments_to_preempted(api):
    """# difficulty: transitive_cascade/emergency_preempt_cascade_depth_three

    PRD §3.8: '... cascades every `CaseAssignment` (in `RESERVED` or `CONFIRMED`)
    to `PREEMPTED`'."""
    bundle = setup_emergency_preempt_cardiac_cascade()
    asgs = list_assignments_for_case(bundle["preempted_case"]["id"])
    assert len(asgs) > 0
    assert all(a["status"] == "PREEMPTED" for a in asgs)


def test_emergency_insert_cascades_settlement_refunded_2850(api):
    """# difficulty: transitive_cascade/emergency_preempt_cascade_depth_three

    PRD §3.8: '... cascades the owning `Settlement` to `REFUNDED` with
    `refund_amount` set to `estimated_total_amount`'.

    Recipe: CARDIAC_OR @1000, anesth@200, scrub@80, circ@70, planned 0..120:
      billable_hours=ceil(120/60)=2; room=2000, anesth=400, scrub=160, circ=140,
      instrument=150, implant=0 = 2850.00."""
    bundle = setup_emergency_preempt_cardiac_cascade()
    s = get_settlement_for_case(bundle["preempted_case"]["id"])
    assert s["status"] == "REFUNDED"
    assert s["refund_amount"] == 2850.00


def test_emergency_insert_instrument_returns_to_soiled(api):
    """# difficulty: transitive_cascade/emergency_preempt_cascade_depth_three

    PRD §3.8: 'flips the underlying `InstrumentSet`'s `sterilization_status`
    from `CHECKED_OUT` to `SOILED` and clears its `current_case_id`'."""
    bundle = setup_emergency_preempt_cardiac_cascade()
    inst_after = validate_success(
        api.get_instrument_set(bundle["instrument_preempted"]["id"], SCHED), 200
    )
    assert inst_after["sterilization_status"] == "SOILED"
    assert inst_after["current_case_id"] is None


def test_emergency_case_lands_in_scheduled_with_priority_emergency(api):
    """PRD §3.8: 'On success the new case is created with `priority` equal to
    `EMERGENCY`, ... `status` advanced from `APPROVED` to `SCHEDULED` in one
    transaction'."""
    bundle = setup_emergency_preempt_cardiac_cascade()
    new_case = bundle["emergency_case"]
    assert new_case["priority"] == "EMERGENCY"
    assert new_case["status"] == "SCHEDULED"


def test_emergency_insert_cannot_preempt_emergency_case(api):
    """PRD §3.8: 'Any conflicting case whose own `priority` is `EMERGENCY` halts
    the entire request: the system rejects the emergency-insert with
    `ERR_CANNOT_PREEMPT_EMERGENCY` and performs no partial preemption.'"""
    from test_helpers import (
        create_operating_room,
        create_anesthesiologist,
        create_scrub_nurse,
        create_circulating_nurse,
        create_instrument_set,
    )
    room = create_operating_room(specialty_required="CARDIAC", room_type="CARDIAC_OR", hourly_rate=1000.00)
    a1 = create_anesthesiologist(qualifications=["CARDIAC"])
    s1 = create_scrub_nurse(qualifications=["CARDIAC"])
    cn1 = create_circulating_nurse(qualifications=["CARDIAC"])
    a2 = create_anesthesiologist(qualifications=["CARDIAC"])
    s2 = create_scrub_nurse(qualifications=["CARDIAC"])
    cn2 = create_circulating_nurse(qualifications=["CARDIAC"])
    inst1 = create_instrument_set(specialty="CARDIAC", sterilize=True)
    inst2 = create_instrument_set(specialty="CARDIAC", sterilize=True)

    # First, use emergency-insert to create an EMERGENCY-priority scheduled case
    payload_first = create_emergency_insert_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[
            make_staff_assignment(a1["id"], "LEAD_ANESTHESIOLOGIST"),
            make_staff_assignment(s1["id"], "SCRUB_NURSE"),
            make_staff_assignment(cn1["id"], "CIRCULATING_NURSE"),
        ],
        instrument_set_id=inst1["id"],
        specialty_required="CARDIAC",
    )
    validate_success(api.emergency_insert(payload_first, SCHED), 201)

    # Second emergency-insert overlaps the first — must reject with
    # ERR_CANNOT_PREEMPT_EMERGENCY because the first case has priority=EMERGENCY
    payload_second = create_emergency_insert_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[
            make_staff_assignment(a2["id"], "LEAD_ANESTHESIOLOGIST"),
            make_staff_assignment(s2["id"], "SCRUB_NURSE"),
            make_staff_assignment(cn2["id"], "CIRCULATING_NURSE"),
        ],
        instrument_set_id=inst2["id"],
        specialty_required="CARDIAC",
    )
    validate_error(api.emergency_insert(payload_second, SCHED), "ERR_CANNOT_PREEMPT_EMERGENCY")
