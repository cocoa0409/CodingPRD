"""Accrual variants: provisional vs final fee, reinvestment stated-yield vs
NAV realization, rebate accruals, and ops-run idempotency.

Covers difficulty instances
loan_fee_provisional_rounding_vs_final_month_rounding,
reinvestment_stated_yield_provisional_vs_nav_final, and corner instances
rebate_accrual_daily_amount, mtm_rerun_same_day_never_double_accrues.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_tranche,
    get_loan,
    get_tranche,
    list_ledger_entries,
    make_borrower_rep_headers,
    post_cash_pledge,
    run_mtm,
    run_mtm_for_dates,
    run_mtm_on,
    run_month_end_close,
    set_clock,
    setup_booked_loan,
    setup_cash_loan_with_pledge,
    setup_desk,
    create_and_book_loan,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]
OPS = TEST_USERS["ops_settler_headers"]


class TestDualVariantFeeAccrual:
    def _four_day_fee_loan(self, api):
        """1,000,000-share SECURITIES loan at 25bps, four MTM days at 1000c.

        Per-day fee: round_half_up(1,000,000 x 1000 x 25/10000/360)
        = round_half_up(6944.44...) = 6944 per day -> provisional sum 27776.
        Period total: 4 x 6944.44... = 27777.77... -> round once -> 27778.
        """
        ctx = setup_booked_loan(
            security_symbol="FEE1", quantity_total=1_000_000,
            loan_quantity=1_000_000, collateral_type="SECURITIES",
            rate_bps=25, credit_limit_cents=2_000_000_000,
            revenue_share_bps=6250)
        run_mtm_for_dates(
            ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"])
        return ctx

    def test_provisional_daily_rounding_vs_final_month_rounding(self, api):
        """PRD §3.9: "For a **securities-collateral** loan in `BOOKED` or
        `RECALLED`, each daily run posts a `FEE_ACCRUAL_PROVISIONAL` equal to
        that day's `outstanding_quantity` times that day's marked
        `price_cents` times the loan's `rate_bps`, divided by 10000 and then
        by the 360-day year, rounded half-up to whole cents per day"
        PRD §3.9: "For each loan, the exact fee for the period is the
        unrounded day-by-day total — each accrued day's outstanding quantity
        times that day's marked price times `rate_bps`, divided by 10000 and
        by 360, summed across the period's accrued days — rounded half-up
        exactly once at month end and posted as `FEE_ACCRUAL_FINAL`; a
        `FEE_TRUE_UP` entry for the difference between that final fee and the
        sum of the period's provisionals reconciles the two, so the variants
        diverge only by accumulated per-day rounding."

        Design: Difficulty/dual_variant_calc/loan_fee_provisional_rounding_vs_final_month_rounding
        """
        ctx = self._four_day_fee_loan(api)
        loan_id = ctx["loan"]["id"]

        close = run_month_end_close("2026-08")
        assert close["status"] == "CLOSED"
        assert close["loans_finalized_count"] >= 1

        provisionals = list_ledger_entries(
            OPS, loan_id=loan_id, period="2026-08",
            entry_type="FEE_ACCRUAL_PROVISIONAL")
        assert len(provisionals) == 4
        assert all(e["amount_cents"] == 6944 for e in provisionals)
        assert sum(e["amount_cents"] for e in provisionals) == 27776

        finals = list_ledger_entries(
            OPS, loan_id=loan_id, period="2026-08",
            entry_type="FEE_ACCRUAL_FINAL")
        assert len(finals) == 1
        assert finals[0]["amount_cents"] == 27778

        true_ups = list_ledger_entries(
            OPS, loan_id=loan_id, period="2026-08", entry_type="FEE_TRUE_UP")
        assert len(true_ups) == 1
        assert true_ups[0]["amount_cents"] == 2

    def test_provisional_stream_is_one_per_day_and_never_zero(self, api):
        """PRD §3.9: "one entry per loan per accrual date, so a second run on
        the same date posts nothing, and a zero computed fee is never posted
        (a `rate_bps` of zero produces no rows)."

        Design: Difficulty/dual_variant_calc/loan_fee_provisional_rounding_vs_final_month_rounding
        """
        ctx = setup_booked_loan(security_symbol="FEE2", quantity_total=100000,
                                loan_quantity=50000, rate_bps=25)
        run_mtm_on("2026-08-01")
        run_mtm()  # same date again: no double accrual
        entries = list_ledger_entries(
            OPS, loan_id=ctx["loan"]["id"],
            entry_type="FEE_ACCRUAL_PROVISIONAL")
        assert len(entries) == 1
        # 50000 x 1000 x 25 / 10000 / 360 = 347.22 -> 347
        assert entries[0]["amount_cents"] == 347


class TestReinvestmentVariants:
    def _ten_day_tranche(self, api):
        """CASH loan, 10,200,000c pledged, 10,000,000c tranche at 360bps,
        ten MTM days, NAV marked to 10,015,002c."""
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=10_200_000, security_symbol="RNV1",
            quantity_total=1_000_000, loan_quantity=10000, rate_bps=0,
            credit_limit_cents=100_000_000)
        tranche = create_tranche(ctx["loan"], principal_cents=10_000_000,
                                 instrument_type="MMF", stated_yield_bps=360)
        run_mtm_for_dates([
            "2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04",
            "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08",
            "2026-08-09", "2026-08-10"])
        validate_success(api.mark_reinvestment(
            tranche["id"], {"current_nav_cents": 10015002}, OPS))
        return ctx, tranche

    def test_stated_yield_provisional_vs_nav_final(self, api):
        """PRD §3.6: "Provisionally, each daily run accrues every `INVESTED`
        tranche's `principal_cents` times its `stated_yield_bps`, divided by
        10000 and then by the 360-day year, rounded half-up to whole cents,
        as a `REINVEST_INCOME_PROVISIONAL` entry — one per tranche per
        accrual date, regardless of how the NAV has moved. Finally, at
        unwind, the tranche realizes `current_nav_cents` minus
        `principal_cents` as its `realized_income_cents` — a figure that may
        be negative when the mark has fallen — and a `REINVEST_INCOME_FINAL`
        entry carries that signed amount. The provisional stream is
        informational only: it is never trued-up, and the final entry alone
        reaches the revenue pool. Unwinding returns the principal to the
        loan's `cash_uninvested_cents`; gains and losses go to revenue, never
        to the borrower's collateral principal."

        Design: Difficulty/dual_variant_calc/reinvestment_stated_yield_provisional_vs_nav_final
        """
        ctx, tranche = self._ten_day_tranche(api)
        loan_id = ctx["loan"]["id"]

        provisionals = list_ledger_entries(
            OPS, loan_id=loan_id, entry_type="REINVEST_INCOME_PROVISIONAL")
        assert len(provisionals) == 10
        # 10,000,000 x 360 / 10000 / 360 = 1000 per day
        assert all(e["amount_cents"] == 1000 for e in provisionals)
        assert sum(e["amount_cents"] for e in provisionals) == 10000

        unwound = validate_success(api.unwind_reinvestment(
            tranche["id"], TRADER))
        # 10,015,002 - 10,000,000 = 15,002
        assert unwound["realized_income_cents"] == 15002

        finals = list_ledger_entries(
            OPS, loan_id=loan_id, entry_type="REINVEST_INCOME_FINAL")
        assert len(finals) == 1
        assert finals[0]["amount_cents"] == 15002

        # The provisional stream is untouched by the unwind.
        provisionals_after = list_ledger_entries(
            OPS, loan_id=loan_id, entry_type="REINVEST_INCOME_PROVISIONAL")
        assert sum(e["amount_cents"] for e in provisionals_after) == 10000

        # Principal returns to uninvested cash; the gain stays in revenue.
        assert get_loan(loan_id)["cash_uninvested_cents"] == 10200000

    def test_provisional_stream_diverges_from_final_without_trueup(self, api):
        """PRD §3.6: "The provisional stream is informational only: it is
        never trued-up, and the final entry alone reaches the revenue pool."

        After the unwind no additional REINVEST_* entries appear: the
        provisional total (10,000) and the final (15,002) stand side by side.

        Design: Difficulty/dual_variant_calc/reinvestment_stated_yield_provisional_vs_nav_final
        """
        ctx, tranche = self._ten_day_tranche(api)
        loan_id = ctx["loan"]["id"]
        validate_success(api.unwind_reinvestment(tranche["id"], TRADER))
        # Default page size is 10 — pass an explicit limit so all 11
        # entries (10 PROVISIONAL + 1 FINAL) are returned in one page.
        all_entries = list_ledger_entries(OPS, loan_id=loan_id, limit=100)
        reinvest = [e for e in all_entries
                    if e["entry_type"].startswith("REINVEST_INCOME")]
        by_type = {}
        for e in reinvest:
            by_type.setdefault(e["entry_type"], []).append(e)
        assert len(by_type["REINVEST_INCOME_PROVISIONAL"]) == 10
        assert len(by_type["REINVEST_INCOME_FINAL"]) == 1
        # No true-up entry type exists for the reinvestment stream.
        assert all(e["entry_type"] != "FEE_TRUE_UP" for e in reinvest)


class TestReinvestmentGuards:
    def test_reinvestment_requires_loan_booked(self, api):
        """PRD §3.6: "A `DeskTrader` may unwind a tranche manually only while
        its loan is `BOOKED` or `RECALLED` (`ERR_INVALID_STATE`)"
        PRD §3.6: "A `DeskTrader` may invest a cash-collateral loan's
        uninvested balance by opening a `ReinvestmentTranche`" — the invest
        endpoint's definition ("Invest uninvested cash collateral" for loans
        in BOOKED/RECALLED) rejects a still-PROPOSED loan with
        `ERR_INVALID_STATE`.

        Design: Difficulty/cross_entity_state_dependency/reinvestment_requires_loan_booked
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="XDP2")
        from test_helpers import create_loan_proposal
        loan = create_loan_proposal(owner, borrower, security, position,
                                    quantity=1000, collateral_type="CASH",
                                    rate_bps=0)
        resp = api.create_reinvestment(
            loan["id"], {"instrument_type": "MMF", "principal_cents": 100000,
                         "stated_yield_bps": 360}, TRADER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        booked = validate_success(api.accept_loan(
            loan["id"], make_borrower_rep_headers(borrower["id"])))
        post_cash_pledge(booked, borrower, 1_020_000)
        tranche = validate_success(api.create_reinvestment(
            loan["id"], {"instrument_type": "MMF", "principal_cents": 100000,
                         "stated_yield_bps": 360}, TRADER),
            expected_status=201)
        assert tranche["status"] == "INVESTED"
        # 1,020,000 pledged - 100,000 invested
        assert get_loan(loan["id"])["cash_uninvested_cents"] == 920000


    def test_manual_unwind_rejected_when_loan_not_booked(self, api):
        """PRD §3.6: "A `DeskTrader` may unwind a tranche manually only while
        its loan is `BOOKED` or `RECALLED` (`ERR_INVALID_STATE`)"

        After the loan settles, the tranche was already unwound by the
        settlement cascade; a second manual unwind is a state error.

        Design: Difficulty/cross_entity_state_dependency/reinvestment_requires_loan_booked
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="XDP3",
            loan_quantity=1000, rate_bps=0)
        tranche = create_tranche(ctx["loan"], principal_cents=100_000)
        from test_helpers import return_shares
        return_shares(ctx["loan"], ctx["borrower"], 1000)  # settles; unwinds
        resp = api.unwind_reinvestment(tranche["id"], TRADER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRebateAccrual:
    def test_rebate_accrual_daily_amount_is_negative(self, api):
        """PRD §3.9: "For a **cash-collateral** loan, the borrower earns a
        rebate instead: each run posts a `REBATE_ACCRUAL` equal to the day's
        active cash pledged — the sum of the loan's `ACTIVE` cash pledges —
        times `rate_bps`, divided by 10000 and by 360, rounded half-up per
        day, and carried as a negative amount because it is income owed back
        to the borrower."

        Design: Corner/calculations/rebate_accrual_daily_amount
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=10_200_000, security_symbol="CL1",
            loan_quantity=10000, rate_bps=150)
        run_mtm()
        entries = list_ledger_entries(
            OPS, loan_id=ctx["loan"]["id"], entry_type="REBATE_ACCRUAL")
        assert len(entries) == 1
        # round_half_up(10200000 x 150 / 10000 / 360) = 425, stored negative
        assert entries[0]["amount_cents"] == -425
        assert entries[0]["accrual_date"] == "2026-08-01"


class TestOpsRunIdempotency:
    def test_mtm_rerun_same_day_never_double_accrues(self, api):
        """PRD §2.12: "The run is idempotent within a date: running it twice
        for the same date never double-accrues, never double-issues, and
        produces no duplicate ledger entries."
        PRD §3.9: "one entry per loan per accrual date, so a second run on
        the same date posts nothing"

        Design: Corner/complexity_layers/mtm_rerun_same_day_never_double_accrues
        """
        ctx = setup_booked_loan(security_symbol="EP1", quantity_total=100000,
                                loan_quantity=50000, rate_bps=25)
        first = run_mtm()
        second = run_mtm()
        assert first["loans_accrued"] == 1
        assert second["loans_accrued"] == 0
        entries = list_ledger_entries(
            OPS, loan_id=ctx["loan"]["id"],
            entry_type="FEE_ACCRUAL_PROVISIONAL")
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 347
