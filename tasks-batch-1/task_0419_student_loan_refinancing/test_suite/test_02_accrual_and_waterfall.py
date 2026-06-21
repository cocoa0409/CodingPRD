"""Interest accrual (sum-then-round) and the payment waterfall, including
forbearance capitalization invariants.

Difficulty queue A: combinatorial_formula (interest accrual mode_b) and
compensating_invariant (capitalization + waterfall conservation).
"""
import pytest

from test_helpers import (
    get_success_data,
    setup_funded_loan,
    set_clock,
    post_payment,
    start_forbearance,
    list_forbearance_plans,
    get_loan,
    api_client,
)


class TestInterestAccrualSumThenRound:
    def test_accrual_sum_then_round_30_days(self, api):
        """PRD 3.9: "The newly accrued interest is the loan's
        principal_balance_cents at the start of the window multiplied by that
        daily rate multiplied by the number of days, and that single product is
        rounded half up to whole cents — the rounding happens once, after
        multiplying by the day count, not per day."

        principal 5,000,000, locked_apr 775 bps, 30 days:
        5,000,000 * (775/10000/365) * 30 = 31849.31... -> round_half_up 31849.
        A payment of exactly 31849 is fully consumed by interest.

        Design: Difficulty/combinatorial_formula/interest_accrual_sum_then_round_mode_b
        """
        bundle = setup_funded_loan(
            clock_at="2026-06-01T00:00:00Z",
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-ACC-A", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        assert loan["locked_apr_bps"] == 775, f"locked_apr expected 775, got {loan['locked_apr_bps']}"

        set_clock("2026-07-01T00:00:00Z")
        payment = post_payment(loan, 31849, "2026-07-01T00:00:00Z")
        assert payment["interest_portion_cents"] == 31849, (
            f"interest_portion should be 31849 (sum-then-round 30 days), got {payment['interest_portion_cents']}"
        )
        assert payment["principal_portion_cents"] == 0, (
            f"principal_portion should be 0, got {payment['principal_portion_cents']}"
        )

    def test_accrual_leaves_zero_accrued_after_full_interest_payment(self, api):
        """PRD 3.9: "The interest portion is subtracted from accrued_interest_cents
        and the principal portion is subtracted from principal_balance_cents."

        Design: Difficulty/combinatorial_formula/interest_accrual_sum_then_round_mode_b
        """
        bundle = setup_funded_loan(
            clock_at="2026-06-01T00:00:00Z",
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-ACC-B", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        set_clock("2026-07-01T00:00:00Z")
        post_payment(loan, 31849, "2026-07-01T00:00:00Z")
        loan_after = get_loan(loan["id"])
        assert loan_after["accrued_interest_cents"] == 0, (
            f"accrued_interest should be 0 after paying exactly the accrued interest, "
            f"got {loan_after['accrued_interest_cents']}"
        )


class TestPaymentWaterfallConservation:
    def test_waterfall_splits_payment_interest_first(self, api):
        """PRD 3.9: "The interest_portion_cents is the smaller of the payment's
        amount_cents and the refreshed accrued_interest_cents. The remainder is
        the payment amount minus that interest portion. The principal_portion_cents
        is the smaller of that remainder and the loan's principal_balance_cents."

        60,000 payment, 31,849 interest accrued -> interest 31,849, principal 28,151.

        Design: Difficulty/compensating_invariant/payment_waterfall_conserves_paid_vs_obligation_reduction
        """
        bundle = setup_funded_loan(
            clock_at="2026-06-01T00:00:00Z",
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-WF1", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        set_clock("2026-07-01T00:00:00Z")
        payment = post_payment(loan, 60000, "2026-07-01T00:00:00Z", paid_at="2026-07-01T00:00:00Z")
        assert payment["interest_portion_cents"] == 31849
        assert payment["principal_portion_cents"] == 28151

    def test_waterfall_conserves_cents_and_reduces_principal(self, api):
        """PRD 3.9: "The principal_portion_cents is the smaller of that remainder
        and the loan's principal_balance_cents."

        31,849 + 28,151 == 60,000 (no cent created or lost); principal 5,000,000 ->
        4,971,849; accrued 0.

        Design: Difficulty/compensating_invariant/payment_waterfall_conserves_paid_vs_obligation_reduction
        """
        bundle = setup_funded_loan(
            clock_at="2026-06-01T00:00:00Z",
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-WF2", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        set_clock("2026-07-01T00:00:00Z")
        payment = post_payment(loan, 60000, "2026-07-01T00:00:00Z", paid_at="2026-07-01T00:00:00Z")
        assert payment["interest_portion_cents"] + payment["principal_portion_cents"] == 60000, (
            "interest + principal portions must sum to the payment amount"
        )
        loan_after = get_loan(loan["id"])
        assert loan_after["principal_balance_cents"] == 4_971_849
        assert loan_after["accrued_interest_cents"] == 0
