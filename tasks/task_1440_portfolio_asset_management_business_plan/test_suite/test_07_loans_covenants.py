"""Loans, covenant tests (DSCR / debt-yield / LTV), the breach-cure-waive
cycle, freshness windows, and the posture cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    actuals_line_entry,
    assert_covenant_test,
    confirm_valuation_fresh,
    create_actuals_report_payload,
    create_covenant,
    create_covenant_payload,
    create_covenant_test_payload,
    create_loan,
    create_loan_payload,
    create_valuation_payload,
    find_line,
    get_covenant,
    get_loan,
    get_portfolio,
    get_success_data,
    lines_plan10,
    make_property_manager_headers,
    record_covenant_test,
    set_clock,
    setup_asset_with_noi,
    setup_base_asset,
    setup_loan_and_covenant,
    setup_plan_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
ANALYST = TEST_USERS["analyst"]
LENDER = TEST_USERS["lender"]


def _fix_a2_with_loan(api, months=4, principal=500000000, rate_bps=500,
                      covenant_type="MIN_DSCR", threshold_bps=12500,
                      maturity="2027-06-30"):
    """FY2026 plan with accepted RENT/CAM actuals (annualized NOI 30,000,000
    for the default month counts), plus a loan and one covenant."""
    ctx = setup_asset_with_noi(fiscal_year=2026, months=months)
    return setup_loan_and_covenant(ctx, principal=principal, rate_bps=rate_bps,
                                   covenant_type=covenant_type,
                                   threshold_bps=threshold_bps,
                                   maturity=maturity)


class TestWatchBreachCureCycle:
    """Difficulty instance: non_linear_state_machine /
    loan_watch_breach_cure_cycle.

    Loan 500,000,000 @ 500bps -> annual debt service 25,000,000; covenant
    MIN_DSCR threshold 12,500. Four months of actuals give annualized NOI
    30,000,000 (DSCR 12,000 -> FAIL); a strong month 5 (RENT 12,000,000)
    lifts annualized NOI to 51,600,000 (DSCR 20,640 -> PASS, curing).
    """

    def test_fail_breaches_covenant_and_watches_loan(self, api):
        """PRD §3.6: "A `FAIL` on an `ACTIVE` covenant breaches it — `ACTIVE`
        to `IN_BREACH` — stamps `last_breach_at` with the current clock time,
        moves the loan from `CURRENT` to `WATCH`, and recomputes the
        portfolio's `risk_posture`."

        Design: Difficulty/non_linear_state_machine/loan_watch_breach_cure_cycle
        """
        ctx = _fix_a2_with_loan(api)
        assert ctx["loan"]["status"] == "CURRENT"
        assert ctx["covenant"]["status"] == "ACTIVE"

        test = record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        assert test["result"] == "FAIL"
        assert test["measured_value_bps"] == 12000, (
            "round_half_up(30,000,000 * 10000 / 25,000,000) = 12,000 < 12,500")
        assert get_covenant(ctx["covenant"]["id"])["status"] == "IN_BREACH"
        assert get_loan(ctx["loan"]["id"])["status"] == "WATCH"

    def test_pass_inside_cure_window_restores_current(self, api):
        """PRD §3.6: "A `PASS` recorded against an `IN_BREACH` covenant cures
        it — back to `ACTIVE`, with `last_breach_at` cleared to null — and
        when no other covenant of the same loan remains in breach, the loan
        returns from `WATCH` to `CURRENT`, again recomputing posture."

        Design: Difficulty/non_linear_state_machine/loan_watch_breach_cure_cycle
        """
        ctx = _fix_a2_with_loan(api)
        record_covenant_test(ctx["covenant"]["id"], "2026-Q3")  # FAIL -> breach

        # Month-5 actuals: RENT 12,000,000 / CAM 500,000 lift the annualized
        # NOI to (4*2,500,000 + 11,500,000) * 12 / 5 = 51,600,000.
        pm_headers = make_property_manager_headers(ctx["manager"]["id"])
        rent_m5 = find_line(ctx["lines"], "RENT_REVENUE", 5)
        cam_m5 = find_line(ctx["lines"], "CAM_EXPENSE", 5)
        report = get_success_data(api.create_actuals_report(
            create_actuals_report_payload(ctx["plan"]["id"], 5, [
                actuals_line_entry(rent_m5["id"], 12000000),
                actuals_line_entry(cam_m5["id"], 500000)]), pm_headers))
        get_success_data(api.accept_actuals_report(report["id"], AM))

        test2 = record_covenant_test(ctx["covenant"]["id"], "2026-Q4")
        assert test2["result"] == "PASS"
        assert test2["measured_value_bps"] == 20640, (
            "round_half_up(51,600,000 * 10000 / 25,000,000) = 20,640")
        covenant = get_covenant(ctx["covenant"]["id"])
        assert covenant["status"] == "ACTIVE"
        assert covenant["last_breach_at"] is None
        assert get_loan(ctx["loan"]["id"])["status"] == "CURRENT"


class TestCovenantFailPostureCascade:
    """Difficulty instance: transitive_cascade /
    covenant_fail_cascades_to_portfolio_posture."""

    def test_fail_cascade_reaches_portfolio_posture(self, api):
        """PRD §3.6: "A `FAIL` on an `ACTIVE` covenant breaches it — `ACTIVE`
        to `IN_BREACH` ... moves the loan from `CURRENT` to `WATCH`, and
        recomputes the portfolio's `risk_posture`."
        PRD §3.9: "when exactly one loan is in `WATCH` and none in `DEFAULT`,
        the posture is `ELEVATED`; otherwise it is `NORMAL`."

        Design: Difficulty/transitive_cascade/covenant_fail_cascades_to_portfolio_posture
        """
        ctx = _fix_a2_with_loan(api)
        assert get_portfolio(ctx["portfolio"]["id"])["risk_posture"] == "NORMAL"

        record_covenant_test(ctx["covenant"]["id"], "2026-Q3")  # FAIL
        assert get_covenant(ctx["covenant"]["id"])["status"] == "IN_BREACH"
        assert get_loan(ctx["loan"]["id"])["status"] == "WATCH"
        assert get_portfolio(ctx["portfolio"]["id"])["risk_posture"] == "ELEVATED"

    def test_fail_test_record_carries_measure_and_noi(self, api):
        """PRD §3.6: "The measurement is computed once, at creation, and is
        immutable thereafter: the record carries `measured_value_bps`, the
        `annualized_noi_cents_used`, and a `result` of `PASS` or `FAIL`".

        Design: Difficulty/transitive_cascade/covenant_fail_cascades_to_portfolio_posture
        """
        ctx = _fix_a2_with_loan(api)
        test = record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        assert test["result"] == "FAIL"
        assert test["measured_value_bps"] == 12000
        assert test["annualized_noi_cents_used"] == 30000000


class TestDscrThresholdBoundary:
    """Difficulty instance: boundary_precision_check /
    dscr_exactly_at_threshold_passes.

    FIX with 4 accepted months (RENT 4,000,000 / CAM 500,000 per month):
    annualized NOI = 3,500,000 * 12 / 4 * ... = 42,000,000; loan 300,000,000
    @ 1000bps -> annual debt service 30,000,000; measured DSCR exactly
    14,000 against a 14,000 threshold.
    """

    def _setup(self, api):
        ctx = setup_asset_with_noi(fiscal_year=2026, months=4,
                                   rent_budget=4200000, rent_actual=4000000,
                                   line_set="fix_a1")
        return setup_loan_and_covenant(ctx, principal=300000000,
                                       rate_bps=1000, covenant_type="MIN_DSCR",
                                       threshold_bps=14000,
                                       maturity="2028-06-30")

    def test_dscr_exactly_at_threshold_passes(self, api):
        """PRD §3.6: "For `MIN_DSCR`, the measured value is the
        trailing-actuals annualized NOI times ten thousand divided by annual
        debt service, rounded half-up to a whole basis point, and the test
        passes when the measured value is at least `threshold_bps`."

        Design: Difficulty/boundary_precision_check/dscr_exactly_at_threshold_passes
        """
        ctx = self._setup(api)
        test = record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        assert test["measured_value_bps"] == 14000, \
            "round_half_up(42,000,000 * 10000 / 30,000,000)"
        assert test["result"] == "PASS", "the >= boundary is inclusive at 14,000"

    def test_exact_threshold_fires_no_breach_cascade(self, api):
        """PRD §3.6: "A `FAIL` on an `ACTIVE` covenant breaches it" — a PASS
        at the exact threshold leaves covenant ACTIVE and loan CURRENT.

        Design: Difficulty/boundary_precision_check/dscr_exactly_at_threshold_passes
        """
        ctx = self._setup(api)
        record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        assert get_covenant(ctx["covenant"]["id"])["status"] == "ACTIVE"
        assert get_loan(ctx["loan"]["id"])["status"] == "CURRENT"


class TestLtvFreshnessGate:
    """Difficulty instance: cross_entity_state_dependency /
    ltv_test_blocked_without_fresh_valuation."""

    def test_ltv_test_without_valuation_rejected(self, api):
        """PRD §3.6: "An LTV test with no confirmed valuation at all, or whose
        latest confirmed valuation's `effective_date` is more than 270 days
        before the clock date, fails closed with `ERR_STALE_VALUATION` and the
        test is not recorded".

        Design: Difficulty/cross_entity_state_dependency/ltv_test_blocked_without_fresh_valuation
        """
        ctx = setup_base_asset()
        loan = create_loan(ctx["asset"]["id"])
        covenant = create_covenant(loan["id"], covenant_type="MAX_LTV",
                                   threshold_bps=6500)
        res = api.create_covenant_test(
            create_covenant_test_payload(covenant["id"], "2026-Q3"), ANALYST)
        validate_error(res, ApiErrorId.ERR_STALE_VALUATION)

    def test_ltv_rejection_persists_no_test_record(self, api):
        """PRD §3.6: "An LTV test with no confirmed valuation at all, or whose
        latest confirmed valuation's `effective_date` is more than 270 days
        before the clock date, fails closed with `ERR_STALE_VALUATION` and the
        test is not recorded" — the covenant's test list stays empty.

        Design: Difficulty/cross_entity_state_dependency/ltv_test_blocked_without_fresh_valuation
        """
        ctx = setup_base_asset()
        loan = create_loan(ctx["asset"]["id"])
        covenant = create_covenant(loan["id"], covenant_type="MAX_LTV",
                                   threshold_bps=6500)
        validate_error(api.create_covenant_test(
            create_covenant_test_payload(covenant["id"], "2026-Q3"), ANALYST),
            ApiErrorId.ERR_STALE_VALUATION)
        _, meta = validate_paginated(api.list_covenant_tests(covenant["id"],
                                                             ANALYST))
        assert meta["total_count"] == 0


class TestDuplicateTestBeatsStaleValuation:
    """Difficulty instance: priority_pair_validation_conflict /
    duplicate_test_conflict_beats_stale_valuation.

    Valuation 500,000,000 effective 2026-07-01 is CONFIRMED; the 2026-Q3 LTV
    test records PASS at the default clock (valuation age 31 days). With the
    clock at 2027-05-01 the valuation is over 270 days old, but a repeated
    2026-Q3 label trips the uniqueness tier first.
    """

    def _setup(self, api):
        ctx = setup_asset_with_noi(fiscal_year=2026, months=1,
                                   rent_budget=4200000, rent_actual=4000000,
                                   line_set="fix_a1")
        setup_loan_and_covenant(ctx, principal=300000000, rate_bps=1000,
                                covenant_type="MAX_LTV", threshold_bps=6500,
                                maturity="2028-06-30")
        valuation = get_success_data(api.create_valuation(
            create_valuation_payload(ctx["asset"]["id"], "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=500000000), ANALYST))
        confirm_valuation_fresh(valuation["id"], ctx["asset"]["id"])
        return ctx

    def test_duplicate_period_conflict_beats_stale_valuation(self, api):
        """PRD §3.6: "Only one test may exist per covenant and period
        (`ERR_DUPLICATE_COVENANT_TEST`)".
        PRD §2.9 lists "9. Shape and uniqueness" before "10. Clock-derived
        temporal rules (`ERR_FUTURE_PERIOD`, `ERR_VALUATION_REGRESSIVE`,
        `ERR_STALE_VALUATION`, ...)".

        Design: Difficulty/priority_pair_validation_conflict/duplicate_test_conflict_beats_stale_valuation
        """
        ctx = self._setup(api)
        first = record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        assert first["result"] == "PASS"
        set_clock("2027-05-01T00:00:00Z")  # valuation now 300+ days old
        res = api.create_covenant_test(
            create_covenant_test_payload(ctx["covenant"]["id"], "2026-Q3"),
            ANALYST)
        err = validate_error(res, ApiErrorId.ERR_DUPLICATE_COVENANT_TEST)
        assert err["error_id"] == "ERR_DUPLICATE_COVENANT_TEST", \
            "NOT ERR_STALE_VALUATION though the valuation is stale at trigger"

    def test_fresh_valuation_ltv_passes_at_baseline(self, api):
        """PRD §3.6: "`MAX_LTV` works off value rather than income: it reads
        the asset's latest confirmed valuation (latest by `effective_date`,
        which strictly increases per §3.5, so no tie is possible), measures
        the principal times ten thousand divided by that valuation's implied
        value with half-up rounding, and passes when the measured value is at
        most `threshold_bps`."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_test_conflict_beats_stale_valuation
        """
        ctx = self._setup(api)
        test = record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        assert test["measured_value_bps"] == 6000, \
            "round_half_up(300,000,000 * 10000 / 500,000,000)"
        assert test["result"] == "PASS", "6,000 <= 6,500 threshold"


class TestCovenantMeasures:
    def test_dscr_test_without_noi_evidence_rejected(self, api):
        """PRD §3.6: "Both NOI-based tests refuse to run before any actuals
        exist: when the trailing-actuals NOI is null, creation fails with
        `ERR_NO_NOI_EVIDENCE`."

        Design: Corner/calculations/dscr_test_without_noi_evidence_rejected
        """
        ctx = setup_plan_scenario(fiscal_year=2026, lines=lines_plan10())
        loan = create_loan(ctx["asset"]["id"])
        covenant = create_covenant(loan["id"], covenant_type="MIN_DSCR",
                                   threshold_bps=12500)
        res = api.create_covenant_test(
            create_covenant_test_payload(covenant["id"], "2026-Q3"), ANALYST)
        validate_error(res, ApiErrorId.ERR_NO_NOI_EVIDENCE)
        _, meta = validate_paginated(api.list_covenant_tests(covenant["id"],
                                                             ANALYST))
        assert meta["total_count"] == 0, "a refused test is not recorded"

    def test_debt_yield_test_passes_at_computed_value(self, api):
        """PRD §3.6: "`MIN_DEBT_YIELD` substitutes the principal balance for
        debt service — NOI times ten thousand divided by principal, rounded
        half-up — and likewise passes at or above threshold."

        Design: Corner/calculations/debt_yield_test_passes_at_computed_value
        """
        # Month-1-only actuals: ytd NOI 3,000,000 - 500,000 = 2,500,000 over
        # M=1 -> annualized 30,000,000; principal 500,000,000 -> 600 bps.
        ctx = setup_asset_with_noi(fiscal_year=2026, months=1)
        setup_loan_and_covenant(ctx, principal=500000000, rate_bps=500,
                                covenant_type="MIN_DEBT_YIELD",
                                threshold_bps=500)
        test = record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        assert test["annualized_noi_cents_used"] == 30000000
        assert test["measured_value_bps"] == 600, \
            "round_half_up(30,000,000 * 10000 / 500,000,000)"
        assert test["result"] == "PASS", "600 >= 500 threshold"
        assert get_covenant(ctx["covenant"]["id"])["status"] == "ACTIVE"

    def test_ltv_valuation_age_boundary_270_days(self, api):
        """PRD §3.6: "An LTV test with no confirmed valuation at all, or whose
        latest confirmed valuation's `effective_date` is more than 270 days
        before the clock date, fails closed with `ERR_STALE_VALUATION` and the
        test is not recorded" — exactly 270 days old still tests.

        Design: Corner/calculations/ltv_valuation_age_boundary_270_days
        """
        ctx = setup_base_asset()
        loan = create_loan(ctx["asset"]["id"])
        covenant = create_covenant(loan["id"], covenant_type="MAX_LTV",
                                   threshold_bps=6500)
        valuation = get_success_data(api.create_valuation(
            create_valuation_payload(ctx["asset"]["id"], "2026-01-15",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=500000000), ANALYST))
        confirm_valuation_fresh(valuation["id"], ctx["asset"]["id"])

        set_clock("2026-10-12T00:00:00Z")  # valuation age exactly 270 days
        test = record_covenant_test(covenant["id"], "2026-Q3")
        assert test["measured_value_bps"] == 6000
        assert test["result"] == "PASS", "the freshness window is inclusive"

        set_clock("2026-10-13T00:00:00Z")  # age 271 — now stale
        res = api.create_covenant_test(
            create_covenant_test_payload(covenant["id"], "2026-Q4"), ANALYST)
        validate_error(res, ApiErrorId.ERR_STALE_VALUATION)


class TestCovenantWaive:
    def test_waive_active_covenant_rejected(self, api):
        """PRD §3.6: "waiving requires the covenant to be `IN_BREACH`
        (`ERR_COVENANT_NOT_WAIVABLE`)".

        Design: Corner/validations/waive_active_covenant_rejected
        """
        ctx = setup_base_asset()
        loan = create_loan(ctx["asset"]["id"])
        covenant = create_covenant(loan["id"], covenant_type="MIN_DSCR",
                                   threshold_bps=12500)
        res = api.waive_covenant(covenant["id"], LENDER)
        validate_error(res, ApiErrorId.ERR_COVENANT_NOT_WAIVABLE)
        assert get_covenant(covenant["id"])["status"] == "ACTIVE"

    def test_waive_breached_covenant_cures_loan(self, api):
        """PRD §3.6: "A `Lender` may instead forgive a breach: waiving
        requires the covenant to be `IN_BREACH` (`ERR_COVENANT_NOT_WAIVABLE`),
        moves it to `WAIVED` (terminal), and when no other covenant of the
        loan remains in breach and the loan sits in `WATCH`, returns the loan
        to `CURRENT` with a posture recompute."

        Design: Corner/endpoints/waive_breached_covenant_cures_loan
        """
        ctx = _fix_a2_with_loan(api, months=1)
        record_covenant_test(ctx["covenant"]["id"], "2026-Q3")  # FAIL
        assert get_portfolio(ctx["portfolio"]["id"])["risk_posture"] == "ELEVATED"

        waived = validate_success(api.waive_covenant(ctx["covenant"]["id"],
                                                     LENDER), 200)
        assert waived["status"] == "WAIVED"
        assert get_loan(ctx["loan"]["id"])["status"] == "CURRENT"
        assert get_portfolio(ctx["portfolio"]["id"])["risk_posture"] == "NORMAL", \
            "the full breach cascade unwinds on waiver"

    def test_covenant_test_on_waived_covenant_rejected(self, api):
        """PRD §3.6: "a test against a `WAIVED` covenant — or against a loan
        in `DEFAULT`, `REFINANCED`, or `PAID_OFF` — is refused with
        `ERR_COVENANT_NOT_TESTABLE`."

        Design: Corner/state_machines/covenant_test_on_waived_covenant_rejected
        """
        ctx = _fix_a2_with_loan(api, months=1)
        test = record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        assert test["result"] == "FAIL"  # 12,000 < 12,500 -> breach
        validate_success(api.waive_covenant(ctx["covenant"]["id"], LENDER), 200)
        res = api.create_covenant_test(
            create_covenant_test_payload(ctx["covenant"]["id"], "2026-Q4"),
            ANALYST)
        validate_error(res, ApiErrorId.ERR_COVENANT_NOT_TESTABLE)


class TestLoanAndTestRecords:
    def test_second_active_loan_rejected(self, api):
        """PRD §3.6: "An asset carries at most one live loan: while any loan
        in `CURRENT`, `WATCH`, or `DEFAULT` exists for the asset, another
        origination is refused with `ERR_LOAN_EXISTS`."

        Design: Corner/validations/second_active_loan_rejected
        """
        ctx = setup_base_asset()
        create_loan(ctx["asset"]["id"])
        res = api.create_loan(
            create_loan_payload(ctx["asset"]["id"], lender_name="Bank2",
                                principal_balance_cents=200000000,
                                annual_interest_rate_bps=900,
                                origination_date="2026-02-01",
                                maturity_date="2029-01-31"), DIRECTOR)
        validate_error(res, ApiErrorId.ERR_LOAN_EXISTS)

    def test_covenant_test_immutable_no_version_field(self, api):
        """PRD §2.4: "the covenant test is an append-only measurement record
        and carries only `id` and `created_at`. Because a recorded covenant
        test never changes after creation, `updated_at` and `version` are both
        absent from it."
        PRD §3.6: "The measurement is computed once, at creation, and is
        immutable thereafter: the record carries `measured_value_bps`, the
        `annualized_noi_cents_used`, and a `result` of `PASS` or `FAIL`".

        Design: Corner/entities/covenant_test_immutable_no_version_field
        """
        # Month-1-only FIX A1: ytd NOI 3,500,000 -> annualized 42,000,000;
        # ADS 300,000,000 @ 1000bps = 30,000,000 -> measured 14,000.
        ctx = setup_asset_with_noi(fiscal_year=2026, months=1,
                                   rent_budget=4200000, rent_actual=4000000,
                                   line_set="fix_a1")
        setup_loan_and_covenant(ctx, principal=300000000, rate_bps=1000,
                                covenant_type="MIN_DSCR", threshold_bps=12500,
                                maturity="2028-06-30")
        recorded = record_covenant_test(ctx["covenant"]["id"], "2026-Q3")
        data, meta = validate_paginated(
            api.list_covenant_tests(ctx["covenant"]["id"], ANALYST))
        assert meta["total_count"] == 1
        test = data[0]
        assert test["id"] == recorded["id"]
        assert_covenant_test(test)
        assert test["measured_value_bps"] == 14000
        assert test["annualized_noi_cents_used"] == 42000000
        assert test["result"] == "PASS", "14,000 >= 12,500"
        assert test["covenant_id"] == ctx["covenant"]["id"]
        assert test["period_label"] == "2026-Q3"
