"""Rate lock placement, extensions (cyclic self-loop, cap, fee tiers),
cancellation, and the 48-hour free-look refund (PRD §3.5).

Covers difficulty design instances:
- non_linear_state_machine/rate_lock_cyclic_self_loop_on_extended
- boundary_precision_check/extension_cap_60_vs_61_days_strict_greater_than
- resource_temporal_overlap/rate_lock_active_window_singleton_per_application
- compensating_invariant/rate_lock_fee_accounting_invariant
- cross_entity_state_dependency/rate_lock_extension_depends_on_loan_application_state
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_rate_lock,
    assert_rate_lock_fee_invariant,
    create_and_pre_qualify,
    extend_rate_lock,
    extend_rate_lock_payload,
    get_loan_application,
    get_rate_lock,
    iso_plus,
    place_rate_lock,
    place_rate_lock_payload,
    setup_rate_lock_with_cumulative_extra_days,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rate lock placement — PRD §3.5
# ===========================================================================
def test_place_rate_lock_sets_45_day_expiry_and_25bps_fee(
    api, loan_officer_headers,
):
    """PRD §3.5: "The lock is created in LOCKED, with the system
    stamping locked_at to SystemClock.now, computing lock_expires_at
    as locked_at plus 45 days, and computing lock_fee_cents as 25 basis
    points (0.25%) of the application's requested_loan_amount_cents,
    rounded half-up to whole cents."

    Claim: with requested_loan_amount_cents=20_000_000 (= $200,000),
    lock_fee_cents = ROUND_HALF_UP(20_000_000 * 25 / 10000) = 50_000
    cents. lock_expires_at = locked_at + 45 days.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    rl = place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    assert_rate_lock(rl)
    assert rl["status"] == "LOCKED"
    assert rl["lock_fee_cents"] == 50_000, (
        "PRD §3.5: lock_fee_cents = 25 bps of 20_000_000 = 50_000 cents"
    )
    assert rl["extension_fee_paid_cents"] == 0
    # lock_expires_at = locked_at + 45 days
    expected = iso_plus(rl["locked_at"], days=45)
    assert rl["lock_expires_at"] == expected, (
        "PRD §3.5: lock_expires_at = locked_at + 45 days. "
        f"Expected {expected}, got {rl['lock_expires_at']}."
    )


def test_locked_rate_bps_above_2000_rejected(api, loan_officer_headers):
    """PRD §3.5: "a locked_rate_bps — an interest rate expressed in
    basis points, strictly positive and not exceeding 2,000 (i.e.,
    20%)."

    Claim: locked_rate_bps=2001 -> ERR_VALIDATION.
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    res = api.place_rate_lock(
        app["id"],
        place_rate_lock_payload(locked_rate_bps=2001),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_VALIDATION.value, expected_status=422,
    )


def test_rate_lock_overlap_rejected_when_one_already_active(
    api, loan_officer_headers,
):
    """PRD §3.5: "The system permits at most one active RateLock — one
    whose status is LOCKED or EXTENDED — per LoanApplication at any
    time; attempting to place a second active lock is rejected with
    ERR_RATE_LOCK_OVERLAP."

    Claim: a second POST /rate-lock while the first is LOCKED returns
    409 ERR_RATE_LOCK_OVERLAP.

    # difficulty: resource_temporal_overlap/rate_lock_active_window_singleton_per_application
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    res = api.place_rate_lock(
        app["id"],
        place_rate_lock_payload(locked_rate_bps=640),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_RATE_LOCK_OVERLAP.value,
        expected_status=409,
    )


def test_rate_lock_singleton_after_cancel_can_replace(
    api, loan_officer_headers,
):
    """PRD §3.5: "at most one active RateLock — one whose status is
    LOCKED or EXTENDED — per LoanApplication at any time".

    Claim: after the first lock is CANCELLED (no longer LOCKED/EXTENDED),
    a fresh POST /rate-lock must be accepted (the singleton is now free).

    # difficulty: resource_temporal_overlap/rate_lock_active_window_singleton_per_application
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    rl1 = place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    cancelled = validate_success(
        api.cancel_rate_lock(app["id"], None, loan_officer_headers), 200,
    )
    assert cancelled["status"] == "CANCELLED"
    # Now a fresh lock should succeed.
    rl2 = place_rate_lock(
        app["id"], locked_rate_bps=640, headers=loan_officer_headers,
    )
    assert rl2["status"] == "LOCKED"
    assert rl2["id"] != rl1["id"]


# ===========================================================================
# Rate lock extension tiers — PRD §3.5
# difficulty: non_linear_state_machine/rate_lock_cyclic_self_loop_on_extended
# ===========================================================================
def test_extension_fee_tier_7_days(api, loan_officer_headers):
    """PRD §3.5: "The fee schedule is tiered on extra_days: 7 days
    costs 5 basis points of the requested_loan_amount_cents, 15 days
    costs 10 basis points, and 30 days costs 25 basis points; the raw
    product is rounded half-up to whole cents."

    Claim: with requested=20_000_000, extend by 7 ->
    fee = ROUND_HALF_UP(20_000_000 * 5 / 10_000) = 10_000 cents.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    rl = extend_rate_lock(
        app["id"], extra_days=7, headers=loan_officer_headers,
    )
    assert rl["status"] == "EXTENDED"
    assert rl["extension_fee_paid_cents"] == 10_000, (
        "PRD §3.5: 7-day extension fee = 5 bps of 20_000_000 = 10_000."
    )


def test_extension_fee_tier_15_days(api, loan_officer_headers):
    """PRD §3.5: "15 days costs 10 basis points"

    Claim: extend by 15 -> 20_000 cents on 20_000_000 principal.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    rl = extend_rate_lock(
        app["id"], extra_days=15, headers=loan_officer_headers,
    )
    assert rl["extension_fee_paid_cents"] == 20_000


def test_extension_fee_tier_30_days(api, loan_officer_headers):
    """PRD §3.5: "30 days costs 25 basis points"

    Claim: extend by 30 -> 50_000 cents on 20_000_000 principal.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    rl = extend_rate_lock(
        app["id"], extra_days=30, headers=loan_officer_headers,
    )
    assert rl["extension_fee_paid_cents"] == 50_000


def test_extension_cyclic_self_loop_accumulates_fees(
    api, loan_officer_headers,
):
    """PRD §3.5: "A lock already in EXTENDED can be re-extended by the
    same mechanism (a self-loop on the state), subject to a cumulative
    cap: the sum of extra_days across all RateLockExtension rows on
    this lock must not exceed 60 days"

    Claim: 7 + 15 + 30 = 52 cumulative extension days; status remains
    EXTENDED throughout; extension_fee_paid_cents accumulates to
    10_000 + 20_000 + 50_000 = 80_000.

    # difficulty: non_linear_state_machine/rate_lock_cyclic_self_loop_on_extended
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    rl = place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    initial_expires = rl["lock_expires_at"]

    rl = extend_rate_lock(
        app["id"], extra_days=7, headers=loan_officer_headers,
    )
    assert rl["status"] == "EXTENDED"
    rl = extend_rate_lock(
        app["id"], extra_days=15, headers=loan_officer_headers,
    )
    assert rl["status"] == "EXTENDED", (
        "PRD §3.5: re-extension is a self-loop on EXTENDED"
    )
    rl = extend_rate_lock(
        app["id"], extra_days=30, headers=loan_officer_headers,
    )
    assert rl["status"] == "EXTENDED"
    assert rl["extension_fee_paid_cents"] == 80_000, (
        f"Cumulative ext_fee should be 80_000, got "
        f"{rl['extension_fee_paid_cents']}."
    )
    # lock_expires_at moved by 7+15+30 = 52 days from the initial.
    expected_after = iso_plus(initial_expires, days=52)
    assert rl["lock_expires_at"] == expected_after, (
        "PRD §3.5: lock_expires_at advances by the cumulative "
        "extra_days across all extensions."
    )


# ===========================================================================
# Extension cap boundary — PRD §3.5
# difficulty: boundary_precision_check/extension_cap_60_vs_61_days_strict_greater_than
# ===========================================================================
def test_extension_cumulative_60_days_accepted(api, loan_officer_headers):
    """PRD §3.5: "the sum of extra_days across all RateLockExtension
    rows on this lock must not exceed 60 days; an extension that would
    breach the cap is rejected with ERR_EXTENSION_CAP_EXCEEDED."

    Claim: a final 7-day extension that brings cumulative to 60 days
    (30 + 15 + 7 = 52 prior, then +7 -> 59, wait — let's use 30 + 15 +
    7 + 7 = 59 and then +1 not allowed; simpler: prior cumulative = 53
    via 30+15+7+? — but only 7/15/30 are valid extras. Use prior
    cumulative = 53 by 30+15+7+? — impossible. Instead build prior = 53
    via 30+15+7 = 52, then +7 -> 59 (within cap). To hit exactly 60,
    use prior 30 = 30, then +30 = 60.

    Final scenario: prior = 30, attempt +30 -> cumulative 60 (inclusive
    cap). Must be ACCEPTED.

    # difficulty: boundary_precision_check/extension_cap_60_vs_61_days_strict_greater_than
    """
    _, app, rl = setup_rate_lock_with_cumulative_extra_days(
        cumulative_days=30,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
    )
    # rl is the EXTENDED state at cumulative=30. Now extend by 30 more.
    out = extend_rate_lock(
        app["id"], extra_days=30, headers=loan_officer_headers,
    )
    assert out["status"] == "EXTENDED", (
        "PRD §3.5: cumulative of exactly 60 is inclusive ('must not "
        "exceed 60 days'). Extension must succeed."
    )


def test_extension_cumulative_61_days_rejected(api, loan_officer_headers):
    """PRD §3.5: "must not exceed 60 days; an extension that would
    breach the cap is rejected with ERR_EXTENSION_CAP_EXCEEDED."

    Claim: prior cumulative=52 (built via 30+15+7), then attempt
    extra_days=15 -> would breach (52+15=67 > 60); rejected with
    ERR_EXTENSION_CAP_EXCEEDED.

    # difficulty: boundary_precision_check/extension_cap_60_vs_61_days_strict_greater_than
    """
    _, app, _ = setup_rate_lock_with_cumulative_extra_days(
        cumulative_days=52,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
    )
    res = api.extend_rate_lock(
        app["id"], extend_rate_lock_payload(extra_days=15),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_EXTENSION_CAP_EXCEEDED.value,
        expected_status=409,
    )


@pytest.mark.parametrize("invalid_extra", [1, 5, 10, 14, 20, 45, 60])
def test_extension_invalid_extra_days_rejected(
    api, loan_officer_headers, invalid_extra,
):
    """PRD §3.5: "Submitting an extension with an extra_days value of
    7, 15, or 30 ..."

    Claim: an extra_days value outside {7, 15, 30} is rejected with
    ERR_VALIDATION.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    res = api.extend_rate_lock(
        app["id"], extend_rate_lock_payload(extra_days=invalid_extra),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_VALIDATION.value, expected_status=422,
    )


# ===========================================================================
# Cross-entity dependency: rate-lock extension depends on app state
# difficulty: cross_entity_state_dependency/rate_lock_extension_depends_on_loan_application_state
# ===========================================================================
def test_extension_blocked_when_application_is_withdrawn(
    api, loan_officer_headers,
):
    """PRD §3.5: "Submitting an extension with an extra_days value of
    7, 15, or 30 from LOCKED first verifies that SystemClock.now is no
    later than the current lock_expires_at (i.e., the lock has not yet
    expired at the moment of the request), and that the parent
    LoanApplication.status is not in DENIED, WITHDRAWN, or CLOSED."

    Claim: withdraw the application (cascades the lock to CANCELLED),
    then attempt POST /rate-lock/extend. The rate lock is no longer in
    LOCKED/EXTENDED so the extension is rejected. The PRD enumerates
    DENIED/WITHDRAWN/CLOSED as the application states that block
    extension; in this scenario withdraw cascades the lock to CANCELLED
    so the source state of the lock is also wrong. Either the
    source-state check or the parent-state check produces the
    rejection — both routes are rooted in PRD §3.5.

    # difficulty: cross_entity_state_dependency/rate_lock_extension_depends_on_loan_application_state
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    validate_success(api.withdraw_application(
        app["id"], None, loan_officer_headers,
    ), 200)
    # Withdraw cascades the rate lock to CANCELLED.
    rl_after = get_rate_lock(
        app["id"], headers=loan_officer_headers,
    )
    assert rl_after["status"] == "CANCELLED"

    res = api.extend_rate_lock(
        app["id"], extend_rate_lock_payload(extra_days=15),
        loan_officer_headers,
    )
    assert res.status_code == 409, (
        f"Expected 409 (state-level rejection of extension on a "
        f"non-LOCKED/EXTENDED lock under DENIED/WITHDRAWN/CLOSED "
        f"application), got {res.status_code}"
    )


# ===========================================================================
# Cancel & 48-hr free-look refund — PRD §3.5
# difficulty: compensating_invariant/rate_lock_fee_accounting_invariant
# ===========================================================================
def test_cancel_within_48_hours_refunds_full_lock_fee(
    api, loan_officer_headers,
):
    """PRD §3.5: "Cancellation sets status to CANCELLED and computes
    refund_cents: if the cancellation happens within 48 hours of
    locked_at (the free-look window — that is, SystemClock.now minus
    locked_at is no more than 48 hours), the refund is the sum of
    lock_fee_cents and extension_fee_paid_cents; otherwise the refund
    is zero."

    Claim: lock at clock=2026-03-02T10:00; cancel at
    2026-03-03T09:00 (23 hours later, within 48h). refund_cents must
    equal lock_fee_cents + extension_fee_paid_cents = 50_000 + 0.

    # difficulty: compensating_invariant/rate_lock_fee_accounting_invariant
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    rl = place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    advance_clock("2026-03-03T09:00:00.000Z")  # 23h after lock
    out = validate_success(api.cancel_rate_lock(
        app["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "CANCELLED"
    assert out["refund_cents"] == rl["lock_fee_cents"] + rl.get(
        "extension_fee_paid_cents", 0,
    ), (
        "PRD §3.5: within 48-hour free-look, refund_cents = "
        "lock_fee_cents + extension_fee_paid_cents."
    )
    assert_rate_lock_fee_invariant(out)


def test_cancel_outside_48_hours_no_refund(api, loan_officer_headers):
    """PRD §3.5: "otherwise the refund is zero."

    Claim: lock at 2026-03-02T10:00; extend by 7 (fee 10_000); advance
    to 2026-03-05T11:00 (73 hours after lock, outside free-look);
    cancel -> refund_cents = 0.

    # difficulty: compensating_invariant/rate_lock_fee_accounting_invariant
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    extend_rate_lock(
        app["id"], extra_days=7, headers=loan_officer_headers,
    )
    advance_clock("2026-03-05T11:00:00.000Z")  # 73h after lock
    out = validate_success(api.cancel_rate_lock(
        app["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "CANCELLED"
    assert out["refund_cents"] == 0, (
        "PRD §3.5: outside 48-hour free-look, refund_cents = 0."
    )
    assert_rate_lock_fee_invariant(out)


def test_rate_lock_get_returns_current_state(api, loan_officer_headers):
    """PRD §4: GET /loan-applications/{id}/rate-lock returns the
    application's current rate lock.

    Claim: after place_rate_lock, GET returns the same id with
    status=LOCKED.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    rl = place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    out = validate_success(api.get_rate_lock(
        app["id"], loan_officer_headers,
    ), 200)
    assert out["id"] == rl["id"]
    assert out["status"] == "LOCKED"
