"""Concurrency / race condition tests for the IP Management API (PRD §3.8).

Only tests where PRD §3.8 explicitly names BOTH the winner-determination rule
and the loser's specific error_id are generated. PRD names the error_id for
every race in §3.8, so each race below has a named loser-id.
"""

from test_helpers import (
    ApiErrorId,
    advance_clock_days_fixture,
    run_race,
    setup_registered_ip_with_annual_fee,
    validate_error,
)


class TestConcurrentPay:
    """PRD §3.8 — two /pay calls on the same AnnualFeeSchedule."""

    def test_two_pays_one_wins_one_fee_already_paid(
        self, api, finance_manager_headers
    ):
        """PRD §3.8: "When two clients call the pay endpoint on the same
        `AnnualFeeSchedule`, exactly one wins by first-writer on
        `AnnualFeeSchedule.paid_at` and the loser receives
        `ERR_FEE_ALREADY_PAID`."

        Claim: in a concurrent race of two /pay calls on the same fee,
        exactly one succeeds (2xx) and the other receives
        ERR_FEE_ALREADY_PAID (409).
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=10
        )
        fee_id = seed["annual_fee"]["id"]
        # Use two distinct opaque finance-manager headers to avoid any
        # client-side request deduplication artifacts.
        results = run_race(
            lambda: api.pay_annual_fee(fee_id, {}, finance_manager_headers),
            lambda: api.pay_annual_fee(fee_id, {}, finance_manager_headers),
        )
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) == 1, (
            f"PRD §3.8 requires exactly one success and one failure; "
            f"got {len(successes)} successes, {len(failures)} failures"
        )
        assert len(failures) == 1
        # Loser carries the PRD-named error_id.
        validate_error(failures[0], ApiErrorId.ERR_FEE_ALREADY_PAID)
