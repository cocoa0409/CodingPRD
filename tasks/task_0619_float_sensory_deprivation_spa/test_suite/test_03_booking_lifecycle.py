"""Booking lifecycle: the reschedule cycle, the confirmation eligibility gate, check-in tank
gating, initial/terminal states, and orientation side effects feeding the gate."""
from test_helpers import (
    validate_success, validate_error,
    setup_confirmed_cash_booking_future, setup_reserved_cash_booking_unoriented,
    setup_confirmed_credit_booking_tank_in_cycle, setup_completed_credit_booking,
    setup_member_and_tank, setup_scheduled_orientation,
    create_booking,
    api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


# ─── Reschedule cycle (nlsm_booking_reschedule_cycle) ─────────────────────
def test_reschedule_then_confirm_returns_to_confirmed(api):
    """PRD §3.6: "A booking may also be confirmed out of the `RESCHEDULED` state, which cycles
    it back to `CONFIRMED` after a time change — this is the reschedule cycle, and
    confirmation is defined from both `RESERVED` and `RESCHEDULED`."

    Design: Difficulty/non_linear_state_machine/nlsm_booking_reschedule_cycle
    """
    ctx = setup_confirmed_cash_booking_future()
    bk = ctx["booking"]
    validate_success(
        api.reschedule_booking(bk["id"], {"new_start_utc": "2026-07-11T14:00:00Z"},
                               FRONTDESK), 200)
    reconfirmed = validate_success(api.confirm_booking(bk["id"], FRONTDESK), 200)
    assert reconfirmed["status"] == "CONFIRMED", (
        f"expected CONFIRMED after reschedule+confirm, got {reconfirmed['status']}"
    )


def test_reschedule_moves_window_to_new_start_and_end(api):
    """PRD §3.6: "A `CONFIRMED` booking may be **rescheduled** to a new start time, supplied
    as `new_start_utc`, which moves it to `RESCHEDULED` and recomputes its window (`start_utc`
    and `end_utc` shift to the new times) while leaving the deposit untouched".

    Design: Difficulty/non_linear_state_machine/nlsm_booking_reschedule_cycle
    """
    ctx = setup_confirmed_cash_booking_future()
    bk = ctx["booking"]
    validate_success(
        api.reschedule_booking(bk["id"], {"new_start_utc": "2026-07-11T14:00:00Z"},
                               FRONTDESK), 200)
    final = validate_success(api.confirm_booking(bk["id"], FRONTDESK), 200)
    # Timestamps are serialized in ISO 8601 UTC with three fractional digits (PRD §2.4).
    assert final["start_utc"] == "2026-07-11T14:00:00.000Z"
    # 60-min session -> end_utc one hour after the new start.
    assert final["end_utc"] == "2026-07-11T15:00:00.000Z"


# ─── Cross-entity confirm gate (cesd_booking_confirm_requires_member_oriented) ──
def test_confirm_unoriented_member_rejected(api):
    """PRD §3.6: "Confirmation is the eligibility gate: the member must have completed
    orientation (`orientation_completed` true), must have signed a waiver whose version is at
    least the current waiver version of 1 ... and must not be suspended ... A booking that
    fails any of these is refused with `ERR_MEMBER_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_booking_confirm_requires_member_oriented
    """
    ctx = setup_reserved_cash_booking_unoriented()
    bk = ctx["booking"]
    res = api.confirm_booking(bk["id"], FRONTDESK)
    validate_error(res, "ERR_MEMBER_NOT_ELIGIBLE", expected_status=409)


def test_confirm_unoriented_member_keeps_booking_reserved(api):
    """PRD §3.6: "A booking that fails any of these is refused with `ERR_MEMBER_NOT_ELIGIBLE`."
    PRD §3.6: "Before a reserved booking can proceed it must be **confirmed**, moving it from
    `RESERVED` to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_booking_confirm_requires_member_oriented
    """
    ctx = setup_reserved_cash_booking_unoriented()
    bk = ctx["booking"]
    api.confirm_booking(bk["id"], FRONTDESK)
    after = validate_success(api.get_booking(bk["id"], FRONTDESK), 200)
    assert after["status"] == "RESERVED", (
        f"booking must remain RESERVED after a rejected confirm, got {after['status']}"
    )


# ─── Cross-entity check-in gate (cesd_booking_checkin_requires_tank_clean) ──
def test_checkin_on_in_cycle_tank_rejected(api):
    """PRD §3.6: "The tank must be available on both axes — `IN_SERVICE` operationally and
    `CLEAN` on sanitation — and a tank failing either is refused with `ERR_TANK_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_booking_checkin_requires_tank_clean
    """
    ctx = setup_confirmed_credit_booking_tank_in_cycle(zero_balance=False)
    bk = ctx["booking"]
    res = api.check_in_booking(bk["id"], FRONTDESK)
    validate_error(res, "ERR_TANK_UNAVAILABLE", expected_status=409)


def test_checkin_on_in_cycle_tank_keeps_booking_confirmed(api):
    """PRD §3.6: "Check-in moves a `CONFIRMED` booking to `CHECKED_IN` and is a front-desk
    action." PRD §3.6: "a tank failing either is refused with `ERR_TANK_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_booking_checkin_requires_tank_clean
    """
    ctx = setup_confirmed_credit_booking_tank_in_cycle(zero_balance=False)
    bk = ctx["booking"]
    api.check_in_booking(bk["id"], FRONTDESK)
    after = validate_success(api.get_booking(bk["id"], FRONTDESK), 200)
    assert after["status"] == "CONFIRMED", (
        f"booking must remain CONFIRMED after a rejected check-in, got {after['status']}"
    )


# ─── Initial state (new_booking_starts_in_reserved) ───────────────────────
def test_new_booking_starts_reserved(api):
    """PRD §3.5: "A new booking is created `RESERVED`, and its `end_utc` is computed as
    `start_utc` plus `session_minutes`".

    Design: Corner/state_machines/new_booking_starts_in_reserved
    """
    ctx = setup_member_and_tank()
    booking = create_booking(ctx["member"]["id"], ctx["tank"]["id"], 90,
                             "2026-02-01T10:00:00Z", "CASH")
    assert booking["status"] == "RESERVED"


# ─── Invalid transition: complete from RESERVED ───────────────────────────
def test_complete_reserved_booking_rejected(api):
    """PRD §2.7: "Only once a request is authenticated, authorized, resolvable, well-formed,
    and in-range does the system evaluate state-machine legality, which fails with
    `ERR_INVALID_STATE` (HTTP 409) when a transition is not defined from the resource's current
    state."

    Design: Corner/state_machines/complete_booking_from_reserved_returns_invalid_state
    """
    ctx = setup_member_and_tank()
    booking = create_booking(ctx["member"]["id"], ctx["tank"]["id"], 60,
                             "2026-02-01T10:00:00Z", "CASH")
    res = api.complete_booking(booking["id"], FRONTDESK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_booking(booking["id"], FRONTDESK), 200)
    assert after["status"] == "RESERVED"


# ─── Terminal state lockdown: cancel COMPLETED booking ────────────────────
def test_cancel_completed_booking_rejected(api):
    """PRD §3.7: "Cancellation is defined from `RESERVED`, `CONFIRMED`, and `RESCHEDULED`; it
    is deliberately *not* available from `CHECKED_IN`, because by check-in any credits have
    already been consumed, and an attempt to cancel a checked-in booking is an illegal
    transition."

    Design: Corner/state_machines/cancel_terminal_completed_booking_rejected
    """
    ctx = setup_completed_credit_booking()
    bk = ctx["booking"]
    assert bk["status"] == "COMPLETED"
    res = api.cancel_booking(bk["id"], FRONTDESK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_booking(bk["id"], FRONTDESK), 200)
    assert after["status"] == "COMPLETED"


# ─── Orientation completion side effect ───────────────────────────────────
def test_orientation_completion_marks_member_oriented(api):
    """PRD §3.2: "Completion is the moment the waiver is recorded: it writes the orientation's
    `waiver_version` onto the member's `waiver_signed_version` and flips the member's
    `orientation_completed` to true."

    Design: Corner/state_machines/orientation_completion_sets_member_oriented_sideeffect
    """
    ctx = setup_scheduled_orientation("2026-03-01T09:00:00Z",
                                      complete_clock="2026-03-01T09:05:00Z",
                                      waiver_version=1)
    validate_success(api.complete_orientation(ctx["orientation"]["id"], FRONTDESK), 200)
    member = validate_success(api.get_member(ctx["member"]["id"], FRONTDESK), 200)
    assert member["orientation_completed"] is True
    assert member["waiver_signed_version"] == 1
