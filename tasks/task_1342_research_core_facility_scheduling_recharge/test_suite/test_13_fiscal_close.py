"""Fiscal-year close: accrual-vs-cash true-up, the carryforward cascade, and
the open-batch gate (PRD §3.13)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS,
    setup_canonical_stack, open_fiscal_year, create_draft_rate_set,
    create_approved_booking, open_batch, finalize_batch,
    run_session_to_completed, create_and_validate_usage_log,
    find_entry_for_usage_log, find_fiscal_year,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
STAFF2 = TEST_USERS["staff2_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestAccrualVsCashTrueUp:
    def _setup(self, api):
        """Two completed+validated sessions in FY2026: E1 (net 15000) in
        finalized batch 2026-09, left BILLED; E2 (net 9000) in finalized batch
        2026-10, marked PAID. One 50000-cent contract covers 2026."""
        stack = setup_canonical_stack(with_contract=True)
        # E1: 74 actual minutes -> 15000.
        b1 = create_approved_booking(stack)
        bat9 = open_batch(2026, 9)
        c1 = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        log1 = create_and_validate_usage_log(
            c1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        finalize_batch(bat9["id"])
        # E2: 40 actual minutes -> billable 45 -> 9000.
        b2 = create_approved_booking(
            stack, start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T09:40:00Z"
        )
        c2 = run_session_to_completed(
            b2, "2026-09-02T09:00:00Z", "2026-09-02T09:40:00Z"
        )
        bat10 = open_batch(2026, 10)
        log2 = create_and_validate_usage_log(
            c2, "2026-09-02T09:00:00Z", "2026-09-02T09:40:00Z"
        )
        finalize_batch(bat10["id"])
        e2 = find_entry_for_usage_log(log2["id"])
        validate_success(api.mark_recharge_entry_paid(e2["id"], FINANCE), 200)
        return stack

    def test_accrual_revenue_differs_from_cash(self, api):
        """PRD §3.13: "The official accrual revenue — `revenue_cents` — is the
        sum of `net_amount_cents` over counted entries whose status at close
        time is `BILLED` or `PAID`; written-off entries are excluded as
        reversed. An informational cash variant, `cash_revenue_cents`, sums the
        same set but counts only entries `PAID` at close time; the two figures
        diverge whenever any counted entry is billed-but-unpaid at close".

        Design: Difficulty/dual_variant_calc/fiscal_trueup_accrual_vs_cash_on_fiscal_year
        """
        stack = self._setup(api)
        closed = validate_success(
            api.close_fiscal_year(stack["fy"]["id"], FINANCE), 200
        )
        assert closed["revenue_cents"] == 24000, "accrual: BILLED 15000 + PAID 9000"
        assert closed["cash_revenue_cents"] == 9000, "cash: PAID only"
        assert closed["revenue_cents"] != closed["cash_revenue_cents"]

    def test_cost_surplus_and_carryforward_use_accrual(self, api):
        """PRD §3.13: "`cost_cents` is the sum of `annual_cost_cents` over
        every maintenance contract whose coverage window intersects the fiscal
        year — full cost, no proration — plus 120,000 cents of operating
        overhead for each instrument that has at least one counted revenue
        entry in the year. `surplus_deficit_cents` is revenue minus cost,
        signed; `carryforward_out_cents` equals it".

        Design: Difficulty/dual_variant_calc/fiscal_trueup_accrual_vs_cash_on_fiscal_year
        """
        stack = self._setup(api)
        closed = validate_success(
            api.close_fiscal_year(stack["fy"]["id"], FINANCE), 200
        )
        assert closed["cost_cents"] == 170000, "contract 50000 + 120000 overhead"
        assert closed["surplus_deficit_cents"] == -146000, "24000 - 170000"
        assert closed["carryforward_out_cents"] == -146000, (
            "the accrual figure is the official one carried forward"
        )


class TestCarryforwardCascade:
    def _setup(self, api):
        """Canonical stack with a contract covering 2026-01-01..2027-12-31; one
        BILLED 15000-cent entry; a DRAFT FY2027 rate set (internal 12000)
        existing BEFORE the close."""
        stack = setup_canonical_stack(
            with_contract=True,
            contract_overrides={"coverage_start": "2026-01-01",
                                "coverage_end": "2027-12-31"},
        )
        rs27 = create_draft_rate_set(
            stack["i1"]["id"], fiscal_year=2027,
            effective_from="2027-01-01T00:00:00Z",
        )
        b1 = create_approved_booking(stack)
        batch = open_batch(2026, 9)
        c1 = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        create_and_validate_usage_log(
            c1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        finalize_batch(batch["id"])
        return stack, rs27

    def test_close_posts_carryforward_to_auto_created_period(self, api):
        """PRD §3.13: "If the next fiscal year's period does not exist, it is
        auto-created in `OPEN` status with `carryforward_in_cents` set to this
        year's `carryforward_out_cents`." and "`surplus_deficit_cents` is
        revenue minus cost, signed; `carryforward_out_cents` equals it".

        Design: Difficulty/transitive_cascade/fiscal_close_carryforward_cascade
        """
        stack, rs27 = self._setup(api)
        closed = validate_success(
            api.close_fiscal_year(stack["fy"]["id"], FINANCE), 200
        )
        assert closed["surplus_deficit_cents"] == -155000, "15000 - 170000"
        assert closed["carryforward_out_cents"] == -155000
        fy27 = find_fiscal_year(2027)
        assert fy27["status"] == "OPEN", "auto-created in OPEN status"
        assert fy27["carryforward_in_cents"] == -155000

    def test_next_year_draft_line_flagged_for_review(self, api):
        """PRD §3.13: "That new carryforward propagates into every rate set in
        `DRAFT` or `UNDER_REVIEW` for the next fiscal year: the derived-rate
        computation re-runs with the new carryforward (projected cost minus the
        signed carryforward, divided by projected hours, each line's suggestion
        rounded half-up to cents first), and any re-derived line whose stored
        internal rate deviates from the new suggestion by more than five
        percent gets `flagged_for_review` set to true in its verdict entry."

        Design: Difficulty/transitive_cascade/fiscal_close_carryforward_cascade
        """
        stack, rs27 = self._setup(api)
        validate_success(api.close_fiscal_year(stack["fy"]["id"], FINANCE), 200)
        after = validate_success(api.get_rate_set(rs27["id"], FINANCE), 200)
        # Suggestion: (50000 + 120000 - (-155000)) / 500 = 650; the stored
        # 12000 deviates by far more than five percent.
        assert after["line_verdicts"][0]["flagged_for_review"] is True


class TestCloseGate:
    def test_fiscal_close_blocked_by_open_batch(self, api):
        """PRD §3.13: "Closing the year is permitted only when no
        `RechargeBatch` whose period falls inside the closing year remains
        `OPEN` (`ERR_UNFINALIZED_BATCHES`)."

        Design: Corner/validations/fiscal_close_blocked_by_open_batch
        """
        fy26 = open_fiscal_year(2026)
        open_batch(2026, 9)
        res = api.close_fiscal_year(fy26["id"], FINANCE)
        validate_error(res, "ERR_UNFINALIZED_BATCHES", expected_status=409)
        after = validate_success(api.get_fiscal_year(fy26["id"], FINANCE), 200)
        assert after["status"] == "OPEN"
