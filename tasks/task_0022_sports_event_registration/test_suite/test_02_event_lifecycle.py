"""Event creation, opening, and lifecycle transitions
(PRD §3.1, §3.2, §3.6, §2.5, §2.11)."""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    add_minutes,
    add_hours,
    assert_event,
    cancel_event,
    create_event,
    create_event_payload,
    DEFAULT_T0,
    event_drawn,
    event_in_progress,
    event_open_for_registration,
    open_event,
    register_participant,
    register_n_distinct_participants,
    list_participants,
    close_registration,
    draw_event,
    list_matches,
    list_sync_events,
    find_sync_events,
    validate_error,
    validate_success,
)


# ===========================================================================
# 3.1 — Event creation in DRAFT
# ===========================================================================
class TestEventCreation:
    def test_create_event_returns_draft(self, api, organizer_headers):
        """PRD §3.1: 'On creation the event sits in DRAFT, with derived
        fields status, registered_count, prize_paid_total_cents, and
        posture initialized to DRAFT, 0, 0, and CLEAN respectively.'"""
        res = api.create_event(create_event_payload(), organizer_headers)
        event = validate_success(res, expected_status=201)
        assert_event(event)
        assert event["status"] == "DRAFT"
        assert event["registered_count"] == 0
        assert event["prize_paid_total_cents"] == 0
        assert event["posture"] == "CLEAN"

    @pytest.mark.parametrize("bad_pct", [-0.01, 50.01, 51, -1, 100])
    def test_tax_pct_outside_range_rejected(
        self, api, organizer_headers, bad_pct
    ):
        """PRD §2.6: 'The `tax_withholding_pct` field on `Event` is a
        decimal number with exactly two decimal places, restricted to
        the inclusive range zero through fifty; values outside that
        range are rejected with `ERR_TAX_OUT_OF_RANGE`.'"""
        payload = create_event_payload(tax_withholding_pct=bad_pct)
        res = api.create_event(payload, organizer_headers)
        validate_error(res, "ERR_TAX_OUT_OF_RANGE")

    @pytest.mark.parametrize("ok_pct", [0.0, 25.0, 50.0])
    def test_tax_pct_inside_range_accepted(
        self, api, organizer_headers, ok_pct
    ):
        """PRD §2.6: 'restricted to the inclusive range zero through fifty.'"""
        payload = create_event_payload(tax_withholding_pct=ok_pct)
        res = api.create_event(payload, organizer_headers)
        event = validate_success(res, expected_status=201)
        assert float(event["tax_withholding_pct"]) == pytest.approx(ok_pct, abs=0.001)


# ===========================================================================
# 3.1 — DRAFT -> OPEN
# ===========================================================================
class TestOpenEvent:
    def test_open_outside_registration_window_blocked(self, api, organizer_headers):
        """PRD §3.1: 'Opening the event by the organizer transitions it from
        DRAFT to OPEN; the precondition is that the current time falls
        within the registration window — that is, registration_opens_at is
        at or before now and now is strictly before
        registration_closes_at.'"""
        # Create event whose registration window is in the future, do NOT
        # advance the clock. Open should fail with ERR_INVALID_STATE since
        # the precondition fails (now < registration_opens_at).
        event = create_event(base_iso="2099-01-01T00:00:00.000Z")
        res = api.open_event(event["id"], organizer_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_open_succeeds_inside_registration_window(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'Opening the event by the organizer transitions it from
        DRAFT to OPEN.'"""
        event = create_event()
        advance_clock(add_minutes(event["registration_opens_at"], 1))
        res = api.open_event(event["id"], organizer_headers)
        opened = validate_success(res)
        assert opened["status"] == "OPEN"


# ===========================================================================
# 3.1 — OPEN -> REGISTRATION_CLOSED
# ===========================================================================
class TestCloseRegistration:
    def test_close_before_registration_closes_at_blocked(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'In both cases the precondition is that now is at or
        after registration_closes_at.'"""
        event = event_open_for_registration()
        # Clock currently inside the window.
        res = api.close_registration(event["id"], organizer_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_close_after_registration_closes_at_succeeds(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'Registration closes either explicitly — by an
        organizer-driven transition from OPEN to REGISTRATION_CLOSED.'"""
        event = event_open_for_registration()
        advance_clock(event["registration_closes_at"])
        res = api.close_registration(event["id"], organizer_headers)
        closed = validate_success(res)
        assert closed["status"] == "REGISTRATION_CLOSED"


# ===========================================================================
# 3.2 — REGISTRATION_CLOSED -> DRAWN
# ===========================================================================
class TestDraw:
    def test_draw_below_capacity_min_rejected(self, api, organizer_headers):
        """PRD §3.2: 'The draw is gated by two preconditions:
        registered_count must be at least capacity_min (otherwise
        ERR_REGISTRATION_BELOW_MIN).'"""
        event = event_open_for_registration(capacity_min=4, capacity_max=8)
        # Register 3 (below capacity_min=4)
        register_n_distinct_participants(event["id"], 3)
        advance_clock(event["registration_closes_at"])
        close_registration(event["id"])
        res = api.draw_event(event["id"], organizer_headers)
        validate_error(res, "ERR_REGISTRATION_BELOW_MIN")

    def test_draw_emits_draw_announced_sync_event(self, api, organizer_headers):
        """PRD §3.2: 'a SyncEvent of kind DRAW_ANNOUNCED is emitted to
        GOVERNING_BODY.'"""
        event, _ = event_drawn(n_participants=4)
        sync = list_sync_events(target_system="GOVERNING_BODY",
                                kind="DRAW_ANNOUNCED")
        assert len(sync) >= 1, (
            "PRD §3.2: a DRAW_ANNOUNCED sync-event row must be emitted "
            "to GOVERNING_BODY on /draw."
        )

    def test_draw_assigns_bracket_seeds_1_to_n(self, api):
        """PRD §3.2: 'Seeding produces an integer bracket_seed from 1 to N,
        where N equals registered_count.'"""
        event, parts = event_drawn(n_participants=4)
        # After draw, every participant must carry a bracket_seed in 1..N.
        seeds = sorted(p["bracket_seed"] for p in list_participants(event["id"]))
        assert seeds == [1, 2, 3, 4]

    def test_draw_creates_match_rows(self, api):
        """PRD §3.2: 'Match rows are created with `event_id`,
        `round_index` (starting at 1 for the first round, incremented
        for survivors even through bye rounds), `bracket_position`
        (1..N within the round), `home_participant_id` (the higher-seed
        participant), `away_participant_id` (the lower-seed
        participant, or `null` for a bye), `scheduled_start_at` and
        `scheduled_end_at` (assigned by the scheduling logic, with
        `scheduled_end_at` strictly later than `scheduled_start_at`),
        and an initial `status` of `SCHEDULED` (or `BYE` for bye rows
        whose `away_participant_id` is `null`).'"""
        event, _ = event_drawn(n_participants=4)
        matches = list_matches(event["id"])
        assert len(matches) >= 2  # At minimum two round-1 matches for 4 players.
        for m in matches:
            assert m["round_index"] >= 1
            assert m["status"] in {"SCHEDULED", "BYE"}


# ===========================================================================
# 3.6 — DRAWN -> IN_PROGRESS preconditions
# ===========================================================================
class TestStartEvent:
    def test_start_before_starts_at_blocked(self, api, organizer_headers):
        """PRD §3.6: 'Two preconditions hold: now is at or after starts_at,
        and every round-1 Match carries at least one ASSIGNED HEAD
        RefereeAssignment.'"""
        event, _ = event_drawn(n_participants=4)
        # Don't advance the clock past starts_at; precondition must fail.
        res = api.start_event(event["id"], organizer_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_start_without_head_referee_blocked(self, api, organizer_headers):
        """PRD §3.6: 'every round-1 `Match` carries at least one
        `ASSIGNED` `RefereeAssignment` of role `HEAD`.'"""
        event, _ = event_drawn(n_participants=4)
        advance_clock(event["starts_at"])
        # No referees assigned — precondition fails.
        res = api.start_event(event["id"], organizer_headers)
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# 3.1 — Cancel
# ===========================================================================
class TestCancel:
    def test_cancel_from_draft(self, api, organizer_headers):
        """PRD §3.1: 'A draft event, an open event, or an event whose
        registration has closed may all be cancelled by the organizer.
        Cancellation from `DRAFT` is a status flip with no cascade.'"""
        event = create_event()
        cancelled = cancel_event(event["id"])
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_from_open_withdraws_all_participants(self, api):
        """PRD §3.1: 'Cancellation from OPEN or REGISTRATION_CLOSED runs
        the same cascade in both cases: every participant in REGISTERED,
        SEEDED, or ACTIVE is converted to WITHDRAWN, and each such
        cascaded withdrawal itself emits a ENTRY_FEE_CHARGED outbox event
        to PAYMENT with a refund payload.'"""
        event = event_open_for_registration()
        register_n_distinct_participants(event["id"], 3)
        cancel_event(event["id"])
        parts = list_participants(event["id"])
        for p in parts:
            assert p["status"] == "WITHDRAWN"
        sync = list_sync_events(target_system="PAYMENT",
                                kind="ENTRY_FEE_CHARGED")
        # At least 3 refund-bearing events must exist (one per participant).
        # Earlier registration calls also emit ENTRY_FEE_CHARGED, so at
        # least 6 total are expected (3 registers + 3 refunds).
        assert len(sync) >= 6


# ===========================================================================
# 2.5 — Optimistic concurrency control
# ===========================================================================
class TestOptimisticConcurrency:
    def test_stale_version_on_open_rejected(self, api, organizer_headers):
        """PRD §2.5: 'Endpoints that mutate a specific resource by its
        identifier accept an optional version field in the request body.
        When version is supplied, the server compares it to the current
        persisted version of the targeted resource; on mismatch, the
        request is rejected with ERR_VERSION_CONFLICT.'"""
        event = create_event()
        advance_clock(add_minutes(event["registration_opens_at"], 1))
        # Wrong version (simulate stale client view).
        res = api.open_event(event["id"], organizer_headers,
                             payload={"version": 99})
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_correct_version_on_open_succeeds(self, api, organizer_headers):
        """PRD §2.5: 'Omitting the `version` field skips the
        optimistic-concurrency check entirely, and the mutation proceeds
        against whatever the current server state is.'"""
        event = create_event()
        advance_clock(add_minutes(event["registration_opens_at"], 1))
        res = api.open_event(event["id"], organizer_headers,
                             payload={"version": event["version"]})
        opened = validate_success(res)
        assert opened["status"] == "OPEN"
        # PRD §2.4: 'version increments by exactly 1 with every mutation'.
        assert opened["version"] == event["version"] + 1
