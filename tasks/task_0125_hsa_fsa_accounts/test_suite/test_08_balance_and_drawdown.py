"""Available-balance identity and drawdown waterfall — PRD §3.5, §3.6.

Coverage targets:
- available_balance = (contributions_ytd_cents + carryover_in_cents)
                     - claims_paid_ytd_cents.
- pay drawdown: current-year contributions first, then carryover.
- reverse drawdown undo: LIFO (current-year credit restored before
  carryover credit).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    available_balance,
    get_claim,
    get_plan_year,
    iso_datetime_utc,
    pay_claim,
    post_contribution,
    reverse_claim,
    setup_carryover_chain_with_successor,
    setup_health_fsa_carryover_full_chain,
    submit_claim,
    create_claim,
    seed_qualified_expense,
    approve_claim,
    validate_success,
)


# ===========================================================================
# Available balance identity — PRD §3.5
# ===========================================================================
class TestAvailableBalance:

    def test_available_balance_identity_after_contribution(self, api):
        """PRD §3.5: "The available balance is defined as the sum of
        contributions_ytd_cents and carryover_in_cents, less
        claims_paid_ytd_cents."

        Claim: after a single contribution, available_balance computed
        from the plan year's denormalized counters equals the
        contribution amount (no carryover, no claims paid).
        """
        from test_helpers import setup_funded_plan_year
        _, acct, py = setup_funded_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE", contribution_cents=80_000,
        )
        assert available_balance(py) == 80_000
        assert py["contributions_ytd_cents"] == 80_000
        assert py["carryover_in_cents"] == 0
        assert py["claims_paid_ytd_cents"] == 0


# ===========================================================================
# Drawdown waterfall — PRD §3.6
# ===========================================================================
class TestDrawdownWaterfall:

    def test_pay_draws_current_year_first(self, api):
        """PRD §3.6: "payment of a claim draws first from current-year
        contributions and only from carryover once the current-year
        pool is exhausted."

        Claim: with $1,000 current-year + $640 carryover, paying $500
        leaves carryover_consumed_cents == 0 (the entire payment came
        from current-year contributions).
        """
        # Build a HEALTH_FSA CARRYOVER chain so the successor PY has
        # carryover_in_cents > 0. Then add a $1_000 current-year
        # contribution.
        holder, acct, _pred, succ, qe = setup_health_fsa_carryover_full_chain(
            predecessor_year=2025, successor_year=2026,
            pred_contribution_cents=100_000,
            pred_pay_claim_cents=20_000,
        )
        # succ.carryover_in_cents should be 64_000 (min(80_000, 64_000)).
        assert succ["carryover_in_cents"] == 64_000
        # Add $1_000 current-year contribution to the successor.
        post_contribution(succ["id"], amount_cents=100_000,
                          source="PAYROLL")
        # Pay a $500 claim against the successor.
        from test_helpers import iso_datetime_utc as _iso
        claim = create_claim(
            account_holder=holder, account=acct,
            service_date=_iso(2026, 6, 15),
            expense_code=qe["code"], amount_cents=50_000,
        )
        submit_claim(claim["id"], account_holder=holder)
        approve_claim(claim["id"])
        pay_claim(claim["id"])
        py_after = get_plan_year(acct["id"], succ["id"])
        assert py_after["claims_paid_ytd_cents"] == 50_000
        # PRD §3.6: drawn_from_current = min(new_payment,
        # current_year_available). current_year_available = 100_000.
        # new_payment = 50_000. So drawn_from_current = 50_000 and
        # drawn_from_carryover = 0.
        assert py_after["carryover_consumed_cents"] == 0

    def test_pay_exceeds_current_year_consumes_carryover(self, api):
        """PRD §3.6: "drawn_from_carryover = new_payment minus that
        current-year draw."

        Claim: with current-year $1_000 and carryover $640, paying
        $1_200 -> claims_paid_ytd_cents == 120_000 and
        carryover_consumed_cents == 20_000.
        """
        holder, acct, _pred, succ, qe = setup_health_fsa_carryover_full_chain(
            predecessor_year=2025, successor_year=2026,
            pred_contribution_cents=100_000,
            pred_pay_claim_cents=20_000,
        )
        assert succ["carryover_in_cents"] == 64_000
        post_contribution(succ["id"], amount_cents=100_000,
                          source="PAYROLL")
        from test_helpers import iso_datetime_utc as _iso
        claim = create_claim(
            account_holder=holder, account=acct,
            service_date=_iso(2026, 6, 15),
            expense_code=qe["code"], amount_cents=120_000,
        )
        submit_claim(claim["id"], account_holder=holder)
        approve_claim(claim["id"])
        pay_claim(claim["id"])
        py_after = get_plan_year(acct["id"], succ["id"])
        assert py_after["claims_paid_ytd_cents"] == 120_000
        assert py_after["carryover_consumed_cents"] == 20_000


# ===========================================================================
# Reverse drawdown undo — PRD §3.5, §3.6
# ===========================================================================
class TestReverseDrawdown:

    def test_reverse_pay_undo_restores_counters(self, api):
        """PRD §3.5: "claims_paid_ytd_cents decreases by the original
        paid_amount_cents, carryover_consumed_cents is adjusted
        symmetrically per the drawdown rule (undo is LIFO with
        respect to drawdown — current-year credit is restored before
        carryover credit)".

        Claim: pay then reverse on a single claim returns both
        claims_paid_ytd_cents and carryover_consumed_cents to their
        pre-pay values (both zero in this fresh setup).
        """
        holder, acct, _pred, succ, qe = setup_health_fsa_carryover_full_chain(
            predecessor_year=2025, successor_year=2026,
            pred_contribution_cents=100_000,
            pred_pay_claim_cents=20_000,
        )
        post_contribution(succ["id"], amount_cents=100_000,
                          source="PAYROLL")
        from test_helpers import iso_datetime_utc as _iso
        claim = create_claim(
            account_holder=holder, account=acct,
            service_date=_iso(2026, 6, 15),
            expense_code=qe["code"], amount_cents=120_000,
        )
        submit_claim(claim["id"], account_holder=holder)
        approve_claim(claim["id"])
        pay_claim(claim["id"])
        py_after_pay = get_plan_year(acct["id"], succ["id"])
        assert py_after_pay["claims_paid_ytd_cents"] == 120_000
        assert py_after_pay["carryover_consumed_cents"] == 20_000
        # Reverse.
        reverse_claim(claim["id"])
        py_after_reverse = get_plan_year(acct["id"], succ["id"])
        assert py_after_reverse["claims_paid_ytd_cents"] == 0
        assert py_after_reverse["carryover_consumed_cents"] == 0
        # carryover_in_cents is unaffected: returned funds go back to
        # the pool.
        assert py_after_reverse["carryover_in_cents"] == 64_000
