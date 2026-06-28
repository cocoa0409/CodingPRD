"""Enrollment lifecycle: waitlist promotion cycle, advancement demote/promote
cascade, seat conservation, capacity-waitlist behavior, child withdrawal, and
the session-cancel EXCUSED+credit depth-3 cascade.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, TEST_USERS, set_clock,
    setup_waitlisted_pair, setup_enrolled_child,
    create_program, create_room, create_instructor, create_session,
    create_active_membership, create_child, enroll_child,
)
from test_helpers import fixtures as fx

STAFF = TEST_USERS["front_desk_headers"]


def test_cancel_enrolled_row_promotes_waitlisted_row(api):
    """PRD §3.4: "The row transitions to the terminal CANCELLED state, the
    session's enrolled_count is decremented by one to free the seat, the next
    waitlisted row (lowest waitlist_seq) is promoted as above, and the session's
    version is incremented."
    PRD §3.4: "the system promotes the row with the lowest waitlist_seq first
    (ties broken by created_at ascending), clears that row's waitlist_seq to null,
    and increments the session's enrolled_count by one."

    Capacity-1 session: ENROLLED child A, WAITLISTED child B. Cancelling A promotes
    B to ENROLLED with waitlist_seq null; enrolled_count stays 1.

    Design: Difficulty/non_linear_state_machine/enrollment_enrolled_waitlisted_promote_cycle
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_waitlisted_pair(level_index=0, tuition_cents=2500, tier="PLUS")
    # Confirm B started WAITLISTED.
    enr_b = get_success_data(api.get_enrollment(ctx["enrollment_b"]["id"], STAFF))
    assert enr_b["status"] == "WAITLISTED"
    validate_success(api.cancel_enrollment(ctx["enrollment_a"]["id"], STAFF), 200)
    enr_a_after = get_success_data(api.get_enrollment(ctx["enrollment_a"]["id"], STAFF))
    enr_b_after = get_success_data(api.get_enrollment(ctx["enrollment_b"]["id"], STAFF))
    assert enr_a_after["status"] == "CANCELLED"
    assert enr_b_after["status"] == "ENROLLED"
    assert enr_b_after["waitlist_seq"] is None
    session = get_success_data(api.get_session(ctx["session"]["id"], STAFF))
    assert session["enrolled_count"] == 1


def test_waitlisted_row_carries_waitlist_seq_before_promotion(api):
    """PRD §3.4: "When a row is created WAITLISTED, it is assigned a waitlist_seq
    equal to one more than the maximum existing waitlist_seq on that session (and
    holds no seat, so enrolled_count is untouched)."
    PRD §3.4: "A waitlist_seq is null while a row is ENROLLED."

    Companion on the promote-cycle scenario: before any cancellation, the ENROLLED
    row A has waitlist_seq null and the WAITLISTED row B has a non-null waitlist_seq.

    Design: Difficulty/non_linear_state_machine/enrollment_enrolled_waitlisted_promote_cycle
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_waitlisted_pair(level_index=0, tuition_cents=2500, tier="PLUS")
    enr_a = get_success_data(api.get_enrollment(ctx["enrollment_a"]["id"], STAFF))
    enr_b = get_success_data(api.get_enrollment(ctx["enrollment_b"]["id"], STAFF))
    assert enr_a["status"] == "ENROLLED"
    assert enr_a["waitlist_seq"] is None
    assert enr_b["status"] == "WAITLISTED"
    assert enr_b["waitlist_seq"] is not None


def test_recurring_enroll_at_capacity_is_waitlisted_not_rejected(api):
    """PRD §3.4: "A RECURRING request that arrives when the session is at capacity
    is not rejected — it is placed WAITLISTED instead."
    PRD §3.4: "When a row is created WAITLISTED, it is assigned a waitlist_seq equal
    to one more than the maximum existing waitlist_seq on that session (and holds no
    seat, so enrolled_count is untouched)."

    A second RECURRING enroll into a full capacity-1 session is accepted as
    WAITLISTED (201); enrolled_count stays 1.

    Design: Corner/validations/recurring_enroll_at_capacity_is_waitlisted_not_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_waitlisted_pair(level_index=0, tuition_cents=2500, tier="PLUS")
    enr_b = get_success_data(api.get_enrollment(ctx["enrollment_b"]["id"], STAFF))
    assert enr_b["status"] == "WAITLISTED"
    session = get_success_data(api.get_session(ctx["session"]["id"], STAFF))
    assert session["enrolled_count"] == 1


def test_advance_child_demotes_off_level_enrollment_and_promotes_waitlist(api):
    """PRD §3.1: "Every ENROLLED RECURRING enrollment of that child sitting on a
    session whose program level_index no longer equals the child's new
    current_level is demoted from ENROLLED to WAITLISTED"
    PRD §3.1: "decrements that session's enrolled_count by one, and bumps the
    session's version. Freeing that seat in turn triggers promotion of the next
    waitlisted row on that session, exactly as an ordinary cancellation would."

    Capacity-1 level-0 session with child A ENROLLED and child B WAITLISTED.
    Advancing A to level 1 demotes A to WAITLISTED, promotes B to ENROLLED;
    enrolled_count stays 1 and A.current_level becomes 1.

    Design: Difficulty/transitive_cascade/advancement_demote_promote_cascade_depth2
    """
    set_clock("2026-05-01T00:00:00Z")
    # Build the ladder: level 0 (next -> level 1).
    prog1 = create_program(level_index=1, tuition_cents=5000)
    prog0 = create_program(level_index=0, tuition_cents=4000, next_program_id=prog1["id"])
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0, 1])
    session = create_session(prog0["id"], room["id"], instructor["id"], capacity=1)
    family, membership = create_active_membership(tier="PLUS")
    child_a = create_child(family["id"], full_name="A", birth_date="2024-01-01")
    child_b = create_child(family["id"], full_name="B", birth_date="2024-02-01")
    enr_a = enroll_child(child_a["id"], session["id"], membership["id"], kind="RECURRING")
    enr_b = enroll_child(child_b["id"], session["id"], membership["id"], kind="RECURRING")
    advanced = validate_success(
        api.advance_child(child_a["id"], {"target_program_id": prog1["id"]}, STAFF), 200,
    )
    assert advanced["current_level"] == 1
    enr_a_after = get_success_data(api.get_enrollment(enr_a["id"], STAFF))
    enr_b_after = get_success_data(api.get_enrollment(enr_b["id"], STAFF))
    assert enr_a_after["status"] == "WAITLISTED"
    assert enr_b_after["status"] == "ENROLLED"
    session_after = get_success_data(api.get_session(session["id"], STAFF))
    assert session_after["enrolled_count"] == 1


def test_advance_child_updates_current_level(api):
    """PRD §3.1: "When staff advance a child, they supply the target_program_id of
    the destination program; the child's current_level is set to that program's
    level_index."

    Advancing a child with no enrollments simply sets current_level to the target
    program's level_index.

    Design: Difficulty/transitive_cascade/advancement_demote_promote_cascade_depth2
    """
    set_clock("2026-05-01T00:00:00Z")
    prog1 = create_program(level_index=1, tuition_cents=5000)
    prog0 = create_program(level_index=0, tuition_cents=4000, next_program_id=prog1["id"])
    family = fx.create_family()
    child = create_child(family["id"], birth_date="2024-01-01")
    advanced = validate_success(
        api.advance_child(child["id"], {"target_program_id": prog1["id"]}, STAFF), 200,
    )
    assert advanced["current_level"] == 1


def test_enroll_then_cancel_restores_seat_count(api):
    """PRD §3.4: "When a row is created ENROLLED, the session's enrolled_count is
    incremented by one."
    PRD §3.4: "the session's enrolled_count is decremented by one to free the seat"

    Capacity-3 session: enroll (count 0->1) then cancel that enrollment (1->0).
    enrolled_count returns to 0, capacity unchanged at 3.

    Design: Difficulty/compensating_invariant/seat_conservation_enroll_then_cancel_restores_capacity
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=3)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enr = enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
    mid = get_success_data(api.get_session(session["id"], STAFF))
    assert mid["enrolled_count"] == 1
    cancelled = validate_success(api.cancel_enrollment(enr["id"], STAFF), 200)
    assert cancelled["status"] == "CANCELLED"
    session_after = get_success_data(api.get_session(session["id"], STAFF))
    assert session_after["enrolled_count"] == 0
    assert session_after["capacity"] == 3


def test_cancelled_enrollment_is_terminal(api):
    """PRD §3.4: "The row transitions to the terminal CANCELLED state"

    Seat-conservation companion: the cancelled enrollment ends in the terminal
    CANCELLED state (the compensating action's observable on the Enrollment row).

    Design: Difficulty/compensating_invariant/seat_conservation_enroll_then_cancel_restores_capacity
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=3)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enr = enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
    validate_success(api.cancel_enrollment(enr["id"], STAFF), 200)
    enr_after = get_success_data(api.get_enrollment(enr["id"], STAFF))
    assert enr_after["status"] == "CANCELLED"
    session_after = get_success_data(api.get_session(session["id"], STAFF))
    assert session_after["enrolled_count"] == 0


def test_cancel_session_cascades_excused_credit_balance_depth3(api):
    """PRD §3.3: "At depth one, for each ENROLLED RECURRING enrollment in the
    session the system creates an AttendanceRecord with outcome EXCUSED."
    PRD §3.3: "At depth two, each EXCUSED record mints exactly one MakeupCredit on
    that enrollment's membership"
    PRD §3.3: "At depth three, each minted credit increments its membership's
    makeup_credit_balance by one and bumps that membership's version."
    PRD §3.3: "every ENROLLED or WAITLISTED enrollment in the session is
    transitioned to CANCELLED and the session's enrolled_count is set to 0."

    Cancelling a session holding one ENROLLED RECURRING child: session -> CANCELLED,
    membership balance 0->1, enrollment -> CANCELLED.

    Design: Difficulty/transitive_cascade/session_cancel_excused_credit_balance_cascade_depth3
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=4000)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enr = enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
    cancelled = validate_success(api.cancel_session(session["id"], STAFF), 200)
    assert cancelled["status"] == "CANCELLED"
    membership_after = get_success_data(api.get_membership(membership["id"], STAFF))
    assert membership_after["makeup_credit_balance"] == 1
    enr_after = get_success_data(api.get_enrollment(enr["id"], STAFF))
    assert enr_after["status"] == "CANCELLED"


def test_cancel_session_mints_credit_for_each_recurring_child(api):
    """PRD §3.3: "At depth two, each EXCUSED record mints exactly one MakeupCredit
    on that enrollment's membership, with issued_tuition_cents snapshotted to this
    cancelled session's program tuition_cents and status AVAILABLE."

    Companion: the minted credit carries the cancelled session's program tuition
    (4000) as issued_tuition_cents and status AVAILABLE.

    Design: Difficulty/transitive_cascade/session_cancel_excused_credit_balance_cascade_depth3
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=4000)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
    validate_success(api.cancel_session(session["id"], STAFF), 200)
    from test_helpers import validate_paginated
    resp = api.list_membership_makeup_credits(membership["id"], STAFF)
    credits, _meta = validate_paginated(resp)
    assert len(credits) == 1
    assert credits[0]["status"] == "AVAILABLE"
    assert credits[0]["issued_tuition_cents"] == 4000


def test_withdraw_child_sets_withdrawn_and_cancels_enrollment(api):
    """PRD §3.1: "Withdrawing a child sets the child's status to WITHDRAWN"
    PRD §3.1: "The withdrawal cascades over every ENROLLED or WAITLISTED enrollment
    of that child, transitioning each to CANCELLED. For each formerly ENROLLED
    enrollment, the host session's enrolled_count is decremented by one"

    Withdrawing an ENROLLED child sets status WITHDRAWN, cancels the enrollment,
    and drops the session's enrolled_count from 1 to 0.

    Design: Corner/state_machines/child_withdraw_sets_withdrawn_and_cancels_enrollment
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enr = enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
    withdrawn = validate_success(api.withdraw_child(child["id"], STAFF), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    enr_after = get_success_data(api.get_enrollment(enr["id"], STAFF))
    assert enr_after["status"] == "CANCELLED"
    session_after = get_success_data(api.get_session(session["id"], STAFF))
    assert session_after["enrolled_count"] == 0
