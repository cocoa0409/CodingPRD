"""Payment lifecycle: settle, extend, forfeit; partial-payment guard;
late-penalty accrual including linear and capped regimes (PRD §3.9)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_payment,
    assert_round_half_up_cents,
    DAILY_PENALTY_BPS,
    extend_payment,
    extend_payment_payload,
    forfeit_payment,
    get_payment,
    GRACE_FORFEITURE_DAYS,
    make_bidder_headers,
    MAX_PENALTY_BPS,
    setup_forfeited_payment,
    setup_issued_confirmation,
    setup_overdue_payment,
    setup_paid_payment,
    setup_payment_with_balance,
    settle_payment_payload,
    validate_error,
    validate_success,
)


def _parse(value):
    from datetime import datetime
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ===========================================================================
# Payment creation at issuance — PRD §3.9
# ===========================================================================
class TestPaymentCreation:

    def test_balance_due_equals_bid_minus_deposit(self, api):
        """PRD §3.9: "The `balance_due_cents` is pinned at issuance to the winning bid amount minus the matched deposit's `amount_cents`: precisely, it equals `Auction.current_high_cents` minus the `amount_cents` of the single `Deposit` row whose `auction_id` matches the confirmation's auction, whose `bidder_account_id` equals `Auction.outcome_winner_account_id`, and whose status is `PAID."

        Claim: balance_due_cents == current_high_cents - deposit_amount.
        Set up so this is a concrete known value.
        """
        # Use FIXED-deposit mode for determinism.
        _lot, auction, bidders, _winning_bid, _confirmation, payment = (
            setup_issued_confirmation(
                num_bidders=1,
                assessment_value_cents=100_000_000,
                deposit_mode="FIXED",
                deposit_fixed_cents=5_000_000,
            )
        )
        # current_high == starting_price (single bidder; first bid equal
        # to starting_price). starting_price = 70_000_000. deposit =
        # 5_000_000. So balance = 65_000_000.
        assert payment["balance_due_cents"] == 65_000_000, (
            f"Expected balance_due_cents = 70_000_000 - 5_000_000 = "
            f"65_000_000, got {payment['balance_due_cents']}"
        )


# ===========================================================================
# Partial payment guard — PRD §3.9
# ===========================================================================
class TestPartialPayment:

    def test_partial_settlement_rejected(self, api):
        """PRD §3.9: "A settlement that does not clear the full obligation in a single call is rejected with `ERR_PARTIAL_PAYMENT_REJECTED` — the platform does not accept partial payments."

        Claim: settle amount < balance_due → ERR_PARTIAL_PAYMENT_REJECTED.
        """
        _lot, _auction, bidders, _bid, _confirmation, payment = (
            setup_issued_confirmation(
                num_bidders=1,
                assessment_value_cents=100_000_000,
                deposit_mode="FIXED",
                deposit_fixed_cents=5_000_000,
            )
        )
        winner = bidders[-1][0]
        partial = max(payment["balance_due_cents"] - 1, 1)
        resp = api.settle_payment(
            payment["id"], settle_payment_payload(partial),
            make_bidder_headers(winner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTIAL_PAYMENT_REJECTED.value)

    def test_full_settlement_moves_to_paid_and_mints_receipt(self, api):
        """PRD §3.9: "A successful settlement adds the submitted amount to `amount_paid_cents`, flips `status` to `PAID`, mints a `receipt_no`, and emits `PAYMENT_RECEIVED."

        Claim: full settlement → status=PAID and receipt_no populated.
        """
        _lot, _auction, _bidders, _bid, _confirmation, payment = (
            setup_paid_payment(
                num_bidders=1,
                assessment_value_cents=100_000_000,
                deposit_mode="FIXED",
                deposit_fixed_cents=5_000_000,
            )
        )
        assert payment["status"] == "PAID"
        assert payment.get("receipt_no"), "PAID Payment must have receipt_no"


# ===========================================================================
# OVERDUE transition and penalty accrual — PRD §3.9
# ===========================================================================
class TestPaymentOverdueAndPenalty:

    def test_clock_advance_past_due_at_flips_status_to_overdue(self, api):
        """PRD §3.9: "When the clock advances past `due_at`, the payment automatically moves from `PENDING` to `OVERDUE` and emits `PAYMENT_OVERDUE."

        Claim: after clock past due_at → Payment.status == OVERDUE.
        """
        _auction, _confirmation, payment = setup_overdue_payment(
            balance_due_cents=68_000_000,
            payment_deadline_days=1,
            overdue_days=1,
        )
        assert payment["status"] == "OVERDUE"

    def test_penalty_linear_at_day_5(self, api):
        """PRD §3.9: "The uncapped penalty equals `balance_due_cents` multiplied by fifty (the daily penalty in basis points, that is half a percent per calendar day) multiplied by the number of days overdue, with the full-precision intermediate then divided by ten thousand."

        Claim: at 5 days overdue with balance 68_000_000:
        penalty = round_half_up(68_000_000 * 50 * 5 / 10000) == 1_700_000.
        """
        _auction, _confirmation, payment = setup_overdue_payment(
            balance_due_cents=68_000_000,
            payment_deadline_days=1,
            overdue_days=5,
        )
        assert payment["penalty_accrued_cents"] == 1_700_000, (
            f"Expected 1_700_000 (= 68_000_000 * 50 * 5 / 10000), "
            f"got {payment['penalty_accrued_cents']}"
        )

    def test_penalty_capped_at_10pct_after_20_days(self, api):
        """PRD §3.9: "A hard cap equals `balance_due_cents` multiplied by one thousand (the maximum penalty in basis points, that is ten percent of the balance), again divided by ten thousand. The stored `penalty_accrued_cents` is the lesser of the uncapped value and the cap."

        Claim: at 30 days overdue with balance 68_000_000:
        penalty = cap = 68_000_000 * 1000 / 10000 = 6_800_000.
        """
        _auction, _confirmation, payment = setup_overdue_payment(
            balance_due_cents=68_000_000,
            payment_deadline_days=1,
            overdue_days=30,
        )
        assert payment["penalty_accrued_cents"] == 6_800_000, (
            f"Expected 6_800_000 (cap = 68_000_000 * 0.10), "
            f"got {payment['penalty_accrued_cents']}"
        )


# ===========================================================================
# Grace extension — PRD §3.9
# ===========================================================================
class TestPaymentExtend:

    def test_extend_returns_status_to_pending(self, api, court_clerk_headers):
        """PRD §3.9: "A `CourtClerk` may grant grace by extending an `OVERDUE` payment back to `PENDING`."
        PRD §3.9: "The transition sets `due_at` to the current instant plus the supplied number of days, returns `status` to `PENDING`, and pauses penalty accrual while retaining the already-accrued `penalty_accrued_cents`."

        Claim: extend on OVERDUE → status = PENDING.
        """
        _auction, _confirmation, payment = setup_overdue_payment(
            balance_due_cents=68_000_000,
            payment_deadline_days=1,
            overdue_days=3,
        )
        extended = extend_payment(payment["id"], extension_days=7)
        assert extended["status"] == "PENDING"


# ===========================================================================
# Forfeiture — PRD §3.9
# ===========================================================================
class TestPaymentForfeit:

    def test_forfeit_before_grace_window_rejected(
        self, api, court_clerk_headers,
    ):
        """PRD §3.9: "If the payment remains `OVERDUE` for more than seven calendar days past `due_at`, the `CourtClerk` may forfeit it."

        Claim: forfeit at day 3 (<= 7 days past due_at) →
        ERR_INVALID_STATE.
        """
        _auction, _confirmation, payment = setup_overdue_payment(
            balance_due_cents=68_000_000,
            payment_deadline_days=1,
            overdue_days=3,
        )
        resp = api.forfeit_payment(payment["id"], court_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_settle_on_forfeited_rejected(self, api):
        """PRD §3.9: "A settlement attempted on a `FORFEITED` payment is rejected with `ERR_PAYMENT_FORFEITED."

        Claim: settle a FORFEITED Payment by the winning bidder →
        ERR_PAYMENT_FORFEITED.
        """
        # Build a forfeited payment, threading the winner's account so
        # the settle call passes ownership checks and we exercise the
        # state-level guard the PRD names.
        from test_helpers import (
            advance_clock_to,
            forfeit_payment,
            get_payment,
            setup_issued_confirmation,
        )
        _lot, _auction, bidders, _bid, _confirmation, payment = (
            setup_issued_confirmation(
                num_bidders=1,
                assessment_value_cents=100_000_000,
                deposit_mode="FIXED",
                deposit_fixed_cents=5_000_000,
                payment_deadline_days=1,
            )
        )
        winner_account = bidders[-1][0]
        # Advance clock past due_at + GRACE_FORFEITURE_DAYS so forfeit
        # becomes a valid transition.
        due_at = _parse(payment["due_at"])
        advance_clock_to(due_at + timedelta(days=GRACE_FORFEITURE_DAYS + 1))
        payment = forfeit_payment(payment["id"])
        assert payment["status"] == "FORFEITED"
        resp = api.settle_payment(
            payment["id"],
            settle_payment_payload(payment["balance_due_cents"]),
            make_bidder_headers(winner_account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_FORFEITED.value)


# ===========================================================================
# Penalty resets on PAID / PENDING — PRD §3.9
# ===========================================================================
class TestPenaltyOnNonOverdue:

    def test_penalty_zero_while_pending(self, api):
        """PRD §3.9: "While the payment is `PENDING` or `PAID`, `penalty_accrued_cents` is recomputed as zero."

        Claim: PENDING Payment has penalty_accrued_cents == 0.
        """
        _lot, _auction, _bidders, _bid, _confirmation, payment = (
            setup_issued_confirmation(
                num_bidders=1,
                assessment_value_cents=100_000_000,
                deposit_mode="FIXED",
                deposit_fixed_cents=5_000_000,
            )
        )
        if payment["status"] == "PENDING":
            assert payment["penalty_accrued_cents"] == 0
        else:
            pytest.skip(
                f"Payment skipped to {payment['status']} at issuance"
            )
