"""Complexity layers — OCC positive path, clock-driven scheduled actions — and the
immediate-consistency invariant. Queue B (Corner)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    setup_confirmed_reservation,
    setup_guest_restaurant_plan_session,
    cancel_reservation_payload,
    create_reservation_payload,
    make_guest_headers,
    TEST_USERS,
)


def test_occ_correct_version_succeeds_on_cancel(api):
    """PRD §2.7: "Both endpoints take a non-optional input field
    expected_reservation_version of integer type, which must equal the parent
    Reservation's current version."
    PRD §2.4: "The version field is an integer that begins at 1 on creation and
    is incremented by exactly 1 on every server-committed mutation"

    Design: Corner/complexity_layers/occ_correct_version_succeeds_on_cancel
    """
    guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(party_size=1)
    current = reservation["version"]
    res = api.cancel_reservation(
        reservation["id"],
        cancel_reservation_payload(current),
        make_guest_headers(guest["id"]),
    )
    cancelled = validate_success(res, expected_status=200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] > current


def test_clock_set_changes_validation_outcome_scheduled_action(api):
    """PRD §3.8: "The clock-set capability accepts a single field to_iso8601 and
    overwrites the platform's virtual current UTC for the entire deployment; every
    time-based gate in the system — window opening, slot-grid alignment, two-hour
    cancel cutoff, fifteen-minute check-in grace, no-show grace, Lightning Lane
    expiry window — reads from this virtual clock thereafter."
    PRD §3.3: "The booking window opens, for each calendar visit_date, exactly 60
    days before that date, at 06:00:00 in the resort timezone."

    Design: Corner/complexity_layers/clock_set_changes_validation_outcome_scheduled_action
    """
    # Provision dependencies BEFORE advancing the clock.
    set_clock("2025-11-01T00:00:00Z")
    guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
        park_code="EPCOT",
        visit_date="2026-02-15",
        plan_valid_from="2025-11-01T00:00:00Z",
        plan_valid_until="2026-12-31T00:00:00Z",
    )
    # Advance clock inside the booking window (well past 2025-12-17T11:00:00Z).
    set_clock("2026-01-15T12:00:00Z")
    payload = create_reservation_payload(
        guest_id=guest["id"],
        restaurant_id=restaurant["id"],
        park_session_id=ps["id"],
        dining_plan_id=dp["id"],
        slot_start_utc="2026-02-15T18:00:00Z",
        party_size=1,
    )
    res = api.create_reservation(payload, make_guest_headers(guest["id"]))
    reservation = validate_success(res, expected_status=201)
    assert reservation["status"] == "PENDING"


def test_immediate_consistency_dining_plan_balance_reflected_in_same_response(api):
    """PRD §2.6: "The platform's consistency model is immediate: a caller that
    observes the originating entity in its post-transition state will, on any
    subsequent read of a cascaded entity, observe that entity in its post-cascade
    state as well. There is no eventual-consistency window between an originating
    transition and its derived effects."
    PRD §3.4: "On a successful commit, the platform sets Reservation.credits_held
    to the restaurant's dining_plan_credit_cost multiplied by the reservation's
    current party_size, increases the plan's table_service_credits_held by exactly
    that amount"

    Design: Corner/consistency_model/immediate_consistency_dining_plan_balance_reflected_in_same_response
    """
    guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
        party_size=2,
        dining_plan_credit_cost=1,
        table_service_credits_initial=10,
    )
    # Immediately read the plan.
    res = api.get_dining_plan(dp["id"], make_guest_headers(guest["id"]))
    plan = validate_success(res, expected_status=200)
    assert plan["table_service_credits_held"] == 2
    assert plan["table_service_credits_remaining"] == 10
