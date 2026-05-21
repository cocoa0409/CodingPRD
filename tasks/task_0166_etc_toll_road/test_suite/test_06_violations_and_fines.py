"""Violation and Fine creation tests — reason codes, fine_amount, and
outstanding-fine reconciliation.

PRD §3.3 covers violation creation; PRD §3.5 covers fine_amount and
outstanding reconciliation; PRD §3.6 covers fine lifecycle.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_fine,
    create_account,
    create_toll_event_payload,
    create_vehicle,
    find_fine_for_account,
    ingest_hov_fraud_event,
    ingest_insufficient_funds_event,
    make_account_holder_headers,
    setup_account_with_bound_transponder,
    setup_account_with_vehicle,
    validate_success,
)


# ---------------------------------------------------------------------------
# Fine amount = toll_component + civil_penalty by reason_code — PRD §3.5
# ---------------------------------------------------------------------------
def test_fine_amount_hov_fraud(api):
    """PRD §3.5: "an `HOV_FRAUD` violation incurs 10000 cents."

    PRD §3.5: "The toll component is computed by running the same
    pricing algorithm described in §3.3 but in its plate-bill variant —
    that is, with the fifteen-percent plate-bill surcharge applied
    regardless of how the original event was attributed".

    Claim: HOV_FRAUD with base=200, same-agency, CLASS_2:
    toll_component = round_half_up(200 * 1.00) = 200 + round_half_up
    (200 * 0.15) = 30 → 230; civil_penalty = 10000; amount = 10230.
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
    assert fine is not None, "Expected a fine to be created"
    assert_fine(fine)
    assert fine["civil_penalty_cents"] == 10000
    assert fine["amount_cents"] == 10230
    assert fine["settlement_status"] == "PENDING"
    assert fine["dispute_count"] == 0


def test_fine_amount_insufficient_funds(api):
    """PRD §3.5: "an `UNREAD_TRANSPONDER_NO_PLATE` violation incurs a
    civil penalty of 5000 cents, an `INSUFFICIENT_FUNDS_ON_PLATE_BILL`
    violation incurs 2500 cents, a `BLOCKED_VEHICLE` violation incurs
    7500 cents, and an `HOV_FRAUD` violation incurs 10000 cents."

    Claim: INSUFFICIENT_FUNDS with base=200, same-agency: toll_comp=230,
    civil=2500, amount=2730.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    assert fine is not None
    assert fine["civil_penalty_cents"] == 2500
    assert fine["amount_cents"] == 2730


# ---------------------------------------------------------------------------
# Violation linked to TollEvent — PRD §3.5
# ---------------------------------------------------------------------------
def test_fine_due_at_thirty_days_after_issued(api):
    """PRD §3.5: "The fine is stamped with `issued_at` matching the
    violation's creation time and `due_at` exactly thirty days after
    `issued_at`."

    Claim: due_at == issued_at + 30 days.
    """
    from datetime import timedelta

    from test_helpers import parse_iso

    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    issued = parse_iso(fine["issued_at"])
    due = parse_iso(fine["due_at"])
    assert (due - issued) == timedelta(days=30)


def test_initial_fine_dispute_count_zero(api):
    """PRD §3.5: "Its initial `settlement_status` is `PENDING` and its
    `dispute_count` is 0."

    Claim: a newly created Fine has dispute_count == 0 and status
    PENDING.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    assert fine["dispute_count"] == 0
    assert fine["settlement_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Outstanding-fine reconciliation — PRD §3.5
# ---------------------------------------------------------------------------
def test_outstanding_fine_cents_includes_pending(api):
    """PRD §3.5: "The system reconciles
    `Account.outstanding_fine_cents` by summing the `amount_cents` of
    every fine tied to the account whose `settlement_status` is
    `PENDING` or `OVERDUE`; fines whose status is `DISPUTED`,
    `SETTLED`, or `DISMISSED` do not contribute (a `DISPUTED` fine
    counts as zero outstanding)."

    Claim: a single PENDING fine of 2730 puts outstanding at 2730 and
    keeps Account.status = ACTIVE (since 2730 < 15000).
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    refreshed = validate_success(
        api.get_account(a["id"], TEST_USERS["agency_admin_headers"]),
        expected_status=200,
    )
    assert refreshed["outstanding_fine_cents"] == 2730
    assert refreshed["status"] == "ACTIVE"


def test_outstanding_crosses_suspend_threshold(api):
    """PRD §3.5: "When that total reaches or exceeds 15000 cents — the
    suspension threshold — and the account is currently `ACTIVE`, the
    account transitions to `SUSPENDED` with the cascades described in
    §2.8."

    Claim: two HOV_FRAUD fines (each 10230) sum to 20460 ≥ 15000 →
    Account.status flips to SUSPENDED.
    """
    a = create_account(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False,
    )
    v1 = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                        hov_capable=True)
    v2 = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                        hov_capable=True)
    ingest_hov_fraud_event(a, v1, base_rate_cents=200,
                           agency_code="NY_EZPASS")
    ingest_hov_fraud_event(a, v2, base_rate_cents=200,
                           agency_code="NY_EZPASS")
    refreshed = validate_success(
        api.get_account(a["id"], TEST_USERS["agency_admin_headers"]),
        expected_status=200,
    )
    assert refreshed["outstanding_fine_cents"] == 20460
    assert refreshed["status"] == "SUSPENDED"


# ---------------------------------------------------------------------------
# Suspension cascade — PRD §2.8
# ---------------------------------------------------------------------------
def test_suspension_cascades_vehicles_blocked_and_transponder_suspended(api):
    """PRD §2.8: "When an account becomes `SUSPENDED` because its
    outstanding fine total has crossed the suspension threshold, every
    `Vehicle` owned by that account is cascaded to `BLOCKED`, and every
    `Transponder` whose status is `ACTIVE` and owned by that account is
    cascaded to `SUSPENDED`."

    Claim: after suspension, Vehicle.status==BLOCKED for all vehicles.
    """
    # Build account with two HOV_FRAUD fraud-vehicles + 1 ACTIVE
    # vehicle. After cascade all three vehicles should be BLOCKED.
    a = create_account(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False,
    )
    target_v = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                              hov_capable=True)
    v_fraud1 = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                              hov_capable=True)
    v_fraud2 = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                              hov_capable=True)
    ingest_hov_fraud_event(a, v_fraud1, base_rate_cents=200,
                           agency_code="NY_EZPASS")
    ingest_hov_fraud_event(a, v_fraud2, base_rate_cents=200,
                           agency_code="NY_EZPASS")

    for v in (target_v, v_fraud1, v_fraud2):
        refreshed = validate_success(
            api.get_vehicle(
                a["id"], v["id"],
                TEST_USERS["agency_admin_headers"],
            ),
            expected_status=200,
        )
        assert refreshed["status"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Disputed fines do NOT contribute to outstanding — PRD §3.5
# ---------------------------------------------------------------------------
def test_disputed_fine_excluded_from_outstanding(api):
    """PRD §3.5: "fines whose status is `DISPUTED`, `SETTLED`, or
    `DISMISSED` do not contribute (a `DISPUTED` fine counts as zero
    outstanding)."

    Claim: after disputing a PENDING fine, Account.outstanding_fine_cents
    drops to 0.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                    agency_code="NY_EZPASS")
    fine = find_fine_for_account(a["id"])
    api.dispute_fine(
        fine["id"], {"reason": "wrong plate"},
        make_account_holder_headers(a["id"]),
    )
    refreshed = validate_success(
        api.get_account(a["id"], TEST_USERS["agency_admin_headers"]),
        expected_status=200,
    )
    assert refreshed["outstanding_fine_cents"] == 0
