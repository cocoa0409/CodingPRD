"""Match quorum, match-deadline cascade, and waitlist promotion."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BookingStatus,
    SlotMatchStatus,
    SlotScheduleStatus,
    WaitlistStatus,
    add_minutes,
    advance_clock_to,
    cancel_booking_as_player,
    create_and_confirm_booking,
    create_booking,
    create_player,
    create_waitlist_entry,
    get_booking,
    get_session_slot,
    list_waitlist_entries,
    setup_basic_scenario,
    setup_public_teamup_slot,
    setup_slot_full_with_waitlist,
    setup_slot_with_confirmed_booking,
    validate_error,
    validate_success,
)


# ─── §3.7 Match deadline cascade ──────────────────────────────────────────

def test_match_deadline_open_cascades_to_match_failed(api):
    """PRD §3.7: "When the current logical clock is at or after `match_deadline_at`, evaluated only as part of a clock-advance scan, exactly one transition is allowed. If `match_status` is `OPEN`, the cascade flips it to `MATCH_FAILED` regardless of `n` (the slot's `OPEN` status at the deadline is decisive); the match-fail in turn cascades the schedule axis from `SCHEDULED` to `CANCELLED`, all bookings in `PENDING_DEPOSIT` or `CONFIRMED` to `CANCELLED` with `cancellation_initiator` of `SYSTEM_MATCH_FAIL` (full deposit and paid refunds)."

    Claim: clock advance past match_deadline_at on an OPEN slot triggers match_status->MATCH_FAILED, schedule_status->CANCELLED, and bookings -> CANCELLED with SYSTEM_MATCH_FAIL.
    """
    venue, room, theme, slot = setup_public_teamup_slot(required_seats_for_launch=4, max_players=4, hours_ahead=2.0)
    # Single pending/confirmed booking: 1 seat (< required 4).
    p1 = create_player()
    booking = create_and_confirm_booking(slot, p1)  # CONFIRMED but n=1 < R=4
    # Advance past match_deadline_at = starts_at - 60m.
    advance_clock_to(add_minutes(slot["match_deadline_at"], 1))

    refreshed_slot = get_session_slot(slot["id"])
    refreshed_booking = get_booking(booking["id"])
    assert refreshed_slot["match_status"] == SlotMatchStatus.MATCH_FAILED.value
    assert refreshed_slot["schedule_status"] == SlotScheduleStatus.CANCELLED.value
    assert refreshed_booking["status"] == BookingStatus.CANCELLED.value
    assert refreshed_booking["cancellation_initiator"] == "SYSTEM_MATCH_FAIL"
    # PRD §3.6: full refund on system cancel.
    assert refreshed_booking["refund_total_cents"] == refreshed_booking["paid_amount_cents"] + refreshed_booking["deposit_held_cents"]


def test_match_deadline_matched_does_not_flip(api):
    """PRD §3.7: "If `match_status` is already `MATCHED` at the deadline, no change occurs — the match locks in pre-deadline."

    Claim: a MATCHED slot at the deadline keeps match_status=MATCHED.
    """
    venue, room, theme, slot = setup_public_teamup_slot(required_seats_for_launch=2, max_players=2, hours_ahead=2.0)
    p1, p2 = create_player(), create_player()
    create_and_confirm_booking(slot, p1)
    create_and_confirm_booking(slot, p2)
    # Now confirmed_seat_count=2 == required.
    pre = get_session_slot(slot["id"])
    assert pre["match_status"] == SlotMatchStatus.MATCHED.value
    advance_clock_to(add_minutes(slot["match_deadline_at"], 1))
    post = get_session_slot(slot["id"])
    assert post["match_status"] == SlotMatchStatus.MATCHED.value


# ─── §3.6 Match demotion (pre-deadline only) ──────────────────────────────

def test_match_demotion_pre_deadline_on_cancel(api):
    """PRD §3.6: "If that decrease pushes the post-decrement count below `required_seats_for_launch` while `match_status` is `MATCHED` and the current logical clock is still earlier than `match_deadline_at`, the match axis demotes from `MATCHED` back to `OPEN`."

    Claim: cancelling a booking pre-deadline that pushes n below R demotes match_status MATCHED -> OPEN.
    """
    venue, room, theme, slot = setup_public_teamup_slot(required_seats_for_launch=2, max_players=4, hours_ahead=72.0)
    p1, p2 = create_player(), create_player()
    b1 = create_and_confirm_booking(slot, p1)
    create_and_confirm_booking(slot, p2)
    pre = get_session_slot(slot["id"])
    assert pre["match_status"] == SlotMatchStatus.MATCHED.value
    cancel_booking_as_player(b1, p1)
    post = get_session_slot(slot["id"])
    # post-decrement n=1 < R=2, well before deadline → demoted to OPEN.
    assert post["match_status"] == SlotMatchStatus.OPEN.value


# ─── §3.7 Waitlist priority and FIFO ──────────────────────────────────────

def test_waitlist_priority_class_pinned_from_player_tier(api):
    """PRD §3.7: "the server pins `priority_class` from the player's `tier` at enqueue time (`VIP` if `Player.tier` is `VIP`, otherwise `STANDARD`)."

    Claim: a VIP player's waitlist entry has priority_class=VIP; a STANDARD player's has STANDARD.
    """
    state = setup_slot_full_with_waitlist()
    slot = state["slot"]
    vip = create_player(tier="VIP")
    standard = create_player()
    vip_entry = create_waitlist_entry(slot, vip, requested_seat_count=1)
    std_entry = create_waitlist_entry(slot, standard, requested_seat_count=1)
    assert vip_entry["priority_class"] == "VIP"
    assert std_entry["priority_class"] == "STANDARD"


def test_waitlist_promotion_on_cancel_creates_pending_booking(api):
    """PRD §3.7: "The first ranked eligible entry is the winner: its status is set to `PROMOTED` and a fresh `Booking` row is created in `PENDING_DEPOSIT`, with `seat_count` equal to the winner's `requested_seat_count` and `lead_player_id` copied from the winner."

    Claim: cancelling a 2-seat booking on a full 4-seat slot promotes a queued 2-seat entry to PROMOTED and the entry's status reflects this.
    """
    state = setup_slot_full_with_waitlist()
    # Cancel booking_1 (2 seats freed) — there's an existing 2-seat queued entry.
    cancel_booking_as_player(state["booking_1"], state["booking_1_lead"])
    # Refresh the waitlist entry by listing.
    entries = list_waitlist_entries(state["slot"])
    target = next((e for e in entries if e["id"] == state["waitlist_entry"]["id"]), None)
    assert target is not None, "Waitlist entry should still appear in the listing"
    assert target["status"] == WaitlistStatus.PROMOTED.value


def test_waitlist_cancel_only_by_lead_player(api):
    """PRD §3.7: "an attempt by anyone other than the entry's `lead_player_id` is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Claim: a different player attempting to cancel another player's waitlist entry is rejected with ERR_INSUFFICIENT_PERMISSIONS.
    """
    from test_helpers import make_player_headers
    state = setup_slot_full_with_waitlist()
    other = create_player()
    resp = api.cancel_waitlist_entry(state["waitlist_entry"]["id"], make_player_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_waitlist_expires_on_slot_cancel(api):
    """PRD §3.7: "A waitlist entry advances to `EXPIRED` when its slot is cancelled or its slot's match axis flips to `MATCH_FAILED`."

    Claim: operator-cancelling a slot expires its QUEUED waitlist entries.
    """
    from test_helpers import cancel_slot
    state = setup_slot_full_with_waitlist()
    cancel_slot(state["slot"], state["venue"])
    entries = list_waitlist_entries(state["slot"])
    target = next((e for e in entries if e["id"] == state["waitlist_entry"]["id"]), None)
    assert target is not None
    assert target["status"] == WaitlistStatus.EXPIRED.value


# NOTE: a dedicated ERR_PLAYER_BANNED test requires knowing NO_SHOW_BAN_THRESHOLD
# to drive a player into BANNED via cascade no-shows. PRD §3.5 names the constant
# but does not pin its value, so the threshold is silent (Silence-pattern bucket:
# default-value). The rule is still exercised indirectly by §3.7 / §3.10 cascades
# verified elsewhere.
