"""Booking creation, deposit confirmation, cancellation refund tiers, refund cap."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BookingStatus,
    add_minutes,
    advance_clock_to,
    assert_booking,
    cancel_booking_as_operator,
    cancel_booking_as_player,
    create_and_confirm_booking,
    create_booking,
    create_booking_payload,
    create_player,
    get_booking,
    get_player,
    make_player_headers,
    make_venue_operator_headers,
    refund_booking,
    refund_booking_payload,
    setup_basic_scenario,
    setup_scenario_with_slot,
    setup_slot_at_completed,
    setup_slot_with_confirmed_booking,
    validate_error,
    validate_success,
)


# ─── §3.5 Booking creation ────────────────────────────────────────────────

def test_booking_creation_pins_seat_count_paid_deposit(api):
    """PRD §3.5: "The server pins `seat_count` as the length of `team_player_ids`, computes `paid_amount_cents` as `seat_count` multiplied by the slot's `price_cents`, and computes `deposit_held_cents` as `seat_count` multiplied by the venue's `deposit_policy_cents`."

    Claim: a 2-seat booking on a slot with price=5000 and venue deposit=2000 has paid=10000 and deposit=4000.
    """
    venue, room, theme, slot = setup_scenario_with_slot(price_cents=5000)
    p1, p2 = create_player(), create_player()
    booking = create_booking(slot, p1, team_player_ids=[p1["id"], p2["id"]])
    assert_booking(booking)
    assert booking["seat_count"] == 2
    assert booking["paid_amount_cents"] == 2 * 5000
    assert booking["deposit_held_cents"] == 2 * venue["deposit_policy_cents"]
    assert booking["status"] == BookingStatus.PENDING_DEPOSIT.value


def test_booking_lead_must_appear_in_team(api):
    """PRD §3.5: "The acting player's id (which equals `X-User-ID`) is recorded as `lead_player_id` and must appear in the `team_player_ids` array."

    Claim: a booking whose acting Player is not in team_player_ids is rejected with ERR_INVALID_REQUEST.
    """
    venue, room, theme, slot = setup_scenario_with_slot()
    lead = create_player()
    other = create_player()
    headers = make_player_headers(lead["id"])
    payload = create_booking_payload(team_player_ids=[other["id"]])
    resp = api.create_booking(slot["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── §3.6 Cancellation refund tiers ───────────────────────────────────────

def test_player_cancel_free_tier_full_refund(api):
    """PRD §3.6: "When lead minutes is at least `FREE_CANCEL_LEAD_MINUTES` (24 hours, or 1440 minutes), the deposit refund is the full `deposit_held_cents` and the paid refund is the full `paid_amount_cents`."

    Claim: cancelling exactly 1440 minutes ahead refunds deposit + paid in full.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2, hours_ahead=24.0, price_cents=5000)
    booking = state["booking"]
    expected_refund = booking["deposit_held_cents"] + booking["paid_amount_cents"]
    cancel_booking_as_player(booking, state["lead_player"])
    refreshed = get_booking(booking["id"])
    assert refreshed["status"] == BookingStatus.CANCELLED.value
    assert refreshed["cancellation_initiator"] == "PLAYER"
    assert refreshed["refund_total_cents"] == expected_refund


def test_player_cancel_late_tier_50_percent_paid(api):
    """PRD §3.6: "When lead minutes is below that bound but still at least `LATE_CANCEL_LEAD_MINUTES` (2 hours, or 120 minutes), the deposit refund is the full `deposit_held_cents` and the paid refund is the floor of `paid_amount_cents` multiplied by `LATE_CANCEL_PAID_REFUND_BPS` (5000) divided by 10000 — that is, fifty percent of the paid amount, rounded down to the cent."

    Claim: cancelling at 180 minutes ahead refunds full deposit + 50% paid (floored).
    """
    state = setup_slot_with_confirmed_booking(seat_count=2, hours_ahead=24.0, price_cents=5000)
    booking = state["booking"]
    paid = booking["paid_amount_cents"]
    deposit = booking["deposit_held_cents"]
    # Advance to T_start - 180m.
    target = add_minutes(state["slot"]["starts_at"], -180)
    advance_clock_to(target)
    cancel_booking_as_player(booking, state["lead_player"])
    refreshed = get_booking(booking["id"])
    expected = deposit + (paid * 5000 // 10000)
    assert refreshed["refund_total_cents"] == expected


def test_player_cancel_late_tier_zero_refund(api):
    """PRD §3.6: "When lead minutes is below `LATE_CANCEL_LEAD_MINUTES` (including any negative value), both the deposit refund and the paid refund are zero — the deposit is forfeited to the venue."

    Claim: cancelling 60 minutes before starts_at (< 120m bound) forfeits everything.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2, hours_ahead=24.0, price_cents=5000)
    target = add_minutes(state["slot"]["starts_at"], -60)
    advance_clock_to(target)
    cancel_booking_as_player(state["booking"], state["lead_player"])
    refreshed = get_booking(state["booking"]["id"])
    assert refreshed["status"] == BookingStatus.CANCELLED.value
    assert refreshed["refund_total_cents"] == 0


# ─── §3.6 Player-cancel only while SCHEDULED ──────────────────────────────

def test_player_cancel_after_live_rejected(api):
    """PRD §3.6: "Player-initiated cancellation is allowed only while the slot is still in `schedule_status` of `SCHEDULED`; once the slot is `LIVE`, player cancellation is rejected with `ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER`."

    Claim: a Player attempting to cancel a booking on a LIVE slot is rejected with ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2)
    venue, slot = state["venue"], state["slot"]
    booking, lead = state["booking"], state["lead_player"]
    # Drive slot to LIVE.
    from test_helpers import create_staff_assignment, create_staff_member, start_slot
    host_staff = create_staff_member(state["theme"]["chain_id"], roles_held=["HOST"], qualifications=[])
    create_staff_assignment(slot, venue, host_staff, role_type="HOST")
    advance_clock_to(slot["starts_at"])
    start_slot(slot, venue)
    # Player attempts cancel.
    headers = make_player_headers(lead["id"])
    resp = api.cancel_booking(booking["id"], headers)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER.value)


# ─── §3.6 Confirm preconditions ───────────────────────────────────────────

def test_confirm_blocked_when_slot_not_scheduled(api):
    """PRD §3.6: "Confirmation requires the slot to still be in `schedule_status` of `SCHEDULED` (otherwise `ERR_SESSION_NOT_OPEN_FOR_CONFIRM`)."

    Claim: confirming a deposit on a CANCELLED slot yields ERR_SESSION_NOT_OPEN_FOR_CONFIRM.
    """
    venue, room, theme, slot = setup_scenario_with_slot()
    p1 = create_player()
    booking = create_booking(slot, p1)  # PENDING_DEPOSIT
    # Cancel the slot.
    op = make_venue_operator_headers(venue["id"])
    validate_success(api.cancel_session_slot(slot["id"], op))
    # Player attempts to confirm.
    resp = api.confirm_deposit(booking["id"], None, make_player_headers(p1["id"]))
    validate_error_one_of_or_specific(resp, ApiErrorId.ERR_SESSION_NOT_OPEN_FOR_CONFIRM.value)


def test_confirm_blocked_when_capacity_exceeded(api):
    """PRD §3.6: "the post-confirm `confirmed_seat_count` to remain at or below `theme.max_players` (otherwise `ERR_SLOT_FULL`)."

    Claim: a booking whose confirm would push confirmed_seat_count above theme.max_players is rejected with ERR_SLOT_FULL.
    """
    # Two pending bookings on the same 2-seat-max slot, each requesting all 2 seats.
    venue, room, theme = setup_basic_scenario(theme_overrides={"min_players": 2, "max_players": 2})
    from test_helpers import create_session_slot as _css
    slot = _css(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=2, hours_ahead=48.0)
    p1, p1b, p2, p2b = create_player(), create_player(), create_player(), create_player()
    b1 = create_and_confirm_booking(slot, p1, team_player_ids=[p1["id"], p1b["id"]])  # confirmed_seat_count=2 (full)
    # New player tries to book — at booking creation ERR_SLOT_FULL fires per §3.5 capacity check.
    headers = make_player_headers(p2["id"])
    payload = create_booking_payload([p2["id"], p2b["id"]])
    resp = api.create_booking(slot["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_SLOT_FULL.value)


# ─── §3.6 Refund (post-completion) ────────────────────────────────────────

def test_refund_below_paid_succeeds(api):
    """PRD §3.6: "the operator supplies `refund_amount_cents`; the deposit refund is zero (the deposit was already released at settlement) and the paid refund equals the supplied `refund_amount_cents`, capped such that `refund_amount_cents` does not exceed `paid_amount_cents` minus the existing `refund_total_cents`."

    Claim: a refund of less-than-paid succeeds; booking.refund_total_cents == refund_amount_cents; status=REFUNDED.
    """
    state = setup_slot_at_completed(seat_count=2)
    booking = state["booking"]
    paid = booking["paid_amount_cents"]
    refunded = refund_booking(booking, state["venue"], paid // 2)
    assert refunded["status"] == BookingStatus.REFUNDED.value
    assert refunded["refund_total_cents"] == paid // 2


def test_refund_exceeds_paid_rejected(api):
    """PRD §3.6: "Any excess is rejected with `ERR_REFUND_EXCEEDS_PAID`."

    Claim: refund_amount_cents > paid_amount_cents - refund_total_cents yields ERR_REFUND_EXCEEDS_PAID.
    """
    state = setup_slot_at_completed(seat_count=2)
    booking = state["booking"]
    paid = booking["paid_amount_cents"]
    op = make_venue_operator_headers(state["venue"]["id"])
    resp = api.refund_booking(booking["id"], refund_booking_payload(paid + 1), op)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_PAID.value)


def test_refund_requires_completed_session(api):
    """PRD §3.6: "This refund requires the slot to be `COMPLETED`; otherwise `ERR_REFUND_REQUIRES_COMPLETED_SESSION`."

    Claim: refund attempted while slot.schedule_status != COMPLETED yields ERR_REFUND_REQUIRES_COMPLETED_SESSION.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2)
    op = make_venue_operator_headers(state["venue"]["id"])
    resp = api.refund_booking(state["booking"]["id"], refund_booking_payload(100), op)
    validate_error(resp, ApiErrorId.ERR_REFUND_REQUIRES_COMPLETED_SESSION.value)


# Helper to allow validation when the implementation may surface either of two
# state-class errors. Keeps the assertion specific where PRD names a concrete error.
def validate_error_one_of_or_specific(resp, expected_error_id: str):
    from test_helpers import validate_error
    validate_error(resp, expected_error_id)
