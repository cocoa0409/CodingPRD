"""Booking and waiver state-machine transitions, including the weather/reschedule
cycle, terminal-state lockdown, and the guarded transitions that gate completion,
weather-hold, and release-hold.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_config, create_quote_draft_booking, hold_booking, add_waiver, sign_waiver,
    create_held_booking, create_confirmed_booking, create_completed_booking,
    create_weather_held_booking, set_clock, take_payment, NON_EXISTENT_UUID,
    assert_instant_eq,
)

COORD = "coordinator_headers"


# ─── Difficulty: non_linear_state_machine / nlsm_booking_weather_reschedule_cycle

def test_weather_reschedule_cycle_returns_to_confirmed(api, coordinator_headers):
    """PRD 3.9: "On success the server releases the old reserved room window and
    reserves the new one, sets `event_start_utc` to the new start, recomputes
    `event_end_utc`, and increments `reschedule_count` by one."

    Design: Difficulty/non_linear_state_machine/nlsm_booking_weather_reschedule_cycle
    """
    ctx = create_weather_held_booking(children_count=8)
    bid = ctx["booking"]["id"]
    version = ctx["booking"]["version"]

    rescheduled = validate_success(api.reschedule_booking(
        bid, {"event_start_utc": "2026-07-05T10:00:00Z",
              "expected_booking_version": version}, coordinator_headers), 200)
    assert rescheduled["status"] == "RESCHEDULED"
    assert rescheduled["reschedule_count"] == 1
    assert_instant_eq(rescheduled["event_start_utc"], "2026-07-05T10:00:00Z")
    assert_instant_eq(rescheduled["event_end_utc"], "2026-07-05T12:00:00Z")

    confirmed = validate_success(api.confirm_booking(bid, coordinator_headers), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["reschedule_count"] == 1


def test_weather_hold_transition_from_confirmed(api, coordinator_headers):
    """PRD 3.9: "A `Coordinator` may move a `CONFIRMED` booking to `WEATHER_HOLD` only
    if the booking is `weather_eligible`".

    Design: Difficulty/non_linear_state_machine/nlsm_booking_weather_reschedule_cycle
    """
    ctx = create_confirmed_booking(
        children_count=8, weather_dependent=True, room_kind="OUTDOOR", pay_amount=7500)
    bid = ctx["booking"]["id"]
    assert ctx["booking"]["weather_eligible"] is True
    held = validate_success(api.weather_hold_booking(bid, coordinator_headers), 200)
    assert held["status"] == "WEATHER_HOLD"


# ─── Difficulty: non_linear_state_machine / nlsm_waiver_sign_revoke_branch ─────

def test_waiver_sign_then_revoke_branch(api, coordinator_headers):
    """PRD 3.5: "A signed waiver may be revoked back to `DRAFT`, which decrements the
    parent's `waivers_signed`."

    Design: Difficulty/non_linear_state_machine/nlsm_waiver_sign_revoke_branch
    """
    venue, room, package = setup_config(included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    hold_booking(bid)
    waiver = add_waiver(bid, child_name="c1")
    signed = sign_waiver(bid, waiver["id"])
    assert signed["status"] == "SIGNED"
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["waivers_signed"] == 1

    revoked = validate_success(api.revoke_waiver(bid, waiver["id"], coordinator_headers), 200)
    assert revoked["status"] == "DRAFT"
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["waivers_signed"] == 0


def test_waiver_sign_increments_then_revoke_resets(api, coordinator_headers):
    """PRD 3.5: "signing moves the waiver from `DRAFT` to `SIGNED` and increments the
    parent booking's `waivers_signed`."

    Design: Difficulty/non_linear_state_machine/nlsm_waiver_sign_revoke_branch
    """
    venue, room, package = setup_config(included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    hold_booking(bid)
    waiver = add_waiver(bid, child_name="c1")
    assert waiver["status"] == "DRAFT"
    sign_waiver(bid, waiver["id"])
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["waivers_signed"] == 1
    api.revoke_waiver(bid, waiver["id"], coordinator_headers)
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["waivers_signed"] == 0


# ─── Corner: state_machines / new_booking_starts_in_quote_draft ────────────────

def test_new_booking_starts_in_quote_draft(api, coordinator_headers):
    """PRD 3.2: "The new booking lands in `QUOTE_DRAFT`."

    Design: Corner/state_machines/new_booking_starts_in_quote_draft
    """
    venue, room, package = setup_config(included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    assert booking["status"] == "QUOTE_DRAFT"
    assert booking["reschedule_count"] == 0
    assert booking["payment_status"] == "UNPAID"


# ─── Corner: state_machines / cancel_already_cancelled_booking_invalid_state ───

def test_cancel_already_cancelled_returns_invalid_state(api, coordinator_headers):
    """PRD 3.12: "A `Coordinator` or a `Guardian` may cancel a booking from any
    non-terminal state — `QUOTE_DRAFT`, `HELD`, `CONFIRMED`, `WEATHER_HOLD`, or
    `RESCHEDULED` — moving it to `CANCELLED`."

    Design: Corner/state_machines/cancel_already_cancelled_booking_invalid_state
    """
    venue, room, package = setup_config(included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    validate_success(api.cancel_booking(bid, coordinator_headers), 200)
    res = api.cancel_booking(bid, coordinator_headers)
    validate_error(res, "ERR_INVALID_STATE")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "CANCELLED"


# ─── Corner: state_machines / completed_booking_terminal_no_transition ─────────

def test_completed_booking_cannot_be_cancelled(api, coordinator_headers):
    """PRD 3.10: "`COMPLETED` is terminal."

    Design: Corner/state_machines/completed_booking_terminal_no_transition
    """
    ctx = create_completed_booking(children_count=8, base_price_cents=30000,
                                   included_children=8, pay_amount=30000)
    bid = ctx["booking"]["id"]
    assert ctx["booking"]["status"] == "COMPLETED"
    res = api.cancel_booking(bid, coordinator_headers)
    validate_error(res, "ERR_INVALID_STATE")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "COMPLETED"


# ─── Corner: state_machines / release_hold_with_payments_rejected ──────────────

def test_release_hold_with_payments_rejected(api, coordinator_headers):
    """PRD 3.7: "Release is allowed only while the booking's `payment_status` is
    `UNPAID`; if any payment has been taken the release is rejected with
    `ERR_HOLD_HAS_PAYMENTS`."

    Design: Corner/state_machines/release_hold_with_payments_rejected
    """
    venue, room, package, booking = create_held_booking(children_count=8, base_price_cents=30000)
    bid = booking["id"]
    take_payment(bid, 7500, direction="CHARGE", purpose="DEPOSIT")
    res = api.release_hold_booking(bid, coordinator_headers)
    validate_error(res, "ERR_HOLD_HAS_PAYMENTS")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "HELD"


# ─── Corner: state_machines / weather_hold_after_event_started_rejected ────────

def test_weather_hold_after_event_started_rejected(api, coordinator_headers):
    """PRD 3.9: "only if the event has not yet started, meaning the clock's
    `current_utc` is strictly before `event_start_utc`; an attempt at or after the
    start is rejected with `ERR_EVENT_ALREADY_STARTED`."

    Design: Corner/state_machines/weather_hold_after_event_started_rejected
    """
    ctx = create_confirmed_booking(
        children_count=8, weather_dependent=True, room_kind="OUTDOOR", pay_amount=7500)
    bid = ctx["booking"]["id"]
    set_clock("2026-07-01T10:00:00Z")  # exactly at event_start
    res = api.weather_hold_booking(bid, coordinator_headers)
    validate_error(res, "ERR_EVENT_ALREADY_STARTED")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "CONFIRMED"


# ─── Corner: state_machines / complete_before_event_ended_rejected ─────────────

def test_complete_before_event_ended_rejected(api, coordinator_headers):
    """PRD 3.10: "The event must have ended: the clock's `current_utc` must be at or
    after `event_end_utc`, or completion is rejected with `ERR_EVENT_NOT_ENDED`."

    Design: Corner/state_machines/complete_before_event_ended_rejected
    """
    ctx = create_confirmed_booking(children_count=8, base_price_cents=30000,
                                   included_children=8, pay_amount=30000)
    bid = ctx["booking"]["id"]
    set_clock("2026-07-01T11:00:00Z")  # before event_end 12:00
    res = api.complete_booking(bid, coordinator_headers)
    validate_error(res, "ERR_EVENT_NOT_ENDED")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "CONFIRMED"
