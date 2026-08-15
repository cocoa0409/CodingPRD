"""Revenue split waterfall, month-end close, and regulatory reporting.

Covers difficulty instances revenue_split_owner_rounded_first_agent_residual
and regulatory_report_finalize_reopen_cycle, plus corner instances
month_end_double_close_rejected and report_finalize_before_period_close_rejected.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_book_loan,
    create_position,
    create_regulatory_report_payload,
    create_tranche,
    list_ledger_entries,
    make_desk_admin_headers,
    make_ops_settler_headers,
    post_cash_pledge,
    run_mtm_for_dates,
    run_month_end_close,
    setup_desk,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]

OPS = TEST_USERS["ops_settler_headers"]
ADMIN = TEST_USERS["desk_admin_headers"]


class TestRevenueSplitEvaluationOrder:
    def _split_setup(self, api):
        """One owner (6250bps) with:
        - a SECURITIES loan of 1,000,000 sh @ 25bps, four MTM days @ 1000c
          (final fee 27778);
        - a CASH loan of 10,000 sh @ 0bps with a 10,000,000c tranche @ 360bps
          marked to 10,015,002c and unwound in-period (final income 15002).
        Net pool = 27778 + 15002 - 0 = 42780.
        """
        security, owner, borrower, pos1 = setup_desk(
            security_symbol="SPL1", quantity_total=1_000_000,
            revenue_share_bps=6250, credit_limit_cents=2_000_000_000)
        pos2 = create_position(owner, security, quantity_total=1_000_000)
        l1 = create_and_book_loan(owner, borrower, security, pos1,
                                  quantity=1_000_000,
                                  collateral_type="SECURITIES", rate_bps=25)
        l2 = create_and_book_loan(owner, borrower, security, pos2,
                                  quantity=10000, collateral_type="CASH",
                                  rate_bps=0)
        post_cash_pledge(l2, borrower, 10_200_000)
        tranche = create_tranche(l2, principal_cents=10_000_000,
                                 instrument_type="REPO", stated_yield_bps=360)
        run_mtm_for_dates(
            ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"])
        validate_success(api.mark_reinvestment(
            tranche["id"], {"current_nav_cents": 10015002}, OPS))
        validate_success(api.unwind_reinvestment(tranche["id"], TRADER))
        return owner

    def test_owner_rounded_first_agent_takes_residual(self, api):
        """PRD §3.9: "the net pool is gross minus rebates and may be
        negative; the owner's share is the net pool times the owner's
        `revenue_share_bps` divided by 10000, rounded half-up to whole cents;
        and the agent's share is the exact residual — the net pool minus the
        owner's rounded share, so the agent absorbs any rounding cent."
        PRD §3.9: "Each owner receives a `REVENUE_SPLIT_OWNER` entry, and the
        desk a `REVENUE_SPLIT_AGENT` entry."

        Pool 42780 @ 6250bps: owner = round_half_up(26737.5) = 26738,
        agent = 42780 - 26738 = 16042 (not round(16042.5) = 16043).

        Design: Difficulty/combinatorial_formula/revenue_split_owner_rounded_first_agent_residual
        """
        owner = self._split_setup(api)
        run_month_end_close("2026-08")
        owner_entries = list_ledger_entries(
            OPS, owner_id=owner["id"], period="2026-08",
            entry_type="REVENUE_SPLIT_OWNER")
        agent_entries = list_ledger_entries(
            OPS, owner_id=owner["id"], period="2026-08",
            entry_type="REVENUE_SPLIT_AGENT")
        assert len(owner_entries) == 1
        assert len(agent_entries) == 1
        assert owner_entries[0]["amount_cents"] == 26738
        assert agent_entries[0]["amount_cents"] == 16042
        assert (owner_entries[0]["amount_cents"]
                + agent_entries[0]["amount_cents"]) == 42780

    def test_split_entries_conserve_the_pool_exactly(self, api):
        """PRD §3.9: "the gross pool is the sum of the owner's loans'
        `FEE_ACCRUAL_FINAL` entries plus their `REINVEST_INCOME_FINAL`
        entries for the period — `FEE_TRUE_UP` is deliberately excluded,
        because it reconciles the provisional stream to the authoritative
        final entry and adding both would double-count the delta; rebates are
        the owner's `REBATE_ACCRUAL` amounts for the period, negated from
        their stored-negative form"

        Design: Difficulty/combinatorial_formula/revenue_split_owner_rounded_first_agent_residual
        """
        owner = self._split_setup(api)
        run_month_end_close("2026-08")
        finals = list_ledger_entries(
            OPS, owner_id=owner["id"], period="2026-08",
            entry_type="FEE_ACCRUAL_FINAL")
        reinvest = list_ledger_entries(
            OPS, owner_id=owner["id"], period="2026-08",
            entry_type="REINVEST_INCOME_FINAL")
        gross = (sum(e["amount_cents"] for e in finals)
                 + sum(e["amount_cents"] for e in reinvest))
        assert gross == 42780

        splits_owner = list_ledger_entries(
            OPS, owner_id=owner["id"], period="2026-08",
            entry_type="REVENUE_SPLIT_OWNER")
        splits_agent = list_ledger_entries(
            OPS, owner_id=owner["id"], period="2026-08",
            entry_type="REVENUE_SPLIT_AGENT")
        total = (splits_owner[0]["amount_cents"]
                 + splits_agent[0]["amount_cents"])
        assert total == gross
        # No cent is created or destroyed; split entries carry loan_id null
        # per PRD §3.9 ("null on the revenue-split entries").
        assert splits_owner[0]["loan_id"] is None
        assert splits_agent[0]["loan_id"] is None


class TestRegulatoryReportCycle:
    def test_finalize_reopen_refinalize_file_cycle(self, api):
        """PRD §3.9: "Finalizing requires a `PeriodClose` to exist for the
        report's `period` (`ERR_PERIOD_NOT_CLOSED`), then computes and
        freezes the aggregates"
        PRD §3.9: "A settler may reopen a `FINALIZED` report, cycling it back
        to `DRAFT` with every aggregate cleared to null and
        `finalized_by_user_id` cleared."
        PRD §3.9: "A successful filing stamps `filed_by_user_id` and moves
        the report to `FILED`, its terminal state."

        Design: Difficulty/non_linear_state_machine/regulatory_report_finalize_reopen_cycle
        """
        run_month_end_close("2026-08")
        report = validate_success(api.create_regulatory_report(
            create_regulatory_report_payload(
                period="2026-08", report_type="MONTHLY_LOAN_ACTIVITY"),
            make_ops_settler_headers("ops-1")), expected_status=201)
        assert report["status"] == "DRAFT"

        fin1 = validate_success(api.finalize_regulatory_report(
            report["id"], make_ops_settler_headers("ops-1")))
        assert fin1["status"] == "FINALIZED"
        assert fin1["total_on_loan_value_cents"] == 0
        assert fin1["total_fee_income_cents"] == 0
        assert fin1["finalized_by_user_id"] == "ops-1"

        reopened = validate_success(api.reopen_regulatory_report(
            report["id"], make_ops_settler_headers("ops-1")))
        assert reopened["status"] == "DRAFT"
        assert reopened["total_on_loan_value_cents"] is None
        assert reopened["finalized_by_user_id"] is None

        fin2 = validate_success(api.finalize_regulatory_report(
            report["id"], make_ops_settler_headers("ops-1")))
        assert fin2["status"] == "FINALIZED"

        filed = validate_success(api.file_regulatory_report(
            report["id"], make_desk_admin_headers("admin-9")))
        assert filed["status"] == "FILED"
        assert filed["filed_by_user_id"] == "admin-9"
        assert filed["finalized_by_user_id"] == "ops-1"

    def test_aggregates_freeze_on_finalize_and_clear_on_reopen(self, api):
        """PRD §3.9: "computes and freezes the aggregates:
        `total_on_loan_value_cents` sums the `market_value_cents` of all
        loans in `BOOKED` or `RECALLED` at finalize time"
        PRD §3.9: "cycling it back to `DRAFT` with every aggregate cleared to
        null and `finalized_by_user_id` cleared."

        Design: Difficulty/non_linear_state_machine/regulatory_report_finalize_reopen_cycle
        """
        run_month_end_close("2026-08")
        report = validate_success(api.create_regulatory_report(
            create_regulatory_report_payload(period="2026-08"), OPS),
            expected_status=201)
        fin = validate_success(api.finalize_regulatory_report(
            report["id"], make_ops_settler_headers("ops-1")))
        assert fin["total_on_loan_value_cents"] == 0
        assert fin["total_fee_income_cents"] == 0
        assert fin["total_rebate_expense_cents"] == 0
        assert fin["fail_count"] == 0
        assert fin["buy_in_count"] == 0
        reopened = validate_success(api.reopen_regulatory_report(
            report["id"], OPS))
        for field in ("total_on_loan_value_cents", "total_fee_income_cents",
                      "total_rebate_expense_cents", "fail_count",
                      "buy_in_count", "finalized_by_user_id"):
            assert reopened[field] is None, f"{field} not cleared on reopen"


class TestMonthEndClose:
    def test_double_close_rejected(self, api):
        """PRD §3.9: "The close is recorded as a `PeriodClose` whose `period`
        is unique — a second close of the same period is rejected with
        `ERR_PERIOD_ALREADY_CLOSED`"

        Design: Corner/errors/month_end_double_close_rejected
        """
        close = run_month_end_close("2026-08")
        assert close["status"] == "CLOSED"
        resp = api.run_month_end_close({"period": "2026-08"}, OPS)
        validate_error(resp, ApiErrorId.ERR_PERIOD_ALREADY_CLOSED)


class TestReportFinalizeGate:
    def test_finalize_before_period_close_rejected_then_succeeds(self, api):
        """PRD §3.9: "Finalizing requires a `PeriodClose` to exist for the
        report's `period` (`ERR_PERIOD_NOT_CLOSED`)"

        Design: Corner/errors/report_finalize_before_period_close_rejected
        """
        report = validate_success(api.create_regulatory_report(
            create_regulatory_report_payload(period="2026-09",
                                             report_type="FAILS_AND_BUYINS"),
            OPS), expected_status=201)
        resp = api.finalize_regulatory_report(report["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED)
        run_month_end_close("2026-09")
        fin = validate_success(api.finalize_regulatory_report(
            report["id"], OPS))
        assert fin["status"] == "FINALIZED"
        assert fin["fail_count"] == 0
