"""Interest reserve accrual: day-count variants, capitalization order, depletion."""
from test_helpers import (
    TEST_USERS,
    get_loan,
    run_accrual,
    setup_funded_scenario,
    validate_paginated,
)

SERVICER = TEST_USERS["loan_servicer_headers"]


class TestDayCountConventionDivergence:
    def _accrue_both_variants(self):
        """Two loans identical except day-count convention; accrue [01-31, 03-01)."""
        sc_actual = setup_funded_scenario(reserve_cents=200_000,
                                          day_count="ACTUAL_360")
        sc_thirty = setup_funded_scenario(reserve_cents=200_000,
                                          day_count="THIRTY_360")
        entry_a = run_accrual(sc_actual["loan"]["id"], "2026-01-31", "2026-03-01")
        entry_b = run_accrual(sc_thirty["loan"]["id"], "2026-01-31", "2026-03-01")
        return sc_actual, sc_thirty, entry_a, entry_b

    def test_day_count_convention_divergence_days_and_due(self, api):
        """PRD §3.8: "Under `ACTUAL_360`, the count is the actual number of
        calendar days from `period_start_date` to `period_end_date`, the end date
        excluded, so a period spanning February counts 28 or 29 days for that
        month. Under `THIRTY_360`, every month counts thirty days: the start
        day-of-month is capped at 30; the end day-of-month is likewise capped at 30
        — explicitly, an end day of 31 paired with a start day of 30 or 31 is
        counted as 30; and the count is 360 times the difference in years, plus 30
        times the difference in months, plus the capped end day minus the capped
        start day. Identical period dates therefore produce a different
        `interest_due_cents` under the two conventions."

        Design: Difficulty/dual_variant_calc/interest_day_count_convention_divergence
        """
        _sa, _sb, entry_a, entry_b = self._accrue_both_variants()
        # ACTUAL_360 over [2026-01-31, 2026-03-01): 29 calendar days.
        assert entry_a["days_counted"] == 29
        # 9500000 * 1200/10000 * 29/360 = 91833.33 -> round half up 91833
        assert entry_a["interest_due_cents"] == 91_833
        # THIRTY_360: 360*0 + 30*(3-1) + (1-30) = 31 days.
        assert entry_b["days_counted"] == 31
        # 9500000 * 1200/10000 * 31/360 = 98166.67 -> round half up 98167
        assert entry_b["interest_due_cents"] == 98_167

    def test_day_count_convention_divergence_reserve_balances(self, api):
        """PRD §3.8: "Fourth, `paid_from_reserve_cents` is the lesser of
        `interest_due_cents` and the reserve balance immediately before the run,
        and the reserve is drawn down by that amount."

        Design: Difficulty/dual_variant_calc/interest_day_count_convention_divergence
        """
        sc_a, sc_b, _ea, _eb = self._accrue_both_variants()
        loan_a = get_loan(sc_a["loan"]["id"])
        loan_b = get_loan(sc_b["loan"]["id"])
        assert loan_a["interest_reserve_balance_cents"] == 200_000 - 91_833
        assert loan_b["interest_reserve_balance_cents"] == 200_000 - 98_167


class TestCapitalizationEvaluationOrder:
    def test_capitalization_run1_reserve_partially_covers(self, api):
        """PRD §3.8: "First the accrual base is fixed as the loan's
        `principal_disbursed_cents` plus its `interest_capitalized_cents`, taken at
        the start of the run before anything this run capitalizes."
        PRD §3.8: "Fourth, `paid_from_reserve_cents` is the lesser of
        `interest_due_cents` and the reserve balance immediately before the run,
        and the reserve is drawn down by that amount. Fifth, the shortfall —
        `interest_due_cents` minus `paid_from_reserve_cents` — is added to
        `interest_capitalized_cents` whenever it is positive, joining the base of
        the next run."

        Design: Difficulty/combinatorial_formula/interest_capitalization_evaluation_order
        """
        sc = setup_funded_scenario(reserve_cents=50_000)
        entry = run_accrual(sc["loan"]["id"], "2026-04-01", "2026-05-01")
        # 30-day run on base 9500000 at 1200 bps -> due 95000.
        assert entry["interest_due_cents"] == 95_000
        assert entry["paid_from_reserve_cents"] == 50_000, (
            "The reserve covers only its 50000 balance"
        )
        assert entry["capitalized_cents"] == 45_000

    def test_capitalization_run2_base_includes_prior_shortfall(self, api):
        """PRD §3.8: "Fifth, the shortfall — `interest_due_cents` minus
        `paid_from_reserve_cents` — is added to `interest_capitalized_cents`
        whenever it is positive, joining the base of the next run. Finally, when a
        run leaves `interest_reserve_balance_cents` at zero,
        `interest_reserve_depleted` is set true."

        Design: Difficulty/combinatorial_formula/interest_capitalization_evaluation_order
        """
        sc = setup_funded_scenario(reserve_cents=50_000)
        run_accrual(sc["loan"]["id"], "2026-04-01", "2026-05-01")
        entry2 = run_accrual(sc["loan"]["id"], "2026-05-01", "2026-05-31")
        # Run 2 base = 9500000 + 45000 = 9545000; 30 days -> due 95450.
        assert entry2["interest_due_cents"] == 95_450, (
            "The prior run's capitalized shortfall joins this run's base"
        )
        assert entry2["paid_from_reserve_cents"] == 0, "Reserve already at zero"
        assert entry2["capitalized_cents"] == 95_450

        loan = get_loan(sc["loan"]["id"])
        assert loan["interest_capitalized_cents"] == 140_450
        assert loan["interest_reserve_balance_cents"] == 0
        assert loan["interest_reserve_depleted"] is True


class TestExactDepletionBoundary:
    def test_reserve_exact_depletion_zero_capitalization(self, api):
        """PRD §3.8: "Fourth, `paid_from_reserve_cents` is the lesser of
        `interest_due_cents` and the reserve balance immediately before the run,
        and the reserve is drawn down by that amount."
        PRD §3.8: "Finally, when a run leaves `interest_reserve_balance_cents` at
        zero, `interest_reserve_depleted` is set true."

        Design: Difficulty/boundary_precision_check/interest_reserve_exact_depletion_boundary
        """
        sc = setup_funded_scenario(reserve_cents=95_000)
        entry = run_accrual(sc["loan"]["id"], "2026-04-01", "2026-05-01")
        # due == reserve exactly (95000 == 95000): pay in full, capitalize nothing.
        assert entry["interest_due_cents"] == 95_000
        assert entry["paid_from_reserve_cents"] == 95_000
        assert entry["capitalized_cents"] == 0, (
            "Equality is the boundary: no shortfall, no capitalization"
        )
        assert entry["reserve_balance_after_cents"] == 0

        loan = get_loan(sc["loan"]["id"])
        assert loan["interest_reserve_depleted"] is True, (
            "Landing exactly on zero sets the depleted flag"
        )

    def test_reserve_depleted_next_run_fully_capitalizes(self, api):
        """PRD §3.8: "Fifth, the shortfall — `interest_due_cents` minus
        `paid_from_reserve_cents` — is added to `interest_capitalized_cents`
        whenever it is positive, joining the base of the next run."
        PRD §3.8: "Every run writes exactly one `INTEREST_PAYMENT` entry — even
        when the computed `interest_due_cents` is zero — and additionally writes
        one `CAPITALIZATION` entry if and only if the shortfall was positive".

        Design: Difficulty/boundary_precision_check/interest_reserve_exact_depletion_boundary
        """
        sc = setup_funded_scenario(reserve_cents=95_000)
        run_accrual(sc["loan"]["id"], "2026-04-01", "2026-05-01")
        entry2 = run_accrual(sc["loan"]["id"], "2026-05-01", "2026-05-31")
        assert entry2["paid_from_reserve_cents"] == 0
        assert entry2["capitalized_cents"] == 95_000, (
            "With the reserve at zero the full due capitalizes"
        )

        loan = get_loan(sc["loan"]["id"])
        assert loan["interest_capitalized_cents"] == 95_000


class TestReserveAccountConservation:
    def test_interest_reserve_ledger_entries_signed(self, api):
        """PRD §3.8: "The `amount_cents` is a signed reserve delta: positive for
        `INITIAL_DEPOSIT`, negative for `INTEREST_PAYMENT` (by the amount paid from
        the reserve), negative for `SWEEP`, and zero for `CAPITALIZATION`."
        PRD §3.8: "Each entry bears a per-loan monotone `entry_index` starting at 1
        — the `INITIAL_DEPOSIT` written at origination is index 1".

        Design: Difficulty/compensating_invariant/interest_reserve_account_conservation
        """
        sc = setup_funded_scenario(reserve_cents=200_000)
        entry = run_accrual(sc["loan"]["id"], "2026-04-01", "2026-05-01")
        assert entry["paid_from_reserve_cents"] == 95_000

        entries, meta = validate_paginated(
            api.list_interest_ledger(sc["loan"]["id"], SERVICER))
        assert meta["total_count"] == 2
        deposit, payment = entries[0], entries[1]
        assert deposit["entry_index"] == 1
        assert deposit["entry_type"] == "INITIAL_DEPOSIT"
        assert deposit["amount_cents"] == 200_000
        assert payment["entry_index"] == 2
        assert payment["entry_type"] == "INTEREST_PAYMENT"
        assert payment["amount_cents"] == -95_000, (
            "INTEREST_PAYMENT carries the negative of the amount paid"
        )

    def test_interest_reserve_account_conservation(self, api):
        """PRD §3.1: "The `interest_reserve_balance_cents` is initialized to
        `interest_reserve_initial_cents` and thereafter always equals the initial
        reserve plus the signed sum of every ledger entry's `amount_cents`."

        Design: Difficulty/compensating_invariant/interest_reserve_account_conservation
        """
        sc = setup_funded_scenario(reserve_cents=200_000)
        run_accrual(sc["loan"]["id"], "2026-04-01", "2026-05-01")

        loan = get_loan(sc["loan"]["id"])
        assert loan["interest_reserve_balance_cents"] == 105_000
        paid_out = 95_000
        swept = loan["interest_reserve_swept_cents"]
        assert swept == 0
        assert loan["interest_reserve_initial_cents"] == (
            loan["interest_reserve_balance_cents"] + paid_out + swept
        ), "200000 == 105000 (balance) + 95000 (paid) + 0 (swept)"
