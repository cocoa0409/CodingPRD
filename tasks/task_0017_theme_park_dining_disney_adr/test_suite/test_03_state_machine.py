"""Reservation, ParkSession, and AllergyMeal state-machine invariants — mainly Queue B."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    set_clock,
    setup_pending_reservation,
    setup_confirmed_reservation,
    cancel_reservation,
    make_guest_headers,
    cancel_reservation_payload,
    TEST_USERS,
    ApiErrorId,
)


def test_cancel_already_cancelled_reservation_returns_invalid_state(api):
    """PRD §2.8: "the target resource's current-state compatibility with the
    requested transition (ERR_INVALID_STATE)"
    PRD §4 (endpoint table): cancel is for "PENDING or CONFIRMED" only — terminal
    states are not valid sources for cancel.

    Design: Corner/state_machines/cancel_already_cancelled_reservation_returns_invalid_state
    """
    _, _, _, _, pending = setup_pending_reservation(party_size=1)
    # First cancel: succeeds (PENDING → CANCELLED).
    cancelled = cancel_reservation(pending["id"], pending["version"], pending["guest_id"])
    assert cancelled["status"] == "CANCELLED"
    # Second cancel: should be ERR_INVALID_STATE.
    res = api.cancel_reservation(
        pending["id"],
        cancel_reservation_payload(cancelled["version"]),
        make_guest_headers(pending["guest_id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_check_in_pending_reservation_skipping_confirm_returns_invalid_state(api):
    """PRD §3.5: "When the guest arrives at the restaurant, check-in advances the
    reservation from CONFIRMED to CHECKED_IN."
    PRD §2.8: precondition-state failure → ERR_INVALID_STATE.

    Design: Corner/state_machines/check_in_pending_reservation_skipping_confirm_returns_invalid_state
    """
    _, _, _, _, pending = setup_pending_reservation(party_size=1)
    # Skip the confirm; attempt check-in directly.
    res = api.check_in_reservation(pending["id"], make_guest_headers(pending["guest_id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_cancel_confirmed_inside_two_hour_cutoff_returns_invalid_state(api):
    """PRD §3.4: "A confirmed reservation can be cancelled by the guest at any time
    before two hours prior to slot_start_utc: the rule is that the current UTC time
    must be strictly earlier than slot_start_utc minus two hours. Inside that
    two-hour window the cancel path from CONFIRMED is no longer available."
    PRD §2.8: precondition violation → ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_confirmed_inside_two_hour_cutoff_returns_invalid_state
    """
    guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
        party_size=2,
        slot_start_utc="2026-02-15T18:00:00Z",
    )
    # Advance clock to 16:30Z — 90 minutes before slot, inside cutoff.
    set_clock("2026-02-15T16:30:00Z")
    res = api.cancel_reservation(
        reservation["id"],
        cancel_reservation_payload(reservation["version"]),
        make_guest_headers(guest["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    # Cancel was rejected; reservation must still be CONFIRMED with credits held.
    fetched = validate_success(
        api.get_reservation(reservation["id"], make_guest_headers(guest["id"])),
        expected_status=200,
    )
    assert fetched["status"] == "CONFIRMED"
    assert fetched["credits_held"] == 2


def test_no_show_sweep_idempotent_second_sweep_finds_nothing(api):
    """PRD §3.8: "The no-show sweep capability walks every Reservation in CONFIRMED
    whose slot_end_utc is now strictly earlier than the current UTC time and runs
    the full CONFIRMED-to-NO_SHOW cascade on each ... returning a swept_count
    integer and a swept_reservation_ids string array."

    Design: Corner/state_machines/no_show_sweep_idempotent_second_sweep_finds_nothing
    """
    guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(party_size=1)
    # Advance clock past slot_end so the sweep picks up this reservation.
    set_clock("2026-02-15T19:00:00Z")
    res = api.no_show_sweep(TEST_USERS["platform_admin_headers"])
    first = validate_success(res, expected_status=200)
    assert first["swept_count"] == 1
    # Second sweep — nothing left.
    res2 = api.no_show_sweep(TEST_USERS["platform_admin_headers"])
    second = validate_success(res2, expected_status=200)
    assert second["swept_count"] == 0
