"""Session slot creation, two-axis state machine, start/complete/cancel."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BookingStatus,
    SlotMatchStatus,
    SlotScheduleStatus,
    add_minutes,
    advance_clock_to,
    assert_session_slot,
    cancel_slot,
    complete_slot,
    create_session_slot,
    drive_slot_to_completed,
    get_booking,
    get_player,
    get_session_slot,
    make_venue_operator_headers,
    setup_basic_scenario,
    setup_slot_at_completed,
    setup_slot_with_confirmed_booking,
    start_slot,
    validate_error,
    validate_success,
)


# ─── Slot creation defaults ────────────────────────────────────────────────

def test_create_slot_pins_ends_at_and_match_deadline(api):
    """PRD §3.3: "`ends_at` is computed as `starts_at` plus the theme's `duration_minutes` and is immutable."
    PRD §3.3: "The `match_deadline_at` is computed at slot creation as `starts_at` minus 60 minutes and stored on the slot."

    Claim: ends_at == starts_at + duration_minutes; match_deadline_at == starts_at - 60m.
    """
    venue, room, theme = setup_basic_scenario(theme_overrides={"duration_minutes": 90})
    starts_at = "2030-06-01T12:00:00.000Z"
    slot = create_session_slot(venue, room, theme, starts_at=starts_at, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    assert_session_slot(slot)
    assert slot["ends_at"] == add_minutes(starts_at, 90)
    assert slot["match_deadline_at"] == add_minutes(starts_at, -60)


def test_create_slot_initial_state(api):
    """PRD §3.3: "The slot starts with `schedule_status` of `SCHEDULED` and `match_status` of `OPEN`, with `confirmed_seat_count`, `gross_revenue_cents`, and `net_revenue_cents` initialised to 0."

    Claim: schedule_status=SCHEDULED, match_status=OPEN, confirmed_seat_count=0.
    """
    venue, room, theme = setup_basic_scenario()
    slot = create_session_slot(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    assert slot["schedule_status"] == SlotScheduleStatus.SCHEDULED.value
    assert slot["match_status"] == SlotMatchStatus.OPEN.value
    assert slot["confirmed_seat_count"] == 0


def test_required_seats_for_launch_within_theme_bounds(api):
    """PRD §3.3: "The `required_seats_for_launch` must satisfy the theme's `min_players` lower bound and `max_players` upper bound — that is, it must be at least the theme's minimum and at most the theme's maximum."

    Claim: required_seats_for_launch < theme.min_players is rejected with ERR_INVALID_REQUEST.
    """
    venue, room, theme = setup_basic_scenario(theme_overrides={"min_players": 3, "max_players": 5})
    headers = make_venue_operator_headers(venue["id"])
    from test_helpers import create_session_slot_payload, future_iso
    payload = create_session_slot_payload(theme["id"], future_iso(48), "PRIVATE_ONLY", 2)
    resp = api.create_session_slot(venue["id"], room["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_required_seats_above_max_rejected(api):
    """PRD §3.3: "it must be at least the theme's minimum and at most the theme's maximum."

    Claim: required_seats_for_launch > theme.max_players is rejected with ERR_INVALID_REQUEST.
    """
    venue, room, theme = setup_basic_scenario(theme_overrides={"min_players": 2, "max_players": 4})
    headers = make_venue_operator_headers(venue["id"])
    from test_helpers import create_session_slot_payload, future_iso
    payload = create_session_slot_payload(theme["id"], future_iso(48), "PRIVATE_ONLY", 5)
    resp = api.create_session_slot(venue["id"], room["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_slot_theme_room_incompatible(api):
    """PRD §2.9: "Cross-entity referential integrity comes sixth, producing `ERR_THEME_ROOM_INCOMPATIBLE`."
    PRD §3.2: "a `compatible_room_ids` array (which must be non-empty and may only contain room ids belonging to the same `chain_id`)."

    Claim: creating a slot against a room not listed in theme.compatible_room_ids yields ERR_THEME_ROOM_INCOMPATIBLE.
    """
    venue, room, theme = setup_basic_scenario()
    # Make a second room NOT listed in theme.compatible_room_ids.
    from test_helpers import create_room as _cr, create_session_slot_payload, future_iso
    other_room = _cr(venue, name="other-room", capacity_min=2, capacity_max=4)
    headers = make_venue_operator_headers(venue["id"])
    payload = create_session_slot_payload(theme["id"], future_iso(48), "PRIVATE_ONLY", theme["min_players"])
    resp = api.create_session_slot(venue["id"], other_room["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_THEME_ROOM_INCOMPATIBLE.value)


# ─── §3.3 Cross-axis coupling ─────────────────────────────────────────────

def test_start_blocked_when_match_status_open(api):
    """PRD §3.3: "If a `VenueOperator` tries to start a slot whose match axis is still `OPEN`, the request is rejected with `ERR_SESSION_NOT_MATCHED`."

    Claim: starting a slot with match_status=OPEN yields ERR_SESSION_NOT_MATCHED.
    """
    venue, room, theme = setup_basic_scenario()
    slot = create_session_slot(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    headers = make_venue_operator_headers(venue["id"])
    advance_clock_to(slot["starts_at"])
    resp = api.start_session_slot(slot["id"], headers)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_MATCHED.value)


def test_match_status_advances_to_matched_on_quorum(api):
    """PRD §3.6: "if the post-increment count meets or exceeds the slot's `required_seats_for_launch` while `match_status` is `OPEN`, the match axis cascades to `MATCHED`."

    Claim: confirming enough seats for quorum cascades match_status -> MATCHED.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2)
    refreshed_slot = get_session_slot(state["slot"]["id"])
    assert refreshed_slot["match_status"] == SlotMatchStatus.MATCHED.value


# ─── §3.3 Start preconditions ─────────────────────────────────────────────

def test_start_outside_window_rejected(api):
    """PRD §3.3: "Starting a slot — moving the schedule axis from `SCHEDULED` to `LIVE` — additionally requires that the current logical clock falls within the start window... outside that window the request is rejected with `ERR_OUTSIDE_START_WINDOW`."

    Claim: attempting to start far away from slot.starts_at yields ERR_OUTSIDE_START_WINDOW.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2, hours_ahead=72.0)
    headers = make_venue_operator_headers(state["venue"]["id"])
    # Don't advance the clock — current clock is 3 days before slot starts.
    resp = api.start_session_slot(state["slot"]["id"], headers)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_START_WINDOW.value)


def test_start_succeeds_with_match_and_window(api):
    """PRD §3.3: "Starting a slot — moving the schedule axis from `SCHEDULED` to `LIVE`."

    Claim: a MATCHED slot inside the start window advances schedule_status to LIVE.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2)
    venue, slot = state["venue"], state["slot"]
    # Need staffing too if theme requires NPC; default theme has no NPC requirement.
    from test_helpers import create_staff_assignment, create_staff_member
    host_staff = create_staff_member(state["theme"]["chain_id"], roles_held=["HOST"], qualifications=[])
    create_staff_assignment(slot, venue, host_staff, role_type="HOST")
    advance_clock_to(slot["starts_at"])
    started = start_slot(slot, venue)
    assert started["schedule_status"] == SlotScheduleStatus.LIVE.value


# ─── §3.3 Complete cascade ─────────────────────────────────────────────────

def test_complete_marks_no_show_on_unchecked_in_booking(api):
    """PRD §3.3: "Every `Booking` still in `CONFIRMED` at the moment of completion — that is, players who confirmed but never checked in — cascades to `CANCELLED` with `cancellation_initiator` set to `NO_SHOW`; their deposits are forfeited to the venue under the no-show variant of the cancellation-refund policy, and the offending players have their `no_show_strikes` counter incremented."

    Claim: a CONFIRMED-not-CHECKED-IN booking at slot.complete becomes CANCELLED with NO_SHOW; deposit forfeited (refund_total stays 0); player.no_show_strikes incremented.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2)
    venue, slot = state["venue"], state["slot"]
    booking = state["booking"]
    lead = state["lead_player"]

    # Add staffing, then start, but DO NOT check in.
    from test_helpers import create_staff_assignment, create_staff_member
    host_staff = create_staff_member(state["theme"]["chain_id"], roles_held=["HOST"], qualifications=[])
    create_staff_assignment(slot, venue, host_staff, role_type="HOST")
    advance_clock_to(slot["starts_at"])
    start_slot(slot, venue)
    # Skip check-in.
    advance_clock_to(add_minutes(slot["ends_at"], 1))
    complete_slot(slot, venue)

    refreshed = get_booking(booking["id"])
    assert refreshed["status"] == BookingStatus.CANCELLED.value
    assert refreshed["cancellation_initiator"] == "NO_SHOW"
    assert refreshed["refund_total_cents"] == 0  # deposit forfeited, paid forfeited

    refreshed_player = get_player(lead["id"])
    assert refreshed_player["no_show_strikes"] >= 1


def test_complete_settles_checked_in_booking(api):
    """PRD §3.3: "every `Booking` in `CHECKED_IN` cascades to `SETTLED` (the per-seat `paid_amount_cents` is recognised as revenue and the deposit hold is released back to the player; the deposit release is **not** counted toward `refund_total_cents`)."

    Claim: completing a slot with a CHECKED_IN booking advances it to SETTLED with refund_total_cents unchanged at 0.
    """
    state = setup_slot_at_completed(seat_count=2)
    booking = state["booking"]
    assert booking["status"] == BookingStatus.SETTLED.value
    assert booking["refund_total_cents"] == 0


# ─── §3.3 Cancel slot cascade ─────────────────────────────────────────────

def test_operator_cancel_slot_cascades_bookings_and_full_refund(api):
    """PRD §3.3: "Every `Booking` in `PENDING_DEPOSIT` or `CONFIRMED` under the slot cascades to `CANCELLED` with `cancellation_initiator` of `VENUE` (when the trigger is operator or venue-suspension)."
    PRD §3.6: "For a venue-initiated or system-initiated cancellation — `cancellation_initiator` of `VENUE` or `SYSTEM_MATCH_FAIL` — the refund is always the full deposit plus the full paid amount, regardless of lead minutes."

    Claim: operator-cancelling a slot CANCELLEDs its CONFIRMED booking with cancellation_initiator=VENUE and full refund.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2)
    cancel_slot(state["slot"], state["venue"])
    refreshed = get_booking(state["booking"]["id"])
    assert refreshed["status"] == BookingStatus.CANCELLED.value
    assert refreshed["cancellation_initiator"] == "VENUE"
    assert refreshed["refund_total_cents"] == refreshed["paid_amount_cents"] + refreshed["deposit_held_cents"]
