"""Dividend accrual mathematics: tier bonuses, rounding order, the minimum
balance gate, the accrual window, and immediate consistency."""
from test_helpers import (
    assert_dividend_declaration,
    assert_dividend_payment,
    create_member,
    declare_dividend,
    list_declaration_payments,
    open_account,
    set_clock,
    setup_charter,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

FILER = TEST_USERS["membership_officer_headers"]
DECIDER = TEST_USERS["membership_officer_2_headers"]
BOARD = TEST_USERS["board_director_headers"]
OPS = TEST_USERS["operations_officer_headers"]


def _charter_with_segment(api, par_value_cents=500):
    _charter, seg_ids = setup_charter(par_value_cents=par_value_cents)
    return seg_ids[0]


class TestTierBonusBranches:
    """Two members with identical 500,000-cent July balances but different
    tiers accrue different dividends; the pool sums both branches."""

    def _setup(self, api):
        set_clock("2025-07-01")
        seg = _charter_with_segment(api)
        m2 = create_member(segment_id=seg, name="Senior Sue",
                           date_of_birth="1985-05-05")
        acct2 = open_account(m2, initial_deposit_cents=500_000)

        set_clock("2026-06-15")
        m1 = create_member(segment_id=seg, name="Junior Jay",
                           date_of_birth="1995-06-06")
        acct1 = open_account(m1, initial_deposit_cents=500_000)

        set_clock("2026-07-15")
        reviewed = validate_success(api.tier_review(m2, OPS))

        set_clock("2026-08-02")
        decl = declare_dividend()
        return m1, m2, acct1, acct2, reviewed, decl

    def test_dividend_tier_bonus_changes_per_account_amounts(self, api):
        """PRD §3.7: "The effective annual rate is the declaration's `rate_bps`
        plus a tier bonus on the owner's tier — zero basis points for STANDARD,
        25 for SELECT, 50 for PREMIER — and at declaration the bonus uses the
        member's tier as of the declaration date."
        PRD §3.7: "Eligible accounts are processed — and their DividendPayment
        rows created — in order of `opened_date` ascending, ties broken by
        `created_at` ascending."
        PRD §3.7: "Each surviving account's raw amount is rounded half-up to
        integer cents exactly once, recorded as the row's
        `accrued_amount_cents`, with the bonus used recorded as
        `tier_bonus_bps_applied` and the row beginning ACCRUED"

        Design: Difficulty/combinatorial_formula/dividend_tier_bonus_conditional_branches
        """
        m1, m2, acct1, acct2, reviewed, decl = self._setup(api)
        assert reviewed["tier"] == "SELECT", (
            "Trailing-90 average 500,000 and tenure 12 qualify for SELECT")

        rows = list_declaration_payments(decl["id"])
        assert len(rows) == 2
        first, second = rows[0], rows[1]
        for row in rows:
            assert_dividend_payment(row)
        assert first["share_account_id"] == acct2["id"], (
            "Rows are created in opened_date ascending order")
        assert first["accrued_amount_cents"] == 2654, (
            "500,000 x 625 bps x 31 / 365 = 2654.11 -> 2654 (SELECT +25 bps)")
        assert first["tier_bonus_bps_applied"] == 25
        assert first["status"] == "ACCRUED"
        assert second["share_account_id"] == acct1["id"]
        assert second["accrued_amount_cents"] == 2548, (
            "500,000 x 600 bps x 31 / 365 = 2547.95 -> 2548 (STANDARD +0 bps)")
        assert second["tier_bonus_bps_applied"] == 0

    def test_dividend_pool_sums_both_tier_branches(self, api):
        """PRD §3.7: "The declaration's `declared_pool_cents` is the sum of
        those per-account rounded amounts — the per-account rounding precedes
        the summation, never follows it."

        Design: Difficulty/combinatorial_formula/dividend_tier_bonus_conditional_branches
        """
        _m1, _m2, _a1, _a2, _reviewed, decl = self._setup(api)
        assert decl["declared_pool_cents"] == 5202, (
            "2654 (SELECT branch) + 2548 (STANDARD branch)")

        rows = list_declaration_payments(decl["id"])
        assert sum(r["accrued_amount_cents"] for r in rows) == 5202
        assert decl["declared_pool_cents"] == sum(
            r["accrued_amount_cents"] for r in rows)


class TestPoolRoundingOrder:
    """Two 10,000-cent accounts at 700 bps: per-account raw 59.4521 rounds to
    59; the pool is 118 (round-then-sum), not 119 (sum-then-round)."""

    def _setup(self, api):
        set_clock("2026-06-15")
        seg = _charter_with_segment(api)
        m1 = create_member(segment_id=seg, name="Round One")
        acct1 = open_account(m1, initial_deposit_cents=10_000)
        m2 = create_member(segment_id=seg, name="Round Two",
                           date_of_birth="1992-02-02")
        acct2 = open_account(m2, initial_deposit_cents=10_000)
        set_clock("2026-08-02")
        decl = declare_dividend(rate_bps=700)
        return acct1, acct2, decl

    def test_pool_rounding_per_account_amounts(self, api):
        """PRD §2.8: "Where a computation produces a fractional cent, the
        per-account amount is rounded half-up to integer cents exactly once"

        Design: Difficulty/combinatorial_formula/dividend_pool_round_per_account_then_sum
        """
        acct1, acct2, decl = self._setup(api)
        rows = list_declaration_payments(decl["id"])
        assert len(rows) == 2
        assert rows[0]["share_account_id"] == acct1["id"]
        assert rows[1]["share_account_id"] == acct2["id"]
        assert rows[0]["accrued_amount_cents"] == 59, (
            "10,000 x 700 bps x 31 / 365 = 59.4521 -> 59 half-up")
        assert rows[1]["accrued_amount_cents"] == 59

    def test_pool_rounding_round_then_sum_total(self, api):
        """PRD §2.8: "that per-account rounding always precedes any summation;
        summing raw values first and rounding once is forbidden because it
        yields a different total."

        Design: Difficulty/combinatorial_formula/dividend_pool_round_per_account_then_sum
        """
        _acct1, _acct2, decl = self._setup(api)
        assert decl["declared_pool_cents"] == 118, (
            "59 + 59; summing the raw 59.4521 + 59.4521 = 118.9042 and "
            "rounding once would yield 119, which is forbidden")


class TestAccrualBasics:
    def test_dividend_adb_constant_balance_literal(self, api):
        """PRD §3.7: "Under `AVERAGE_DAILY_BALANCE` the raw dividend is the sum
        of the window's end-of-day balances, multiplied by the effective rate
        (basis points divided by ten thousand) and divided by 365, the fixed
        day-count year."
        PRD §3.7: "For each account the accrual window runs from the later of
        `period_start` and the account's `opened_date` through `period_end`,
        both boundary days included, and the window's day count is the number
        of calendar days it spans."

        Design: Corner/calculations/dividend_adb_constant_balance_literal
        """
        set_clock("2026-06-15")
        seg = _charter_with_segment(api)
        member_id = create_member(segment_id=seg, name="Calc Amy")
        open_account(member_id, initial_deposit_cents=100_000)

        set_clock("2026-08-02")
        decl = declare_dividend()
        assert_dividend_declaration(decl)
        assert decl["status"] == "DECLARED"
        assert decl["declared_pool_cents"] == 510, (
            "100,000 x 600 bps x 31 / 365 = 509.5890 -> 510 half-up")

        rows = list_declaration_payments(decl["id"])
        assert len(rows) == 1
        assert rows[0]["accrued_amount_cents"] == 510
        assert rows[0]["tier_bonus_bps_applied"] == 0, "Member is STANDARD"
        assert rows[0]["status"] == "ACCRUED"

    def test_dividend_minimum_balance_gate_boundary(self, api):
        """PRD §3.7: "A minimum-balance gate guards both methods: when the sum
        of the window's end-of-day balances divided by the day count falls
        below 500 cents, the account earns nothing and no payment row is
        created for it at accrual."

        Design: Corner/calculations/dividend_minimum_balance_gate_boundary
        """
        set_clock("2026-06-15")
        seg = _charter_with_segment(api, par_value_cents=400)
        m_a = create_member(segment_id=seg, name="Gate Ann")
        acct_a = open_account(m_a, initial_deposit_cents=500)
        m_b = create_member(segment_id=seg, name="Gate Bob",
                            date_of_birth="1990-02-02")
        acct_b = open_account(m_b, initial_deposit_cents=499)

        set_clock("2026-08-02")
        decl = declare_dividend()
        assert decl["declared_pool_cents"] == 3, (
            "500 x 600 bps x 31 / 365 = 2.5479 -> 3 half-up")

        rows, meta = validate_paginated(
            api.list_declaration_payments(decl["id"], BOARD))
        assert meta["total_count"] == 1, (
            "The 499-cent account averages below the 500-cent gate and earns "
            "no row at all")
        assert rows[0]["share_account_id"] == acct_a["id"]
        assert rows[0]["accrued_amount_cents"] == 3
        assert all(r["share_account_id"] != acct_b["id"] for r in rows)

    def test_dividend_input_set_window_and_closed_exclusion(self, api):
        """PRD §3.7: "The eligible set is every share account that is OPEN at
        computation time with an `opened_date` on or before `period_end`;
        CLOSED accounts are excluded entirely."
        PRD §3.7: "For each account the accrual window runs from the later of
        `period_start` and the account's `opened_date` through `period_end`,
        both boundary days included"

        Design: Corner/calculations/dividend_input_set_window_and_closed_exclusion
        """
        set_clock("2026-06-15")
        seg = _charter_with_segment(api)
        m1 = create_member(segment_id=seg, name="Midperiod Mia")
        m2 = create_member(segment_id=seg, name="Early Eddie",
                           date_of_birth="1990-02-02")
        acct2 = open_account(m2, account_type="SUPPLEMENTAL",
                             initial_deposit_cents=100_000)

        set_clock("2026-07-16")
        acct1 = open_account(m1, initial_deposit_cents=500_000)

        set_clock("2026-07-20")
        validate_success(api.close_share_account(acct2["id"], FILER))

        set_clock("2026-08-02")
        decl = declare_dividend()
        assert decl["declared_pool_cents"] == 1315

        rows, meta = validate_paginated(
            api.list_declaration_payments(decl["id"], BOARD))
        assert meta["total_count"] == 1, (
            "The account closed before the declaration is excluded entirely")
        assert rows[0]["share_account_id"] == acct1["id"]
        assert rows[0]["accrued_amount_cents"] == 1315, (
            "Window starts at opened_date 2026-07-16: 500,000 x 600 bps x 16 "
            "/ 365 = 1315.07 -> 1315")

    def test_premier_tier_bonus_applied(self, api):
        """PRD §3.4: "PREMIER requires tenure of at least 36 full months and a
        balance basis of at least 2,500,000 cents"
        PRD §3.7: "The effective annual rate is the declaration's `rate_bps`
        plus a tier bonus on the owner's tier — zero basis points for STANDARD,
        25 for SELECT, 50 for PREMIER"

        Design: Corner/calculations/premier_tier_bonus_applied
        """
        set_clock("2023-07-01")
        seg = _charter_with_segment(api)
        member_id = create_member(segment_id=seg, name="Premier Pam",
                                  date_of_birth="1980-01-01")
        open_account(member_id, initial_deposit_cents=2_500_000)

        set_clock("2026-08-01")
        reviewed = validate_success(api.tier_review(member_id, OPS))
        assert reviewed["tier"] == "PREMIER", (
            "Tenure 37 months and trailing-90 average 2,500,000")

        decl = declare_dividend()
        assert decl["declared_pool_cents"] == 13_801, (
            "2,500,000 x 650 bps x 31 / 365 = 13,801.37 -> 13,801")

        rows = list_declaration_payments(decl["id"])
        assert len(rows) == 1
        assert rows[0]["accrued_amount_cents"] == 13_801
        assert rows[0]["tier_bonus_bps_applied"] == 50


class TestImmediateConsistency:
    def test_immediate_consistency_of_computed_fields_in_create_response(self, api):
        """PRD §1: "Every mutation, including cascades and recomputations, is
        atomic and visible in the same response and in every subsequent read."
        PRD §3.7: "The declaration's `declared_pool_cents` is the sum of those
        per-account rounded amounts — the per-account rounding precedes the
        summation, never follows it."
        PRD §3.5: "The account's `balance_cents` is never accepted as input; it
        is always derived from the ledger."

        Design: Corner/consistency_model/immediate_consistency_of_computed_fields_in_create_response
        """
        set_clock("2026-06-15")
        seg = _charter_with_segment(api)
        member_id = create_member(segment_id=seg, name="Immediate Ivy")
        account = validate_success(api.create_share_account(
            {"member_id": member_id, "account_type": "PRIMARY",
             "initial_deposit_cents": 100_000},
            FILER), 201)
        assert account["balance_cents"] == 100_000, (
            "The creation response itself carries the derived balance")

        set_clock("2026-08-02")
        decl = declare_dividend()
        assert decl["declared_pool_cents"] == 510, (
            "Computed atomically inside the creation response")

        rows = list_declaration_payments(decl["id"])
        assert rows[0]["accrued_amount_cents"] == 510, (
            "The ACCRUED row is visible on the very next read")

        accounts, _meta = validate_paginated(
            api.list_member_share_accounts(member_id, BOARD))
        assert accounts[0]["balance_cents"] == 100_000, (
            "Accrual never moves money; the balance is unchanged")
