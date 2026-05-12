"""Venue creation, update, suspend/resume/close, and revenue-split validation."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BookingStatus,
    SlotScheduleStatus,
    TEST_USERS,
    VenueStatus,
    advance_clock_to,
    assert_venue,
    assert_venue_revenue_split_sum,
    cancel_slot,
    create_and_confirm_booking,
    create_player,
    create_room,
    create_session_slot,
    create_venue,
    create_venue_payload,
    get_booking,
    get_session_slot,
    make_venue_operator_headers,
    setup_basic_scenario,
    setup_slot_with_confirmed_booking,
    validate_error,
    validate_success,
)


# ─── Venue creation ───────────────────────────────────────────────────────

def test_create_venue_returns_active_status(api):
    """PRD §3.1: "A new venue starts in `ACTIVE`."

    Claim: a freshly-created venue has status == ACTIVE.
    """
    resp = api.create_venue(create_venue_payload(), TEST_USERS["platform_admin_headers"])
    venue = validate_success(resp, expected_status=201)
    assert_venue(venue)
    assert venue["status"] == VenueStatus.ACTIVE.value


# ─── §2.10 / §3.1 Revenue split sum ───────────────────────────────────────

def test_revenue_split_must_sum_to_10000(api):
    """PRD §2.10: "the four base bps fields on each affected venue must sum to exactly 10000; any other sum (after applying applicable per-theme or per-staff overrides) yields `ERR_REVENUE_SPLIT_INVALID`."

    Claim: creating a venue whose four bps sum != 10000 yields ERR_REVENUE_SPLIT_INVALID.
    """
    payload = create_venue_payload(
        revenue_share_bps=4500,
        author_royalty_bps=2000,
        host_commission_bps=1500,
        platform_fee_bps=1500,  # sum = 9500
    )
    resp = api.create_venue(payload, TEST_USERS["platform_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_REVENUE_SPLIT_INVALID.value)


def test_revenue_split_at_10000_succeeds(api):
    """PRD §3.1: "if it is not exactly 10000, the request is rejected with `ERR_REVENUE_SPLIT_INVALID`."

    Claim: bps sum at exactly 10000 succeeds.
    """
    payload = create_venue_payload(
        revenue_share_bps=4500,
        author_royalty_bps=2000,
        host_commission_bps=1500,
        platform_fee_bps=2000,
    )
    venue = validate_success(api.create_venue(payload, TEST_USERS["platform_admin_headers"]), expected_status=201)
    assert_venue_revenue_split_sum(venue)


def test_revenue_split_revalidated_on_patch(api):
    """PRD §3.1: "When a `PlatformAdmin` later updates the venue with new `business_hours`, `deposit_policy_cents`, or any of the four bps fields (each optional and individually patchable), the sum is re-validated."

    Claim: a patch that breaks the sum yields ERR_REVENUE_SPLIT_INVALID.
    """
    admin = TEST_USERS["platform_admin_headers"]
    venue = create_venue()
    resp = api.update_venue(venue["id"], {"platform_fee_bps": 1000}, admin)  # would sum to 9000
    validate_error(resp, ApiErrorId.ERR_REVENUE_SPLIT_INVALID.value)


# ─── §3.1 Suspend cascade ────────────────────────────────────────────────

def test_suspend_venue_cascades_slots_and_bookings_to_cancelled(api):
    """PRD §3.1: "every `SessionSlot` in that venue with `schedule_status` equal to `SCHEDULED` is auto-cancelled by cascade, every `Booking` under those slots in `PENDING_DEPOSIT` or `CONFIRMED` is cascaded to `CANCELLED` with `cancellation_initiator` set to `VENUE`, and deposits are fully refunded under the venue-or-system policy described in §3.6."

    Claim: venue suspend cascades SCHEDULED slot → CANCELLED, Booking → CANCELLED with cancellation_initiator=VENUE.
    """
    admin = TEST_USERS["platform_admin_headers"]
    state = setup_slot_with_confirmed_booking(seat_count=2)
    venue, slot, booking = state["venue"], state["slot"], state["booking"]

    suspended = validate_success(api.suspend_venue(venue["id"], admin))
    assert suspended["status"] == VenueStatus.SUSPENDED.value

    refreshed_slot = get_session_slot(slot["id"])
    refreshed_booking = get_booking(booking["id"])
    assert refreshed_slot["schedule_status"] == SlotScheduleStatus.CANCELLED.value
    assert refreshed_booking["status"] == BookingStatus.CANCELLED.value
    assert refreshed_booking["cancellation_initiator"] == "VENUE"


def test_suspend_full_refund_on_cascade(api):
    """PRD §3.6: "For a venue-initiated or system-initiated cancellation — `cancellation_initiator` of `VENUE` or `SYSTEM_MATCH_FAIL` — the refund is always the full deposit plus the full paid amount, regardless of lead minutes."

    Claim: suspended-venue cascade fully refunds (deposit + paid).
    """
    admin = TEST_USERS["platform_admin_headers"]
    state = setup_slot_with_confirmed_booking(seat_count=2)
    booking = state["booking"]
    paid = booking["paid_amount_cents"]
    deposit = booking["deposit_held_cents"]

    validate_success(api.suspend_venue(state["venue"]["id"], admin))
    refreshed = get_booking(booking["id"])
    assert refreshed["refund_total_cents"] == paid + deposit


# ─── §3.1 Resume ──────────────────────────────────────────────────────────

def test_resume_venue_returns_active(api):
    """PRD §3.1: "Resuming a venue moves it from `SUSPENDED` back to `ACTIVE` with no cascading effect."

    Claim: resume after suspend leaves Venue.status==ACTIVE.
    """
    admin = TEST_USERS["platform_admin_headers"]
    venue = create_venue()
    validate_success(api.suspend_venue(venue["id"], admin))
    resumed = validate_success(api.resume_venue(venue["id"], admin))
    assert resumed["status"] == VenueStatus.ACTIVE.value


# ─── §3.1 Close gating ────────────────────────────────────────────────────

def test_close_blocked_with_open_sessions(api):
    """PRD §3.1: "Closing a venue is terminal and may be initiated from either `ACTIVE` or `SUSPENDED`, but only when no `SessionSlot` in the venue still has `schedule_status` of `SCHEDULED` or `LIVE`; otherwise the request is rejected with `ERR_VENUE_HAS_OPEN_SESSIONS`."

    Claim: a venue with a SCHEDULED slot cannot be closed.
    """
    admin = TEST_USERS["platform_admin_headers"]
    venue, room, theme = setup_basic_scenario()
    create_session_slot(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"], hours_ahead=48.0)
    resp = api.close_venue(venue["id"], admin)
    validate_error(resp, ApiErrorId.ERR_VENUE_HAS_OPEN_SESSIONS.value)


def test_close_succeeds_with_no_open_sessions(api):
    """PRD §3.1: "Closing a venue is terminal and may be initiated from either `ACTIVE` or `SUSPENDED`."

    Claim: closing a venue without open slots succeeds and Venue.status==CLOSED.
    """
    admin = TEST_USERS["platform_admin_headers"]
    venue = create_venue()
    closed = validate_success(api.close_venue(venue["id"], admin))
    assert closed["status"] == VenueStatus.CLOSED.value


# ─── §2.9 / §3.1 ERR_VENUE_NOT_ACTIVE on mutations under non-active venue ─

def test_create_room_under_suspended_venue_rejected(api):
    """PRD §3.1: "Any mutation under a venue not in `ACTIVE` (creating rooms, maintenance windows, slots, or bookings) is rejected with `ERR_VENUE_NOT_ACTIVE`."

    Claim: creating a room under a SUSPENDED venue yields ERR_VENUE_NOT_ACTIVE.
    """
    admin = TEST_USERS["platform_admin_headers"]
    venue = create_venue()
    validate_success(api.suspend_venue(venue["id"], admin))
    operator = make_venue_operator_headers(venue["id"])
    resp = api.create_room(venue["id"], {"name": "test-room", "capacity_min": 2, "capacity_max": 4, "turnover_minutes": 30}, operator)
    validate_error(resp, ApiErrorId.ERR_VENUE_NOT_ACTIVE.value)


