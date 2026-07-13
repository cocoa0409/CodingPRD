"""TimeSlot / Booking / Group lifecycle transitions and terminal lockdown (PRD §3.1, §3.5, §3.6, §3.7)."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_course_slot_guide, setup_open_slot, create_course, create_time_slot,
    create_participant, create_booking, create_group, get_time_slot, get_booking,
    get_group, create_guide, assign_guide, setup_booking_completed,
)

OP = TEST_USERS["operator_headers"]


def test_close_records_reason_and_sets_closed(api):
    """PRD §3.6: "An `Operator` may weather-close a slot from either `SCHEDULED` or `OPEN`
    into `CLOSED`, optionally supplying a `reason` that is recorded on the slot's
    `closure_reason`."

    Design: Difficulty/non_linear_state_machine/timeslot_close_reopen_cycle
    """
    course, ts, guide = setup_open_slot(api)
    closed = validate_success(api.close_time_slot(ts["id"], OP, reason="storm"), 200)
    assert closed["status"] == "CLOSED"
    assert closed["closure_reason"] == "storm"


def test_reopen_returns_open_and_clears_closure_reason(api):
    """PRD §3.1: "The same open action is the cycle edge that brings a weather-closed slot
    back from `CLOSED` to `OPEN` once the storm passes — it likewise requires at least one
    `ASSIGNED` guide, and as a side effect it clears `closure_reason` back to null."

    Design: Difficulty/non_linear_state_machine/timeslot_close_reopen_cycle
    """
    course, ts, guide = setup_open_slot(api)
    api.close_time_slot(ts["id"], OP, reason="storm")
    reopened = validate_success(api.open_time_slot(ts["id"], OP), 200)
    assert reopened["status"] == "OPEN"
    assert reopened["closure_reason"] is None


def test_checkin_branch_keeps_seat_held(api):
    """PRD §3.5: "Checking a booking in advances it from `CONFIRMED` to `CHECKED_IN`".
    PRD §3.4: "A slot's `booked_count` is the count of its bookings in the three active
    states `CONFIRMED`, `CHECKED_IN`, and `BRIEFED`".

    Design: Difficulty/non_linear_state_machine/booking_branch_checkin_vs_cancel_divergent_effects
    """
    course, ts, guide = setup_open_slot(api, capacity=4)
    p_a = create_participant(api, full_name="P A")
    api.sign_waiver(p_a["id"], {"signature_name": "P A"}, OP)
    booking = create_booking(api, ts["id"], p_a["id"])
    checked = validate_success(api.checkin_booking(booking["id"], OP), 200)
    assert checked["status"] == "CHECKED_IN"
    slot = get_time_slot(api, ts["id"])
    assert slot["remaining_capacity"] == 3  # seat still held


def test_cancel_branch_releases_seat(api):
    """PRD §3.6: "Cancellation cascades the same way as a closure at the booking level:
    outstanding gear checkouts are returned and their gear items freed to `AVAILABLE`, the
    seat is released, and any season-pass commitment is released."

    Design: Difficulty/non_linear_state_machine/booking_branch_checkin_vs_cancel_divergent_effects
    """
    course, ts, guide = setup_open_slot(api, capacity=4)
    p_a = create_participant(api, full_name="P A")
    p_b = create_participant(api, full_name="P B")
    b_a = create_booking(api, ts["id"], p_a["id"])
    b_b = create_booking(api, ts["id"], p_b["id"])
    assert get_time_slot(api, ts["id"])["remaining_capacity"] == 2
    cancelled = validate_success(api.cancel_booking(b_b["id"], OP), 200)
    assert cancelled["status"] == "CANCELLED"
    # a_a still held, b_b released -> back to 3
    assert get_time_slot(api, ts["id"])["remaining_capacity"] == 3


def test_cancel_from_completed_returns_invalid_state(api):
    """PRD §3.6: "A booking in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` may be voluntarily
    cancelled — by an `Operator` or by the owning `Customer` — into `CANCELLED`."
    PRD §2.9: "the target resource must be in a legal state for the requested transition,
    or the request fails with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_from_completed_returns_invalid_state
    """
    course, ts, guide, p, booking = setup_booking_completed(api)
    assert booking["status"] == "COMPLETED"
    res = api.cancel_booking(booking["id"], OP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert get_booking(api, booking["id"])["status"] == "COMPLETED"


def test_redeem_non_rainchecked_returns_invalid_state(api):
    """PRD §3.6: "A `RAINCHECKED` booking can be redeemed — by an `Operator` or the owning
    `Customer` — into a target slot supplied as `time_slot_id`."
    PRD §2.9: "the target resource must be in a legal state for the requested transition,
    or the request fails with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/redeem_non_rainchecked_returns_invalid_state
    """
    course = create_course(api)
    ts1 = create_time_slot(api, course["id"], start_at="2026-06-03T10:00:00Z")
    ts2 = create_time_slot(api, course["id"], start_at="2026-06-10T10:00:00Z")
    guide = create_guide(api)
    assign_guide(api, guide["id"], ts1["id"])
    p = create_participant(api)
    booking = create_booking(api, ts1["id"], p["id"])  # CONFIRMED, not RAINCHECKED
    res = api.redeem_booking(booking["id"], {"time_slot_id": ts2["id"]}, OP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_open_slot_without_guide_returns_no_guide_assigned(api):
    """PRD §3.1: "Opening a slot advances it from `SCHEDULED` to `OPEN`, but only if at
    least one guide is assigned to it in `ASSIGNED` status; with no assigned guide the open
    is refused with `ERR_NO_GUIDE_ASSIGNED`."

    Design: Corner/state_machines/open_slot_without_guide_returns_no_guide_assigned
    """
    course = create_course(api)
    ts = create_time_slot(api, course["id"], start_at="2026-06-03T10:00:00Z")
    res = api.open_time_slot(ts["id"], OP)
    validate_error(res, "ERR_NO_GUIDE_ASSIGNED", expected_status=409)
    assert get_time_slot(api, ts["id"])["status"] == "SCHEDULED"


def test_slot_complete_marks_confirmed_no_show(api):
    """PRD §3.6: "Any booking still lingering in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` at
    that moment is treated as a no-show: it is driven to `NO_SHOW`, its outstanding gear is
    returned and the gear items freed to `AVAILABLE`, and its seat and any season-pass
    commitment are released."
    PRD §3.6: "A no-show earns no credit — its `raincheck_credit_cents` stays 0."

    Design: Corner/state_machines/slot_complete_marks_confirmed_no_show
    """
    course, ts, guide = setup_open_slot(api, capacity=4)
    p = create_participant(api)
    booking = create_booking(api, ts["id"], p["id"])
    api.complete_time_slot(ts["id"], OP)
    after = get_booking(api, booking["id"])
    assert after["status"] == "NO_SHOW"
    assert after["raincheck_credit_cents"] == 0
    assert get_time_slot(api, ts["id"])["remaining_capacity"] == 4


def test_cancel_group_twice_returns_invalid_state(api):
    """PRD §3.7: "Cancelling a group — by an `Operator` or a `Customer` — drives it to the
    terminal `CANCELLED` state and cascades three levels."
    PRD §2.9: "the target resource must be in a legal state for the requested transition,
    or the request fails with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_group_twice_returns_invalid_state
    """
    course, ts, guide = setup_course_slot_guide(api)
    group = create_group(api, ts["id"], expected_size=2, name="Team")
    validate_success(api.cancel_group(group["id"], OP), 200)
    res = api.cancel_group(group["id"], OP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert get_group(api, group["id"])["status"] == "CANCELLED"
