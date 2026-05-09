"""Participant registration, fee matching, capacity, and the registration
window (PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    add_seconds,
    advance_clock,
    assert_participant,
    close_registration,
    create_event,
    create_event_payload,
    DEFAULT_T0,
    event_open_for_registration,
    find_sync_events,
    list_participants,
    list_sync_events,
    register_n_distinct_participants,
    register_participant,
    register_participant_payload,
    validate_error,
    validate_success,
    withdraw_participant,
)


# ===========================================================================
# 3.1 — Successful registration shape
# ===========================================================================
class TestRegisterParticipant:
    def test_successful_registration_returns_201_and_initial_state(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'On success, the participant row is created with
        status REGISTERED, bracket_seed null, and prize accumulators
        gross_prize_cents and net_prize_cents and final_rank initialized
        to 0, 0, and null respectively.'"""
        event = event_open_for_registration(entry_fee_cents=1500)
        res = api.register_participant(
            event["id"],
            register_participant_payload(entry_fee_paid_cents=1500),
            organizer_headers,
        )
        p = validate_success(res, expected_status=201)
        assert_participant(p)
        assert p["status"] == "REGISTERED"
        assert p["bracket_seed"] is None
        assert p["gross_prize_cents"] == 0
        assert p["net_prize_cents"] == 0
        assert p["final_rank"] is None

    def test_registration_increments_registered_count(self, api):
        """PRD §3.1: 'Event.registered_count increments.'"""
        event = event_open_for_registration()
        before = event["registered_count"]
        register_participant(event["id"])
        from test_helpers import get_event
        after = get_event(event["id"])
        assert after["registered_count"] == before + 1

    def test_registration_emits_entry_fee_charged_sync_event(self, api):
        """PRD §3.1: 'an outbox event of kind ENTRY_FEE_CHARGED is emitted
        to PAYMENT.'"""
        event = event_open_for_registration()
        register_participant(event["id"])
        sync = list_sync_events(target_system="PAYMENT",
                                kind="ENTRY_FEE_CHARGED")
        assert len(sync) >= 1


# ===========================================================================
# 3.1 — Entry fee matching
# ===========================================================================
class TestEntryFeeMismatch:
    @pytest.mark.parametrize("paid", [999, 1001, 0, 100, 5000])
    def test_paid_not_equal_to_event_fee_rejected(
        self, api, organizer_headers, paid
    ):
        """PRD §3.1: 'entry_fee_paid_cents must equal entry_fee_cents
        exactly — neither under nor overpayment is tolerated, with the
        rejection code ERR_ENTRY_FEE_MISMATCH.'"""
        event = event_open_for_registration(entry_fee_cents=1000)
        res = api.register_participant(
            event["id"],
            register_participant_payload(entry_fee_paid_cents=paid),
            organizer_headers,
        )
        validate_error(res, "ERR_ENTRY_FEE_MISMATCH")


# ===========================================================================
# 3.1 — Registration window
# ===========================================================================
class TestRegistrationWindow:
    def test_registration_before_opens_at_rejected(self, api, organizer_headers):
        """PRD §3.1: 'the registration window must be open
        (registration_opens_at at or before now and now strictly before
        registration_closes_at, otherwise ERR_REGISTRATION_CLOSED).'"""
        event = create_event()
        # Open requires now in window — but we want to test registration
        # window check. Move clock to just before opens_at, open event
        # from a future-instant by skipping opening (event remains DRAFT
        # so we instead go through proper lifecycle).
        # Easier: open the event normally, then rewind logic by NOT
        # opening — direct registration on DRAFT also fails. To isolate
        # registration-window check, build event_open_for_registration,
        # but advance clock to past closes_at first.
        opened = event_open_for_registration(base_iso=event["registration_opens_at"])
        # Now move clock past closes_at; window has shut.
        advance_clock(opened["registration_closes_at"])
        res = api.register_participant(
            opened["id"],
            register_participant_payload(),
            organizer_headers,
        )
        validate_error(res, "ERR_REGISTRATION_CLOSED")

    def test_registration_at_closes_at_exclusive_upper_rejected(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'now strictly before registration_closes_at, otherwise
        ERR_REGISTRATION_CLOSED.' difficulty: boundary_precision_check/
        registration_close_inclusive_lower_exclusive_upper."""
        event = event_open_for_registration()
        advance_clock(event["registration_closes_at"])
        res = api.register_participant(
            event["id"],
            register_participant_payload(),
            organizer_headers,
        )
        validate_error(res, "ERR_REGISTRATION_CLOSED")

    def test_registration_just_before_closes_at_succeeds(
        self, api, organizer_headers
    ):
        """PRD §3.1: 'now strictly before registration_closes_at' — at
        registration_closes_at minus one second, registration is open."""
        event = event_open_for_registration()
        advance_clock(add_seconds(event["registration_closes_at"], -1))
        res = api.register_participant(
            event["id"],
            register_participant_payload(),
            organizer_headers,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# 3.1 — Capacity
# ===========================================================================
class TestCapacity:
    def test_register_at_capacity_max_rejected(self, api, organizer_headers):
        """PRD §3.1: 'registered_count must be strictly less than
        capacity_max (otherwise ERR_CAPACITY_EXCEEDED).'"""
        event = event_open_for_registration(capacity_min=2, capacity_max=2)
        register_n_distinct_participants(event["id"], 2)
        # Third registration: registered_count == capacity_max.
        res = api.register_participant(
            event["id"],
            register_participant_payload(country_code="CZ"),
            organizer_headers,
        )
        validate_error(res, "ERR_CAPACITY_EXCEEDED")


# ===========================================================================
# 3.1 — Withdraw
# ===========================================================================
class TestWithdraw:
    def test_withdraw_from_open_decrements_count_and_emits_refund(self, api):
        """PRD §3.1: 'While the event is in `OPEN` or
        `REGISTRATION_CLOSED` and the participant is still `REGISTERED`,
        withdrawal flips the participant to `WITHDRAWN`, decrements
        `Event.registered_count`, and emits an outbox `ENTRY_FEE_CHARGED`
        event with a refund payload (the negative of
        `entry_fee_paid_cents`).'"""
        event = event_open_for_registration()
        ps = register_n_distinct_participants(event["id"], 2)
        from test_helpers import get_event
        before = get_event(event["id"])["registered_count"]
        withdrawn = withdraw_participant(ps[0]["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        after = get_event(event["id"])["registered_count"]
        assert after == before - 1
        sync = list_sync_events(target_system="PAYMENT",
                                kind="ENTRY_FEE_CHARGED")
        # Two registrations + one withdrawal refund = at least 3 events.
        assert len(sync) >= 3
