"""Compensating-action invariants: the wallet/payout ledger after
REQUEST→CONFIRM→CANCEL, and the claim-reserve invariant after SUBMIT→WITHDRAW.
Plus optimistic-concurrency stale-version rejection on
POST /api/v1/bookings/{id}/cancel.

Covers queue A compensating_invariant instances and queue B
optimistic_concurrency corner instance.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    make_owner_headers,
    setup_confirmed_booking,
    setup_submitted_claim,
    cancel_confirmed_booking_with_occ,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


# ---- Queue A: compensating_invariant — money ledger -------------------------

def test_cancel_confirmed_booking_refunds_full_quote_to_wallet(api):
    """PRD §3.5: "On a successful confirmed-side cancel the booking's
    `status` becomes `CANCELLED`, `cancellation_reason` is recorded,
    `Booking.version` increments, the sitter's `pending_payout_cents`
    is decreased by the booking's `provisional_sitter_payout_cents`
    (reservation reversed) and `Sitter.version` bumps, and the owner is
    made whole: `Owner.wallet_credit_cents` is increased by
    `booking_quote_cents` minus `wallet_credit_applied_cents` (the
    principal refund as wallet credit) and then by
    `wallet_credit_applied_cents` (the previously-applied credit
    restored), so the net effect is that the owner's wallet is credited
    by the full `booking_quote_cents`."

    Design: Difficulty/compensating_invariant/cancel_confirmed_booking_preserves_money_ledger_invariant
    """
    owner, sitter, pet, mg, booking = setup_confirmed_booking(
        clock_iso="2026-06-15T08:00:00Z",
        mg_scheduled_at="2026-06-15T07:30:00Z",
        booking_start_at="2026-06-15T09:00:00Z",
        booking_end_at="2026-06-15T10:00:00Z",
        service_type="WALK_60MIN",
    )
    quote = booking["booking_quote_cents"]
    cancelled = cancel_confirmed_booking_with_occ(
        owner, booking, expected_version=booking["version"], reason="owner changed plans"
    )
    assert cancelled["status"] == "CANCELLED"
    o_after = validate_success(api.get_owner(owner["id"], PLATFORM_ADMIN), 200)
    # Owner wallet receives the full quote back (started at 0, no credit applied).
    assert o_after["wallet_credit_cents"] == quote


def test_cancel_confirmed_booking_reverses_pending_payout(api):
    """PRD §3.5: "On a successful confirmed-side cancel the booking's
    `status` becomes `CANCELLED`, `cancellation_reason` is recorded,
    `Booking.version` increments, the sitter's `pending_payout_cents`
    is decreased by the booking's `provisional_sitter_payout_cents`
    (reservation reversed) and `Sitter.version` bumps, and the owner
    is made whole: `Owner.wallet_credit_cents` is increased by
    `booking_quote_cents` minus `wallet_credit_applied_cents` (the
    principal refund as wallet credit) and then by
    `wallet_credit_applied_cents` (the previously-applied credit
    restored), so the net effect is that the owner's wallet is
    credited by the full `booking_quote_cents`."

    The Sitter side of the same compensating invariant: after a CONFIRMED
    cancellation, the previously-reserved provisional payout is removed
    from Sitter.pending_payout_cents. (Sitter started at 0, so post-
    cancel pending_payout_cents must return to 0.)

    Design: Difficulty/compensating_invariant/cancel_confirmed_booking_preserves_money_ledger_invariant
    """
    owner, sitter, pet, mg, booking = setup_confirmed_booking(
        clock_iso="2026-06-15T08:00:00Z",
        mg_scheduled_at="2026-06-15T07:30:00Z",
        booking_start_at="2026-06-15T09:00:00Z",
        booking_end_at="2026-06-15T10:00:00Z",
        service_type="WALK_60MIN",
    )
    s_pre = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_pre["pending_payout_cents"] == booking["provisional_sitter_payout_cents"]
    cancelled = cancel_confirmed_booking_with_occ(
        owner, booking, expected_version=booking["version"],
    )
    assert cancelled["status"] == "CANCELLED"
    s_after = validate_success(api.get_sitter(sitter["id"], PLATFORM_ADMIN), 200)
    assert s_after["pending_payout_cents"] == 0


# ---- Queue A: compensating_invariant — claim reserve ------------------------

def test_withdraw_submitted_claim_terminates_claim_in_withdrawn(api):
    """PRD §3.8: "The owner may also withdraw a still-submitted claim,
    advancing `SUBMITTED → WITHDRAWN`; later states cannot be withdrawn."

    Design: Difficulty/compensating_invariant/withdraw_submitted_claim_preserves_claim_pool_invariant
    """
    owner, sitter, pet, mg, booking, kh, claim = setup_submitted_claim(
        claim_amount_cents=12000,
        completed_kwargs={"owner_rating": 4,
                          "clock_iso": "2026-06-16T08:00:00Z",
                          "mg_scheduled_at": "2026-06-16T07:30:00Z",
                          "booking_start_at": "2026-06-16T09:00:00Z",
                          "booking_end_at": "2026-06-16T10:00:00Z"},
    )
    assert claim["status"] == "SUBMITTED"
    withdrawn = validate_success(
        api.withdraw_insurance_claim(claim["id"], make_owner_headers(owner["id"])),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN"


def test_withdraw_excludes_claim_from_active_reserve_pool_listing(api):
    """PRD §3.8: "The owner may also withdraw a still-submitted claim,
    advancing `SUBMITTED → WITHDRAWN`; later states cannot be withdrawn."
    PRD §4 table row: `GET /api/v1/insurance-claims` "List InsuranceClaims
    filtered by `booking_id`, `sitter_id_snapshot`, `status`."

    The conserved-quantity aspect of the same compensating invariant:
    after withdraw, a status-filtered list of {SUBMITTED, UNDER_REVIEW,
    APPROVED} returns zero items for the affected Sitter — the
    provisional_payout_cents that had been pinned at SUBMIT no longer
    contributes to any active-reserve pool (because the WITHDRAWN status
    is outside the filter set).

    Design: Difficulty/compensating_invariant/withdraw_submitted_claim_preserves_claim_pool_invariant
    """
    # File claim against IN_PROGRESS booking so total_completed_bookings stays
    # 0 and no sitter_tier_score recompute has fired — sitter remains BRONZE.
    # sitter_tier_snapshot pinned at submit is BRONZE, deductible 10000.
    owner, sitter, pet, mg, booking, kh, claim = setup_submitted_claim(
        claim_amount_cents=12000,
        booking_phase="in_progress",
        completed_kwargs={"clock_iso": "2026-06-16T08:00:00Z",
                          "mg_scheduled_at": "2026-06-16T07:30:00Z",
                          "booking_start_at": "2026-06-16T09:00:00Z",
                          "booking_end_at": "2026-06-16T10:00:00Z"},
    )
    assert claim["provisional_payout_cents"] == 2000  # BRONZE: max(0, 12000-10000)
    validate_success(
        api.withdraw_insurance_claim(claim["id"], make_owner_headers(owner["id"])), 200
    )
    # Each active-pool status filter must now return zero claims for this Sitter.
    for active_status in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
        res = api.list_insurance_claims(
            PLATFORM_ADMIN,
            params={"sitter_id_snapshot": sitter["id"], "status": active_status},
        )
        data, meta = validate_paginated(res)
        assert data == [], (
            f"Expected empty list for status={active_status}; got {data!r}"
        )
        assert meta["total_count"] == 0


# ---- Queue B: optimistic_concurrency — stale-version rejection --------------

def test_cancel_confirmed_booking_with_stale_version_rejected(api):
    """PRD §2.6: "Cancelling a confirmed booking is the only operation
    that takes an explicit optimistic-concurrency token. The cancel
    request body must include `expected_booking_version` carrying the
    client's last observed `version` of the target booking. If that
    value does not match the booking's current `version` at the moment
    the server processes the request, the cancel is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_on_cancel
    """
    owner, sitter, pet, mg, booking = setup_confirmed_booking(
        clock_iso="2026-07-05T08:00:00Z",
        mg_scheduled_at="2026-07-05T07:30:00Z",
        booking_start_at="2026-07-05T09:00:00Z",
        booking_end_at="2026-07-05T09:30:00Z",
        service_type="WALK_30MIN",
    )
    stale_version = booking["version"] - 1
    res = api.cancel_booking(
        booking["id"],
        {"reason": "stale cancel", "expected_booking_version": stale_version},
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_STALE_VERSION")
