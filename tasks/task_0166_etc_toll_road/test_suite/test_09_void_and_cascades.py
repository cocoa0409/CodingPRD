"""Void tests — 24h window, refund cascade, violation cascade,
account-suspend reversal.

PRD §3.3 covers the void window and refund/dismiss; PRD §2.8 covers
the cascades.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_by_seconds,
    advance_clock_to,
    create_account,
    create_vehicle,
    current_clock,
    find_fine_for_account,
    get_account,
    get_fine,
    get_toll_event,
    ingest_hov_fraud_event,
    ingest_toll_event,
    make_account_holder_headers,
    parse_iso,
    setup_account_with_bound_transponder,
    setup_account_with_vehicle,
    setup_posted_toll_event,
    setup_suspended_account_via_two_hov_frauds,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Void window — PRD §3.3
# ---------------------------------------------------------------------------
def test_void_within_24h_refunds_posted_balance(api):
    """PRD §3.3: "Voiding a `POSTED` or `TOLL_BY_PLATE_INVOICED` event
    refunds the prior debit by adding `net_toll_cents` back to the
    balance and resetting both `net_toll_cents` and `gross_toll_cents`
    to zero."

    Claim: balance after void equals balance before posting; net and
    gross zero.
    """
    a, v, event = setup_posted_toll_event(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        base_rate_cents=347,
    )
    # Confirm balance has been debited.
    after_post = get_account(a["id"])
    assert after_post["balance_cents"] == 10000 - 347

    res = api.void_toll_event(
        event["id"], TEST_USERS["agency_admin_headers"],
    )
    voided = validate_success(res, expected_status=200)
    assert voided["billing_status"] == "VOIDED"
    assert voided["net_toll_cents"] == 0
    assert voided["gross_toll_cents"] == 0

    refunded = get_account(a["id"])
    assert refunded["balance_cents"] == 10000


def test_void_after_24h_window_rejected(api):
    """PRD §3.3: "but only within 24 hours of its `created_at`;
    outside this window the request is rejected with
    `ERR_VOID_WINDOW_EXPIRED`."

    Claim: clock-advance past 24h after created_at → void → 409
    ERR_VOID_WINDOW_EXPIRED.
    """
    a, v, event = setup_posted_toll_event(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        base_rate_cents=200,
    )
    created = parse_iso(event["created_at"])
    advance_clock_to(created + timedelta(hours=24, seconds=2))
    res = api.void_toll_event(
        event["id"], TEST_USERS["agency_admin_headers"],
    )
    validate_error(res, "ERR_VOID_WINDOW_EXPIRED", expected_status=409)


def test_void_pending_event_rejected(api):
    """PRD §3.3: "A void is permitted only from `POSTED`,
    `TOLL_BY_PLATE_INVOICED`, or `VIOLATED`; in any other billing
    status the request is rejected with `ERR_INVALID_STATE`."

    Note: a PENDING event is not stable in this system (every ingest
    moves to a terminal state immediately), so we exercise the
    requirement via an already-VOIDED event — re-voiding it.
    Claim: voiding an event whose billing_status is VOIDED → 409
    ERR_INVALID_STATE.
    """
    a, v, event = setup_posted_toll_event(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        base_rate_cents=200,
    )
    api.void_toll_event(
        event["id"], TEST_USERS["agency_admin_headers"],
    )
    res = api.void_toll_event(
        event["id"], TEST_USERS["agency_admin_headers"],
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------------
# Violation void → fine dismissed cascade — PRD §3.3, §3.5
# ---------------------------------------------------------------------------
def test_void_violated_event_dismisses_fine_and_clears_violation(api):
    """PRD §3.3: "Voiding a `VIOLATED` event is permitted only while
    the associated fine's settlement status is still `PENDING`; the
    void cascades the associated `Violation` to `CLEARED` and the
    associated `Fine` to `DISMISSED`".

    Claim: void on VIOLATED event with PENDING fine → fine.SETTLEMENT
    transitions to DISMISSED.
    """
    a = create_account(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False,
    )
    v = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                       hov_capable=True)
    ingest_hov_fraud_event(a, v, base_rate_cents=200,
                           agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    assert fine["settlement_status"] == "PENDING"

    # Get the toll_event_id via the Violation -> we don't have a list
    # endpoint, so the Fine should carry violation_id; otherwise we
    # rely on /toll-events list filtered by account.
    res = api.list_toll_events(
        TEST_USERS["agency_admin_headers"],
        params={"account_id": a["id"]},
    )
    body = res.json()
    events = body.get("data") or []
    assert events, "expected at least one toll event"
    violated_event = next(e for e in events
                          if e["billing_status"] == "VIOLATED")
    void_res = api.void_toll_event(
        violated_event["id"], TEST_USERS["agency_admin_headers"],
    )
    voided = validate_success(void_res, expected_status=200)
    assert voided["billing_status"] == "VOIDED"

    refined_fine = get_fine(fine["id"], a["id"])
    assert refined_fine["settlement_status"] == "DISMISSED"


# ---------------------------------------------------------------------------
# Suspension cascade reversal via void — PRD §2.8, §3.5
# ---------------------------------------------------------------------------
def test_void_drops_outstanding_below_threshold_reactivates_account(api):
    """PRD §3.5: "When the total later falls back below 15000 cents and
    the account is currently `SUSPENDED`, the account returns to
    `ACTIVE` with the reverse cascades."

    Claim: after voiding one of two HOV_FRAUD events on a SUSPENDED
    account, outstanding drops below 15000 → Account.status flips
    to ACTIVE.
    """
    account, frauds, target, _ = setup_suspended_account_via_two_hov_frauds()
    assert account["status"] == "SUSPENDED"
    # Find the two VIOLATED toll events on this account.
    res = api.list_toll_events(
        TEST_USERS["agency_admin_headers"],
        params={"account_id": account["id"]},
    )
    body = res.json()
    events = body.get("data") or []
    violated = [e for e in events if e["billing_status"] == "VIOLATED"]
    assert len(violated) >= 1
    api.void_toll_event(
        violated[0]["id"], TEST_USERS["agency_admin_headers"],
    )

    refreshed = get_account(account["id"])
    assert refreshed["outstanding_fine_cents"] < 15000
    assert refreshed["status"] == "ACTIVE"
