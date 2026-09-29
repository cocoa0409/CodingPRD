"""Counters checked before an action, after it, and after it is undone.

Issuing invitations raises a wave counter and a program counter together, and
closing the wave has to walk back through the invitations to the applications to
put both counters back. Booking a seat and then handing it back has to move one
seat rather than duplicate or lose it.
"""

from __future__ import annotations

from test_helpers import (
    InterviewStatus,
    InvitationStatus,
    SlotStatus,
    WaveStatus,
    assert_slot_booking,
    assert_wave_seat_conservation,
    get_success_data,
    setup_issued_invitations,
    setup_released_wave,
    validate_success,
)

SECOND_SLOT_START = "2026-10-06T13:00:00Z"
SECOND_SLOT_END = "2026-10-06T16:00:00Z"


def _released_wave_holding_no_invitations():
    """Two advanced applications and a two-seat wave that has issued nothing."""
    return setup_released_wave(applicant_count=2, seat_capacity=2, slot_capacity=1)


def _two_issued_invitations():
    """The same wave after both applications have been invited."""
    builder = _released_wave_holding_no_invitations()
    builder.issue_invitation("inv1", "app1")
    builder.issue_invitation("inv2", "app2")
    return builder


def _one_invitation_and_two_single_seat_blocks():
    """One issued invitation and two blocks, each able to host one applicant."""
    builder = setup_issued_invitations(
        applicant_count=1, seat_capacity=4, slot_capacity=1
    )
    builder.create_slot(
        "slot2",
        start_at=SECOND_SLOT_START,
        end_at=SECOND_SLOT_END,
        room_label="A-2",
        applicant_capacity=1,
    )
    return builder


def test_both_invitation_counters_start_at_zero(api):
    """Before the first invitation, the wave and the program both count nothing.

    Both figures are derived counts, so an empty wave over two advanced
    applications must read zero on each side.

    PRD 3.4: "`Program.invited_count` is by definition the number of applications under the program whose `interview_status` is anything other than `NOT_INVITED`."
    PRD 3.3: "The wave materialises with `status` `PLANNED` and `issued_count` at 0, where `issued_count` is by definition the number of invitations in the wave whose `status` is `ISSUED` or `ACCEPTED`."

    Design: Difficulty/compensating_invariant/invited_count_conserved_across_invitation_issue_and_wave_close
    """
    builder = _released_wave_holding_no_invitations()

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert program["invited_count"] == 0, (
        f"no application is invited yet, got {program['invited_count']}"
    )

    wave = get_success_data(
        api.get_interview_wave(builder.id("wave1"), builder.coordinator)
    )
    assert_wave_seat_conservation(wave, expected_issued=0)


def test_issuing_two_invitations_raises_both_counters_together(api):
    """The forward action moves the wave counter and the program counter to two.

    Each create consumes one of the two seats and advances its own application's
    interview dimension, which is what the program counter reads.

    PRD 3.4: "Creating an issued invitation carries four further effects: `InterviewWave.issued_count` increments by one, the invited application advances `NOT_INVITED → INVITED` on its interview dimension (which requires the application's `screening_status` to be `ADVANCED` — an unadvanced application cannot be invited at all), `Program.invited_count` is recomputed, and the wave's `version` increments by one."
    PRD 3.4: "While `issued_count` is strictly below `seat_capacity`, the invitation is created with `status` `ISSUED`, its `issued_at` stamped with the current logical clock instant, and its `expires_at` set to **the earlier of** the wave's `response_deadline_at` and `issued_at` plus 120 hours — a five-day response window."

    Design: Difficulty/compensating_invariant/invited_count_conserved_across_invitation_issue_and_wave_close
    """
    builder = _two_issued_invitations()

    wave = get_success_data(
        api.get_interview_wave(builder.id("wave1"), builder.coordinator)
    )
    assert_wave_seat_conservation(wave, expected_issued=2)

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert program["invited_count"] == 2, (
        f"both applications should be counted as invited, got {program['invited_count']}"
    )

    for app_key in ("app1", "app2"):
        application = get_success_data(
            api.get_application(builder.id(app_key), builder.coordinator)
        )
        assert application["interview_status"] == InterviewStatus.INVITED, (
            f"{app_key} should be INVITED, got {application['interview_status']}"
        )


def test_closing_the_wave_returns_both_counters_to_zero(api):
    """The compensating action reaches the applications and not just the invitations.

    Both invitations lapse, both applications fall back to uninvited, and the two
    counters that rose together come back down together.

    PRD 3.4: "An `ISSUED` invitation drives `ISSUED → EXPIRED` either because the logical clock has reached or passed its `expires_at` on a lapse sweep, or because its wave is closing; the effects are that the wave's `issued_count` decrements by one and the application reverts `INVITED → NOT_INVITED` when it retains no invitation in `ISSUED`, `WAITLISTED` or `ACCEPTED`."
    PRD 3.4: "Closing a wave is therefore the wholesale application of both: it drives the wave `RELEASED → CLOSED`, sets every invitation in the wave whose `status` is `ISSUED` or `WAITLISTED` to `EXPIRED`, reverts `INVITED → NOT_INVITED` for each application whose last active invitation was thereby expired, recomputes the wave's `issued_count`, recomputes `Program.invited_count`, and increments the wave's `version` by one."

    Design: Difficulty/compensating_invariant/invited_count_conserved_across_invitation_issue_and_wave_close
    """
    builder = _two_issued_invitations()

    builder.close_wave()

    wave = get_success_data(
        api.get_interview_wave(builder.id("wave1"), builder.coordinator)
    )
    assert wave["status"] == WaveStatus.CLOSED, (
        f"the closed wave should be CLOSED, got {wave['status']}"
    )
    assert_wave_seat_conservation(wave, expected_issued=0)

    for inv_key in ("inv1", "inv2"):
        invitation = get_success_data(
            api.get_interview_invitation(builder.id(inv_key), builder.coordinator)
        )
        assert invitation["status"] == InvitationStatus.EXPIRED, (
            f"{inv_key} should lapse to EXPIRED, got {invitation['status']}"
        )

    for app_key in ("app1", "app2"):
        application = get_success_data(
            api.get_application(builder.id(app_key), builder.coordinator)
        )
        assert application["interview_status"] == InterviewStatus.NOT_INVITED, (
            f"{app_key} should revert to NOT_INVITED, got "
            f"{application['interview_status']}"
        )

    program = get_success_data(api.get_program(builder.id("program"), builder.admin))
    assert program["invited_count"] == 0, (
        "no application is invited once the wave is closed, got "
        f"{program['invited_count']}"
    )


def test_accepting_consumes_exactly_one_of_the_two_seats(api):
    """The forward action books the first block and leaves the second untouched.

    That block hosts one applicant, so the single booking fills it and the seat
    total across the wave is one.

    PRD 3.4: "Acceptance stores the chosen `slot_id` and stamps `responded_at` with the current logical clock instant, increments the slot's `booked_count` by one, moves the slot `OPEN → BOOKED` when `booked_count` reaches `applicant_capacity`, and advances the application `INVITED → SCHEDULED` on its interview dimension — which itself requires that the accepted invitation's `slot_id` is no longer null."
    PRD 2.10: "The slot's `status` follows occupancy in both directions: it moves `OPEN → BOOKED` when the pool empties and back `BOOKED → OPEN` the moment the pool is non-empty again."

    Design: Difficulty/compensating_invariant/booked_seat_total_conserved_across_accept_and_reschedule
    """
    builder = _one_invitation_and_two_single_seat_blocks()

    builder.accept_invitation("inv1", "slot1", "cand1")

    first = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(first, expected_booked=1, expected_status=SlotStatus.BOOKED)

    second = get_success_data(
        api.get_interview_slot(builder.id("slot2"), builder.coordinator)
    )
    assert_slot_booking(second, expected_booked=0, expected_status=SlotStatus.OPEN)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.SCHEDULED, (
        f"the booked application should be SCHEDULED, got {application['interview_status']}"
    )


def test_rescheduling_hands_the_seat_back_and_reopens_the_block(api):
    """The compensating action restores exactly what the acceptance consumed.

    The block is open at zero rather than left BOOKED at zero, and the invitation
    is issued again with nothing booked and no answer recorded.

    PRD 3.4: "**Rescheduling** lets an applicant hand back a booked seat to choose another, driving `ACCEPTED → ISSUED`."
    PRD 3.4: "Four effects follow: the previously booked slot's `booked_count` decrements by one and that slot returns `BOOKED → OPEN` when `booked_count` falls below `applicant_capacity`; the invitation's `slot_id` and `responded_at` are both cleared to null; `issued_at` is re-stamped with the current logical clock instant and `expires_at` is recomputed as the earlier of the wave's `response_deadline_at` and the new `issued_at` plus 120 hours, so the response window genuinely restarts; and the application reverts `SCHEDULED → INVITED`."

    Design: Difficulty/compensating_invariant/booked_seat_total_conserved_across_accept_and_reschedule
    """
    builder = _one_invitation_and_two_single_seat_blocks()
    builder.accept_invitation("inv1", "slot1", "cand1")

    rescheduled = validate_success(
        api.reschedule_interview_invitation(
            builder.id("inv1"), builder.applicant("cand1")
        )
    )
    assert rescheduled["status"] == InvitationStatus.ISSUED, (
        f"the returned invitation should be ISSUED again, got {rescheduled['status']}"
    )
    assert rescheduled["slot_id"] is None, (
        f"the booking is cleared to null, got {rescheduled['slot_id']}"
    )
    assert rescheduled["responded_at"] is None, (
        f"the answer is cleared to null, got {rescheduled['responded_at']}"
    )

    freed = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(freed, expected_booked=0, expected_status=SlotStatus.OPEN)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.INVITED, (
        f"the application reverts to INVITED, got {application['interview_status']}"
    )


def test_the_second_acceptance_moves_the_same_seat_to_the_other_block(api):
    """One seat travels from the first block to the second rather than being copied.

    After the move the second block is full, the first is open, and the invitation
    names the new block.

    PRD 2.10: "Every accept consumes one seat; every decline-after-accept, reschedule-away, applicant withdrawal and slot cancellation restores exactly what it consumed."
    PRD 3.4: "An invitation's `slot_id` is null whenever its `status` is `ISSUED`, `WAITLISTED`, `DECLINED`, `EXPIRED` or `WITHDRAWN`; it holds a value only while the invitation is `ACCEPTED`."

    Design: Difficulty/compensating_invariant/booked_seat_total_conserved_across_accept_and_reschedule
    """
    builder = _one_invitation_and_two_single_seat_blocks()
    builder.accept_invitation("inv1", "slot1", "cand1")
    api.reschedule_interview_invitation(builder.id("inv1"), builder.applicant("cand1"))

    builder.accept_invitation("inv1", "slot2", "cand1")

    first = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(first, expected_booked=0, expected_status=SlotStatus.OPEN)

    second = get_success_data(
        api.get_interview_slot(builder.id("slot2"), builder.coordinator)
    )
    assert_slot_booking(second, expected_booked=1, expected_status=SlotStatus.BOOKED)

    invitation = get_success_data(
        api.get_interview_invitation(builder.id("inv1"), builder.coordinator)
    )
    assert invitation["status"] == InvitationStatus.ACCEPTED
    assert invitation["slot_id"] == builder.id("slot2"), (
        "the invitation should name the newly booked block, got "
        f"{invitation['slot_id']}"
    )

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["interview_status"] == InterviewStatus.SCHEDULED
