"""Settlement, payment event ingest, identity idempotency.

PRD §3.8 (Settlement, Inter-Department Transfer, External Events),
§2.11 (Event Ingest Idempotency).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_clock_to,
    check_in,
    check_out,
    create_user,
    get_lab,
    identity_verified_payload,
    make_reservation,
    payment_confirmed_payload,
    setup_basic_scenario,
    setup_scenario_with_reservation,
    validate_error,
    validate_success,
    verify_user_identity,
)


# ===========================================================================
# Periodic settlement (PRD §3.8)
# ===========================================================================
class TestSettleLab:
    """PRD §3.8: 'A periodic settlement initiated by a PlatformAdmin adds
    the current settlement_balance_cents to lifetime_settled_cents and
    zeros the balance — but only when the balance is strictly greater
    than 0; an attempt to settle a zero or negative balance is rejected
    with ERR_NOTHING_TO_SETTLE at 422.'
    """

    def test_settle_zero_balance_rejected(self, api):
        """PRD §3.8: 'an attempt to settle a zero or negative balance is
        rejected with ERR_NOTHING_TO_SETTLE at 422'."""
        s = setup_basic_scenario()
        res = api.settle_lab(s["lab"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_NOTHING_TO_SETTLE.value)

    def test_settle_nonzero_balance_zeros_balance(self, api):
        """PRD §3.8: 'adds the current settlement_balance_cents to
        lifetime_settled_cents and zeros the balance'."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        # After reservation create, balance > 0 (accrual).
        before = get_lab(s["lab"]["id"])
        assert before["settlement_balance_cents"] > 0
        accrued = before["settlement_balance_cents"]
        res = api.settle_lab(s["lab"]["id"], ADMIN)
        lab = validate_success(res, 200)
        assert lab["settlement_balance_cents"] == 0
        assert lab["lifetime_settled_cents"] == (
            before["lifetime_settled_cents"] + accrued
        )


# ===========================================================================
# Identity-verified idempotency (PRD §2.11, §3.1)
# ===========================================================================
class TestIdentityVerifiedIdempotency:
    """PRD §3.1 / §2.11: 'A repeated call with the same external_user_id
    for identity verification ... must produce a success response
    equivalent to the original; a repeated call whose payload
    contradicts the previously recorded outcome is rejected with
    ERR_IDEMPOTENCY_CONFLICT at 409.'
    """

    def test_repeat_identity_verified_is_noop_success(self, api):
        """PRD §3.1: 'a second VERIFIED event for the same user is a
        no-op success'."""
        u = create_user()
        verify_user_identity(u)
        res = api.deliver_identity_verified(
            identity_verified_payload(
                external_user_id=u["external_user_id"],
            ),
            ADMIN,
        )
        validate_success(res, 200)


# ===========================================================================
# Payment confirmed idempotency (PRD §3.8, §2.11)
# ===========================================================================
class TestPaymentConfirmedIdempotency:
    """PRD §3.8 / §2.11: 'The ingest is idempotent on the combination of
    reservation_id and external_payment_id: a repeated event with the
    same pair is a no-op; a repeated event with the same reservation_id
    but a contradictory external_payment_id (or vice versa) yields
    ERR_IDEMPOTENCY_CONFLICT.'
    """

    def test_payment_confirmed_replay_succeeds(self, api):
        """PRD §3.8: 'a repeated event with the same pair is a no-op'."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        ref = "ext_pay_test_001"
        first = api.deliver_payment_confirmed(
            payment_confirmed_payload(
                reservation_id=s["reservation"]["id"],
                external_payment_id=ref,
            ),
            ADMIN,
        )
        validate_success(first, 200)
        second = api.deliver_payment_confirmed(
            payment_confirmed_payload(
                reservation_id=s["reservation"]["id"],
                external_payment_id=ref,
            ),
            ADMIN,
        )
        validate_success(second, 200)

    def test_payment_confirmed_conflicting_payload_rejected(self, api):
        """PRD §3.8: 'a repeated event with the same reservation_id but a
        contradictory external_payment_id ... yields
        ERR_IDEMPOTENCY_CONFLICT'."""
        s = setup_scenario_with_reservation(
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        first = api.deliver_payment_confirmed(
            payment_confirmed_payload(
                reservation_id=s["reservation"]["id"],
                external_payment_id="ext_pay_A",
            ),
            ADMIN,
        )
        validate_success(first, 200)
        res = api.deliver_payment_confirmed(
            payment_confirmed_payload(
                reservation_id=s["reservation"]["id"],
                external_payment_id="ext_pay_B",
            ),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT.value)
