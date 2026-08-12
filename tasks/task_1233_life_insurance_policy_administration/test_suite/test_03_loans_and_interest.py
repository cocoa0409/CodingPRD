"""Policy loans: origination availability, interest accrual, repayment."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_policy_loan,
    create_funded_policy,
    create_policy_with_loan,
    get_policy,
    get_success_data,
    list_ledger,
    make_policyholder_headers,
    originate_loan,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _ph(bundle):
    return make_policyholder_headers(bundle["insured"]["id"])


class TestLoanInterestAccrual:
    def test_accrual_across_anniversary_keeps_principal_flat(self, api):
        """PRD §3.6: "Within each period the day count is taken, and the period's interest is the
        loan's outstanding principal multiplied by the annual rate of 500
        basis points (that is, by 500 divided by 10000), multiplied by the day
        count, divided by 365, and rounded half-up to whole cents for that
        period. Under the default **non-capitalizing** treatment, each
        period's interest accumulates into `accrued_interest_cents` and the
        principal never changes, so every period computes interest on the same
        principal."

        366-day walk from 2026-05-01 to 2027-05-02 splits at the 2027-05-01
        anniversary: 250000 (365 days) + 685 (1 day) = 250685.

        Design: Difficulty/dual_variant_calc/loan_interest_capitalizing_vs_non_capitalizing
        """
        bundle, loan = create_policy_with_loan(
            5_000_000, cash_to_add=10_000_000, premium_mode="ANNUAL",
            date_of_birth="1990-01-01")
        policy_id = bundle["policy"]["id"]

        set_clock("2027-05-02T00:00:00Z")
        after = validate_success(api.accrue_interest(policy_id, loan["id"], ADMIN))
        assert_policy_loan(after)
        assert after["outstanding_principal_cents"] == 5_000_000, (
            "non-capitalizing default: principal never changes")
        assert after["accrued_interest_cents"] == 250_685, (
            "250000 (first 365-day period) + 685 (1 day) = 250685")
        assert after["last_accrual_date"].startswith("2027-05-02")

        rows, _meta = validate_paginated(
            api.list_loan_accruals(policy_id, loan["id"], AGENT))
        assert len(rows) == 2, "one persisted row per anniversary-split window"
        assert sum(r["interest_accrued_cents"] for r in rows) == 250_685
        assert all(r["principal_base_cents"] == 5_000_000 for r in rows), (
            "every period computes interest on the same principal")

    def test_accrual_partial_year_single_window(self, api):
        """PRD §3.6: "Within each period the day count is taken, and the period's interest is the
        loan's outstanding principal multiplied by the annual rate of 500
        basis points (that is, by 500 divided by 10000), multiplied by the day
        count, divided by 365, and rounded half-up to whole cents for that
        period."
        PRD §3.6: "Every processed window is persisted as an accrual row".

        184 days from 2026-05-01 to 2026-11-01: round_half_up(5000000 x 0.05 x
        184 / 365) = 126027.

        Design: Difficulty/dual_variant_calc/loan_interest_capitalizing_vs_non_capitalizing
        """
        bundle, loan = create_policy_with_loan(
            5_000_000, cash_to_add=10_000_000, premium_mode="ANNUAL")
        policy_id = bundle["policy"]["id"]

        set_clock("2026-11-01T00:00:00Z")
        after = validate_success(api.accrue_interest(policy_id, loan["id"], ADMIN))
        assert after["accrued_interest_cents"] == 126_027
        assert after["outstanding_principal_cents"] == 5_000_000
        rows, _meta = validate_paginated(
            api.list_loan_accruals(policy_id, loan["id"], AGENT))
        assert len(rows) == 1, "no anniversary crossed: a single accrual window"
        assert rows[0]["days_accrued"] == 184
        assert rows[0]["interest_accrued_cents"] == 126_027


class TestLoanAvailabilityBoundary:
    def test_loan_at_exact_available_value_succeeds(self, api):
        """PRD §3.6: "the requested amount must not exceed the policy's `cash_value_cents` minus its
        aggregate `outstanding_loan_principal_cents` minus its aggregate
        `accrued_loan_interest_cents`; a larger request is rejected with
        `ERR_INSUFFICIENT_CASH_VALUE` (HTTP 402)."

        Boundary: requested == available is not "larger", so it succeeds.

        Design: Difficulty/boundary_precision_check/loan_availability_exact_amount_boundary
        """
        bundle = create_funded_policy(10_000_000, premium_mode="ANNUAL")
        policy = get_policy(bundle["policy"]["id"])
        available = (policy["cash_value_cents"]
                     - policy["outstanding_loan_principal_cents"]
                     - policy["accrued_loan_interest_cents"])
        resp = api.create_loan(bundle["policy"]["id"], available, _ph(bundle))
        loan = validate_success(resp, expected_status=201)
        assert loan["status"] == "ACTIVE"
        assert loan["outstanding_principal_cents"] == available

    def test_loan_one_cent_over_available_rejected(self, api):
        """PRD §3.6: "the requested amount must not exceed the policy's `cash_value_cents` minus its
        aggregate `outstanding_loan_principal_cents` minus its aggregate
        `accrued_loan_interest_cents`; a larger request is rejected with
        `ERR_INSUFFICIENT_CASH_VALUE` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/loan_availability_exact_amount_boundary
        """
        bundle = create_funded_policy(10_000_000, premium_mode="ANNUAL")
        policy_id = bundle["policy"]["id"]
        available = get_policy(policy_id)["cash_value_cents"]
        first = validate_success(api.create_loan(policy_id, available, _ph(bundle)),
                                 expected_status=201)
        assert first["status"] == "ACTIVE"
        # Every cent of value is now borrowed; one more cent exceeds availability.
        resp = api.create_loan(policy_id, 1, _ph(bundle))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CASH_VALUE)


class TestLoanRepaymentConservation:
    def test_origination_conserves_cash_plus_outstanding(self, api):
        """PRD §3.6: "The policy's aggregate `outstanding_loan_principal_cents` increases by the
        requested amount, a `LOAN_DISBURSEMENT` debit entry posts to the
        ledger, and the policy's cash value is adjusted accordingly."
        PRD §2.7: "an `entry_type`, a signed `amount_cents` (positive for credits, negative for
        debits)".

        Design: Difficulty/compensating_invariant/loan_origination_repayment_conserves_cash_value_plus_outstanding
        """
        bundle = create_funded_policy(10_000_000, premium_mode="ANNUAL")
        policy_id = bundle["policy"]["id"]
        before = get_policy(policy_id)
        sum_before = (before["cash_value_cents"]
                      + before["outstanding_loan_principal_cents"])

        loan = originate_loan(bundle, 3_000_000)

        after = get_policy(policy_id)
        assert after["outstanding_loan_principal_cents"] == (
            before["outstanding_loan_principal_cents"] + 3_000_000)
        assert after["cash_value_cents"] == before["cash_value_cents"] - 3_000_000
        assert (after["cash_value_cents"] + after["outstanding_loan_principal_cents"]
                == sum_before), "cash_value + outstanding principal is conserved"
        entries = list_ledger(policy_id)
        disb = [e for e in entries if e["entry_type"] == "LOAN_DISBURSEMENT"]
        assert len(disb) == 1 and disb[0]["amount_cents"] == -3_000_000, (
            "disbursement posts as a negative (debit) ledger entry")

    def test_full_repayment_restores_conserved_sum(self, api):
        """PRD §3.6: "When cumulative repayments cover the loan's outstanding principal plus its
        accrued interest in full, the loan moves from `ACTIVE` to `REPAID`;
        the policy's aggregate `outstanding_loan_principal_cents` is
        decremented by the loan's outstanding principal and its aggregate
        `accrued_loan_interest_cents` by the loan's accrued interest, and a
        `LOAN_REPAYMENT_CREDIT` entry posts to the ledger."

        Same-day repayment accrues zero days of interest, so principal alone
        settles the loan.

        Design: Difficulty/compensating_invariant/loan_origination_repayment_conserves_cash_value_plus_outstanding
        """
        bundle = create_funded_policy(10_000_000, premium_mode="ANNUAL")
        policy_id = bundle["policy"]["id"]
        before = get_policy(policy_id)
        sum_before = (before["cash_value_cents"]
                      + before["outstanding_loan_principal_cents"])

        loan = originate_loan(bundle, 3_000_000)
        repaid = validate_success(
            api.repay_loan(policy_id, loan["id"], 3_000_000, _ph(bundle)))
        assert repaid["status"] == "REPAID"

        after = get_policy(policy_id)
        assert after["outstanding_loan_principal_cents"] == 0
        assert after["accrued_loan_interest_cents"] == 0
        assert (after["cash_value_cents"] + after["outstanding_loan_principal_cents"]
                == sum_before), "originate-then-repay conserves cash + outstanding"
        entries = list_ledger(policy_id)
        credits = [e for e in entries if e["entry_type"] == "LOAN_REPAYMENT_CREDIT"]
        assert len(credits) == 1 and credits[0]["amount_cents"] == 3_000_000

    def test_repay_already_repaid_loan_rejected(self, api):
        """PRD §3.6: "Attempting to repay a loan already in `REPAID` (or otherwise terminal) is
        rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/repay_already_repaid_loan_returns_already_terminal
        """
        bundle = create_funded_policy(10_000_000, premium_mode="ANNUAL")
        policy_id = bundle["policy"]["id"]
        loan = originate_loan(bundle, 1_000_000)
        settled = validate_success(
            api.repay_loan(policy_id, loan["id"], 1_000_000, _ph(bundle)))
        assert settled["status"] == "REPAID"
        resp = api.repay_loan(policy_id, loan["id"], 100, _ph(bundle))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
