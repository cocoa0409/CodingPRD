"""Fine lifecycle — pay, dispute, dispute-uphold, dispute-reject,
OVERDUE sweep, and late-penalty compounding.

PRD §3.6 covers these flows; PRD §3.5 covers the violation cascade
when fines settle/dismiss.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_by_days,
    advance_clock_to,
    create_account,
    create_vehicle,
    current_clock,
    dispute_fine_payload,
    find_fine_for_account,
    get_account,
    get_fine,
    get_vehicle,
    ingest_hov_fraud_event,
    ingest_insufficient_funds_event,
    make_account_holder_headers,
    open_dispute,
    parse_iso,
    pay_fine_payload,
    reject_dispute,
    setup_account_with_vehicle,
    uphold_dispute,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Pay — PRD §3.6
# ---------------------------------------------------------------------------
def test_pay_pending_fine_transitions_to_settled(api):
    """PRD §3.6: "A successful payment moves the fine to the terminal
    `SETTLED` status, cascades the associated violation to `CLEARED`,
    subtracts the fine's `amount_cents` from
    `Account.outstanding_fine_cents`".

    Claim: paying a PENDING fine sets settlement_status=SETTLED and
    drops outstanding_fine_cents to 0.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    res = api.pay_fine(
        fine["id"], pay_fine_payload(),
        make_account_holder_headers(a["id"]),
    )
    settled = validate_success(res, expected_status=200)
    assert settled["settlement_status"] == "SETTLED"
    refreshed = get_account(a["id"])
    assert refreshed["outstanding_fine_cents"] == 0


def test_pay_non_pending_non_overdue_rejected(api):
    """PRD §3.6: "The fine must be in `PENDING` or `OVERDUE` settlement
    status; any other status is rejected with `ERR_INVALID_STATE`."

    Claim: paying a DISPUTED fine → 409 ERR_INVALID_STATE.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    api.dispute_fine(
        fine["id"], dispute_fine_payload(reason="r"),
        make_account_holder_headers(a["id"]),
    )
    res = api.pay_fine(
        fine["id"], pay_fine_payload(),
        make_account_holder_headers(a["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_pay_only_by_account_holder(api):
    """PRD §4: POST /fines/{fine_id}/pay is exclusive to AccountHolder.

    Claim: AgencyAdmin attempting to pay a fine → 403 ERR_FORBIDDEN.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    res = api.pay_fine(
        fine["id"], pay_fine_payload(),
        TEST_USERS["agency_admin_headers"],
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------------
# Dispute — PRD §3.6
# ---------------------------------------------------------------------------
def test_dispute_pending_increments_count_and_transitions(api):
    """PRD §3.6: "Opening a dispute moves the fine from `PENDING` to
    `DISPUTED`, increments `dispute_count` by one".

    Claim: dispute_count goes 0 → 1 and settlement_status flips
    PENDING → DISPUTED.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    assert fine["dispute_count"] == 0
    res = api.dispute_fine(
        fine["id"], dispute_fine_payload(reason="r"),
        make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=200)
    assert data["settlement_status"] == "DISPUTED"
    assert data["dispute_count"] == 1


def test_dispute_third_attempt_rejected(api):
    """PRD §3.6: "A new dispute is permitted only when the fine's
    `dispute_count` is strictly less than 2; an attempt to open a third
    dispute is rejected with `ERR_DISPUTE_LIMIT_REACHED`."

    Claim: after two dispute → reject cycles, dispute_count=2 and the
    third dispute attempt → 409 ERR_DISPUTE_LIMIT_REACHED.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    # Cycle 1
    open_dispute(a["id"], fine["id"])
    reject_dispute(fine["id"])
    # Cycle 2
    open_dispute(a["id"], fine["id"])
    reject_dispute(fine["id"])
    refreshed = get_fine(fine["id"], a["id"])
    assert refreshed["dispute_count"] == 2

    # Third attempt
    res = api.dispute_fine(
        fine["id"], dispute_fine_payload(reason="third"),
        make_account_holder_headers(a["id"]),
    )
    validate_error(res, "ERR_DISPUTE_LIMIT_REACHED", expected_status=409)


def test_dispute_uphold_moves_to_dismissed(api):
    """PRD §3.6: "Upholding the dispute is the consumer-favorable
    resolution: the fine moves from `DISPUTED` to the terminal
    `DISMISSED` state, the associated violation cascades to `CLEARED`".

    Claim: uphold on DISPUTED fine → settlement_status DISMISSED.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    open_dispute(a["id"], fine["id"])
    res = api.uphold_dispute(
        fine["id"], TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=200)
    assert data["settlement_status"] == "DISMISSED"


def test_dispute_reject_returns_to_pending(api):
    """PRD §3.6: "Rejecting the dispute returns the fine from
    `DISPUTED` back to `PENDING`; this re-applies the fine's
    `amount_cents` to the account's outstanding total".

    Claim: reject on DISPUTED fine → settlement_status PENDING.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    open_dispute(a["id"], fine["id"])
    res = api.reject_dispute(
        fine["id"], TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=200)
    assert data["settlement_status"] == "PENDING"


# ---------------------------------------------------------------------------
# OVERDUE — PRD §3.6
# ---------------------------------------------------------------------------
def test_clock_advance_past_due_overdues_fine_with_late_penalty(api):
    """PRD §3.6: "When the logical clock advances past a fine's
    `due_at` and the fine is still `PENDING`, an automatic sweep
    transitions it to `OVERDUE`. The sweep adds a late penalty of 2000
    cents to both `amount_cents` and `civil_penalty_cents`".

    Claim: after clock-advance past due_at, the PENDING fine becomes
    OVERDUE and both amount_cents and civil_penalty_cents grow by 2000.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    initial_amount = fine["amount_cents"]
    initial_civil = fine["civil_penalty_cents"]
    # Advance clock to one second past due_at.
    due = parse_iso(fine["due_at"])
    advance_clock_to(due + timedelta(seconds=1))

    refreshed = get_fine(fine["id"], a["id"])
    assert refreshed["settlement_status"] == "OVERDUE"
    assert refreshed["amount_cents"] == initial_amount + 2000
    assert refreshed["civil_penalty_cents"] == initial_civil + 2000


def test_pay_overdue_fine_transitions_to_settled(api):
    """PRD §3.6: "Paying an `OVERDUE` fine settles it in the same way
    as paying a `PENDING` fine: the violation cascades to `CLEARED`,
    an escalated vehicle is restored from `BLOCKED` to `ACTIVE`, the
    fine's full `amount_cents` (including the accrued late penalty)
    is subtracted from `outstanding_fine_cents`, and the account may
    flip from `SUSPENDED` to `ACTIVE`."

    Claim: pay on OVERDUE fine → SETTLED.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    due = parse_iso(fine["due_at"])
    advance_clock_to(due + timedelta(seconds=1))

    refreshed = get_fine(fine["id"], a["id"])
    assert refreshed["settlement_status"] == "OVERDUE"

    res = api.pay_fine(
        fine["id"], pay_fine_payload(),
        make_account_holder_headers(a["id"]),
    )
    settled = validate_success(res, expected_status=200)
    assert settled["settlement_status"] == "SETTLED"


def test_overdue_with_dispute_count_two_escalates_vehicle(api):
    """PRD §3.6: "if the fine's `dispute_count` is at 2 already —
    cascades the associated `Violation` from `OPEN` to `ESCALATED`
    (placing a registration hold on the affected vehicle by setting
    its status to `BLOCKED`)."

    Claim: after two dispute→reject cycles bringing dispute_count to 2,
    advancing the clock past due_at flips the Violation to ESCALATED
    and the Vehicle.status to BLOCKED.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    open_dispute(a["id"], fine["id"])
    reject_dispute(fine["id"])
    open_dispute(a["id"], fine["id"])
    reject_dispute(fine["id"])

    due = parse_iso(fine["due_at"])
    advance_clock_to(due + timedelta(seconds=1))

    v_after = get_vehicle(a["id"], v["id"])
    assert v_after["status"] == "BLOCKED"
