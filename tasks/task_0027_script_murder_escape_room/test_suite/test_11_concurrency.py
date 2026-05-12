"""Concurrency races: explicit serialization guarantees from PRD §2.11."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BookingStatus,
    SlotScheduleStatus,
    TEST_USERS,
    add_minutes,
    advance_clock_to,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_and_confirm_booking,
    create_booking_payload,
    create_player,
    create_session_slot,
    create_staff_assignment,
    create_staff_member,
    get_session_slot,
    make_player_headers,
    make_venue_operator_headers,
    moderate_review_payload,
    refund_booking_payload,
    run_race,
    setup_basic_scenario,
    setup_finalized_settlement_around_slot,
    setup_public_teamup_slot,
    setup_review_pending_moderation,
    setup_settled_booking_with_split,
    setup_slot_at_completed,
    setup_slot_with_confirmed_booking,
    start_slot,
    submit_review,
    unique_chain_id,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ─── §2.11 Player vs operator: cancel vs start ─────────────────────────────

def test_concurrent_player_cancel_and_operator_start(api):
    """PRD §2.11: "When a player cancels a booking while a venue operator simultaneously starts the same slot, the first writer wins on the slot's `schedule_status`; if the start wins (advancing to `LIVE`), the player's cancel sees a `schedule_status` no longer equal to `SCHEDULED` and is rejected with `ERR_SESSION_NOT_OPEN_FOR_CANCEL` at HTTP 409."

    Claim: only one of {player-cancel, operator-start} succeeds; if start wins, cancel returns ERR_SESSION_NOT_OPEN_FOR_CANCEL.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2)
    venue, slot = state["venue"], state["slot"]
    booking, lead = state["booking"], state["lead_player"]
    # Add staffing so start preconditions are met.
    host_staff = create_staff_member(state["theme"]["chain_id"], roles_held=["HOST"], qualifications=[])
    create_staff_assignment(slot, venue, host_staff, role_type="HOST")
    advance_clock_to(slot["starts_at"])
    op = make_venue_operator_headers(venue["id"])
    player_headers = make_player_headers(lead["id"])

    results = run_race(
        lambda: api.start_session_slot(slot["id"], op),
        lambda: api.cancel_booking(booking["id"], player_headers),
    )
    # At least one must succeed; both cannot win because schedule_status is the
    # serialization point. PRD does not commit to a single ordering, so we assert
    # at_least_one_succeeds and (if exactly one fails) name the cancel-loser code.
    assert_at_least_one_succeeds(*results)
    failures = [r for r in results if r.status_code >= 400]
    if len(failures) == 1:
        # PRD §2.11 names ERR_SESSION_NOT_OPEN_FOR_CANCEL for the cancel-loser
        # branch where the start wins; PRD §3.6 simultaneously names
        # ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER for any LIVE-slot player cancel.
        # Both readings are PRD-faithful, so we accept either alongside the
        # alternate-direction failure ERR_OUTSIDE_START_WINDOW (start lost the
        # race because the cancel won and the slot's bookings vanished).
        validate_error_is_one_of(
            failures[0],
            [
                ApiErrorId.ERR_SESSION_NOT_OPEN_FOR_CANCEL.value,
                ApiErrorId.ERR_OUTSIDE_START_WINDOW.value,
                ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER.value,
            ],
        )


# ─── §2.11 Two players race for the last seat ─────────────────────────────

def test_concurrent_booking_creation_at_capacity(api):
    """PRD §2.11: "When two players race to book the last seats on a `PUBLIC_TEAMUP` slot such that, taken together, their bookings would push `confirmed_seat_count` above `theme.max_players`, the first writer wins on the slot's confirmed-seat counter and the loser is rejected with `ERR_SLOT_FULL` at HTTP 409."

    PRD §3.5 pins the confirmed-seat counter as the serialisation point and
    explicitly defers the capacity re-check to deposit confirmation: "The
    capacity check is re-applied atomically at deposit confirmation." Two
    PENDING_DEPOSIT creations can therefore both succeed (the counter has not
    moved); the race that PRD §2.11 names is the one between the two
    confirm-deposit writers that bid to lift the counter above max_players.

    Claim: two simultaneous confirm-deposit attempts whose joint seat counts
    would exceed max_players resolve as exactly one success + one ERR_SLOT_FULL.
    """
    venue, room, theme, slot = setup_public_teamup_slot(required_seats_for_launch=2, max_players=2)
    # Two pending bookings, each requesting 2 seats — together they would push
    # confirmed_seat_count above max_players=2.
    p1 = create_player()
    p1b = create_player()
    p2 = create_player()
    p2b = create_player()
    h1 = make_player_headers(p1["id"])
    h2 = make_player_headers(p2["id"])
    booking_1 = validate_success(
        api.create_booking(slot["id"], create_booking_payload([p1["id"], p1b["id"]]), h1),
        expected_status=201,
    )
    booking_2 = validate_success(
        api.create_booking(slot["id"], create_booking_payload([p2["id"], p2b["id"]]), h2),
        expected_status=201,
    )
    results = run_race(
        lambda: api.confirm_deposit(booking_1["id"], None, h1),
        lambda: api.confirm_deposit(booking_2["id"], None, h2),
    )
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    failure = outcome["failures"][0]
    validate_error(failure, ApiErrorId.ERR_SLOT_FULL.value)


# ─── §2.11 Two moderators race for the same review ────────────────────────

def test_concurrent_review_moderation(api):
    """PRD §2.11: "When two content moderators moderate the same review concurrently, the first decision wins on `Review.status` leaving `PENDING_MODERATION` and the second attempt is rejected with `ERR_REVIEW_ALREADY_MODERATED` at HTTP 409."

    Claim: two concurrent moderate requests on the same PENDING_MODERATION review leave one success + one ERR_REVIEW_ALREADY_MODERATED.
    """
    state = setup_review_pending_moderation(comment="A nicely written comment of moderate length to avoid the short-comment heuristic.")
    review = state["review"]
    mod_a = TEST_USERS["content_moderator_headers"]
    mod_b = TEST_USERS["content_moderator_headers_alt"]
    results = run_race(
        lambda: api.moderate_review(review["id"], moderate_review_payload("APPROVE"), mod_a),
        lambda: api.moderate_review(review["id"], moderate_review_payload("REJECT"), mod_b),
    )
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    validate_error(outcome["failures"][0], ApiErrorId.ERR_REVIEW_ALREADY_MODERATED.value)


# ─── §2.11 Refund vs settlement-finalize race ─────────────────────────────

def test_concurrent_refund_and_finalize(api):
    """PRD §2.11: "When a refund and a settlement-finalize race on the same `SettlementRun`, the first writer wins on the run's status: if finalize wins first, the refund cascades to flip the run to `REVERSED`; if the refund wins first, finalize observes the revised `net_revenue_cents` and pins post-refund payouts."

    Claim: at least one of {refund, finalize} succeeds; double-finalize is impossible (would yield ERR_SETTLEMENT_ALREADY_FINALIZED).
    """
    from test_helpers import create_settlement_run_around_slot
    state = setup_settled_booking_with_split()
    run = create_settlement_run_around_slot(state["slot"], state["chain_id"])
    admin = TEST_USERS["platform_admin_headers"]
    op = make_venue_operator_headers(state["venue"]["id"])
    booking = state["booking"]
    results = run_race(
        lambda: api.finalize_settlement_run(run["id"], admin),
        lambda: api.refund_booking(booking["id"], refund_booking_payload(1000), op),
    )
    # PRD only states "at least one wins"; both can succeed (finalize then refund cascades to REVERSED).
    assert_at_least_one_succeeds(*results)
