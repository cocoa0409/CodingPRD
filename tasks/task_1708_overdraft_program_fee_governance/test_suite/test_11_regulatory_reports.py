"""Regulatory reports (PRD §3.9): closed-interval tiling, provisional vs final
revenue bases, scrutiny metrics, and submission segregation of duties."""
from test_helpers import (
    ApiErrorId,
    authorize,
    create_report,
    list_fees,
    make_opted_in_account,
    make_program,
    open_batch,
    run_posting_day,
    seal_batch,
    set_clock,
    settle_batch,
    submit_waiver,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import COMPLIANCE, TELLER
from test_helpers.test_users import make_compliance_headers


class TestReportRevenueProvisionalVsFinalBasis:
    def _setup(self):
        """Mon: credit 10000 (sealed+settled). Tue: debit 12000 (fee 3500
        POSTED after settle). Wed: debit 1000, batch SEALED only (fee 3500
        ASSESSED)."""
        program = make_program(name="OD-R")
        account, _ = make_opted_in_account(program["id"], holder_name="Holder R",
                                           channel="ONLINE")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("CREDIT_DEPOSIT", 10000)], settle=True)
        run_posting_day(program["id"], "2026-08-04", account["id"],
                        [("DEBIT_ONE_TIME", 12000)], settle=True)
        batch3 = open_batch(program["id"], "2026-08-05")
        authorize(account["id"], "DEBIT_ONE_TIME", 1000)
        seal_batch(batch3["id"])
        return program

    def test_provisional_includes_assessed_fee_final_excludes_it(self, api):
        """PRD §3.9: "The provisional, accrual basis
        `revenue_provisional_cents` sums, over all fees whose period date falls
        inside the closed period and whose status is `ASSESSED`, `POSTED`, or
        `WAIVED`, each fee's `amount_cents` minus its `waived_cents`."
        PRD §3.9: "The settled basis `revenue_final_cents` applies the same sum
        but over fees whose status is `POSTED` or `WAIVED` only, excluding
        `ASSESSED` fees; whenever any batch covering the period is sealed but
        not yet settled, identical period data therefore yields a final figure
        at or below the provisional one."

        Design: Difficulty/dual_variant_calc/report_revenue_provisional_vs_final_basis
        """
        program = self._setup()
        report = create_report(program["id"], "2026-08-03", "2026-08-05",
                               headers=COMPLIANCE)
        finalized = validate_success(api.finalize_report(
            report["id"], make_compliance_headers("co-1")))
        # POSTED 3500 + ASSESSED 3500 on the accrual basis.
        assert finalized["revenue_provisional_cents"] == 7000
        # The settled basis excludes the ASSESSED fee.
        assert finalized["revenue_final_cents"] == 3500

    def test_zero_waiver_period_metrics(self, api):
        """PRD §3.9: "The per-overdrafter average
        `avg_fees_per_overdrafter_centi` multiplies the count of the period's
        `POSTED` and `WAIVED` fees by 100, divides by the number of distinct
        accounts carrying at least one such fee, and discards any remainder".
        PRD §3.9: "The `scrutiny_flag` is true exactly when the waiver ratio is
        strictly greater than 1500 basis points — that is, more than fifteen
        percent of assessed fee value was waived — or the average is at least
        1200 hundredths, meaning twelve or more fees per overdrafter."

        Design: Difficulty/dual_variant_calc/report_revenue_provisional_vs_final_basis
        """
        program = self._setup()
        report = create_report(program["id"], "2026-08-03", "2026-08-05",
                               headers=COMPLIANCE)
        finalized = validate_success(api.finalize_report(
            report["id"], make_compliance_headers("co-1")))
        assert finalized["waiver_ratio_bps"] == 0
        assert finalized["avg_fees_per_overdrafter_centi"] == 100
        assert finalized["scrutiny_flag"] is False


class TestReportPeriodsClosedIntervalTiling:
    def _setup(self):
        program = make_program(name="OD-G")
        r1 = create_report(program["id"], "2026-08-01", "2026-08-31")
        assert r1["status"] == "OPEN"  # first report: gap rule exempt
        return program, r1

    def test_overlapping_period_rejected(self, api):
        """PRD §3.9: "A period that intersects any existing report's closed
        interval is rejected with `ERR_REPORT_PERIOD_OVERLAP`, and this overlap
        check runs before the gap check".

        Design: Difficulty/resource_temporal_overlap/report_periods_closed_interval_tiling
        """
        program, _ = self._setup()
        # Start 2026-08-15 is inside [2026-08-01, 2026-08-31]; the overlap is
        # reported even though the start is also not the day after the prior
        # period_end.
        resp = api.create_report(
            {"program_id": program["id"], "period_start": "2026-08-15",
             "period_end": "2026-09-15"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    def test_gap_rejected_and_exact_tiling_accepted(self, api):
        """PRD §3.9: "then, unless this is the program's first report (which
        may start on any date), the `period_start` must be exactly one day
        after the previous report's `period_end`, else the creation is rejected
        with `ERR_REPORT_PERIOD_GAP`."

        Design: Difficulty/resource_temporal_overlap/report_periods_closed_interval_tiling
        """
        program, _ = self._setup()
        gap = api.create_report(
            {"program_id": program["id"], "period_start": "2026-09-02",
             "period_end": "2026-09-30"}, COMPLIANCE)
        validate_error(gap, ApiErrorId.ERR_REPORT_PERIOD_GAP)

        r4 = validate_success(api.create_report(
            {"program_id": program["id"], "period_start": "2026-09-01",
             "period_end": "2026-09-30"}, COMPLIANCE), 201)
        assert r4["status"] == "OPEN"
        r5 = validate_success(api.create_report(
            {"program_id": program["id"], "period_start": "2026-10-01",
             "period_end": "2026-10-31"}, COMPLIANCE), 201)
        assert r5["status"] == "OPEN"


class TestReportMetricsScrutinyFlagTrue:
    def test_high_waiver_ratio_flags_scrutiny(self, api):
        """PRD §3.9: "The waiver ratio `waiver_ratio_bps` divides the total
        `waived_cents` across the period's `POSTED` and `WAIVED` fees by the
        total `amount_cents` of those same fees, multiplies by 10000 to express
        the result in basis points, and discards any remainder".
        PRD §3.9: "The `scrutiny_flag` is true exactly when the waiver ratio is
        strictly greater than 1500 basis points".

        Design: Corner/calculations/report_metrics_scrutiny_flag_true
        """
        program = make_program(name="OD-CAL5", daily_fee_cap_cents=20000,
                               max_daily_fees_count=5,
                               steering_fee_count_threshold=99)
        account, _ = make_opted_in_account(program["id"], holder_name="H CAL5")
        batch = open_batch(program["id"], "2026-08-03")
        for clock in ("2026-08-03T09:00:00Z", "2026-08-03T09:01:00Z",
                      "2026-08-03T09:02:00Z", "2026-08-03T09:03:00Z"):
            set_clock(clock)
            authorize(account["id"], "DEBIT_ONE_TIME", 1000)
        seal_batch(batch["id"])
        settle_batch(batch["id"])
        fee = list_fees(account_id=account["id"])[0]
        request = submit_waiver(account["id"], [fee["id"]], kind="FIXED_AMOUNT",
                                amount_cents=3000, reason_code="GOODWILL",
                                headers=TELLER)
        assert request["status"] == "APPLIED"  # 3000 <= teller cap, staff

        report = create_report(program["id"], "2026-08-03", "2026-08-03",
                               headers=COMPLIANCE)
        finalized = validate_success(api.finalize_report(
            report["id"], make_compliance_headers("co-1")))
        # floor(3000*10000/14000) = 2142 > 1500.
        assert finalized["waiver_ratio_bps"] == 2142
        assert finalized["scrutiny_flag"] is True
        # 4 fees * 100 / 1 overdrafter.
        assert finalized["avg_fees_per_overdrafter_centi"] == 400
        # 14000 - 3000; all batches settled, so the two bases agree.
        assert finalized["revenue_provisional_cents"] == 11000
        assert finalized["revenue_final_cents"] == 11000


class TestReportScrutinyRatioExactBoundary:
    def test_ratio_exactly_1500_is_not_flagged(self, api):
        """PRD §3.9: "The `scrutiny_flag` is true exactly when the waiver ratio
        is strictly greater than 1500 basis points — that is, more than fifteen
        percent of assessed fee value was waived — or the average is at least
        1200 hundredths, meaning twelve or more fees per overdrafter."

        Design: Corner/calculations/report_scrutiny_ratio_exact_1500_not_flagged
        """
        program = make_program(name="OD-CAL6", fee_amount_cents=2500,
                               daily_fee_cap_cents=20000,
                               max_daily_fees_count=5,
                               steering_fee_count_threshold=99)
        account, _ = make_opted_in_account(program["id"], holder_name="H CAL6",
                                           channel="ONLINE")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("DEBIT_ONE_TIME", 1000)] * 4, settle=True,
                        clock_times=["2026-08-03T09:00:00Z",
                                     "2026-08-03T09:01:00Z",
                                     "2026-08-03T09:02:00Z",
                                     "2026-08-03T09:03:00Z"])
        fee = list_fees(account_id=account["id"])[0]
        submit_waiver(account["id"], [fee["id"]], kind="FIXED_AMOUNT",
                      amount_cents=1500, reason_code="GOODWILL", headers=TELLER)

        report = create_report(program["id"], "2026-08-03", "2026-08-03",
                               headers=COMPLIANCE)
        finalized = validate_success(api.finalize_report(
            report["id"], make_compliance_headers("co-1")))
        # floor(1500*10000/10000) = 1500; strict > 1500: exact boundary clear.
        assert finalized["waiver_ratio_bps"] == 1500
        assert finalized["scrutiny_flag"] is False
        assert finalized["revenue_final_cents"] == 8500  # 10000 - 1500


class TestReportSelfSubmissionForbidden:
    def test_finalizer_cannot_submit_and_empty_period_finalizes_zero(self, api):
        """PRD §3.9: "the submitter's `X-User-ID` must differ from
        `finalized_by_user_id`, else the submission is rejected with
        `ERR_SELF_SUBMISSION_FORBIDDEN`."
        PRD §3.9: "when no such fees exist the ratio is zero" and "when no
        account has such a fee the average is zero".

        Design: Corner/validations/report_self_submission_forbidden
        """
        program = make_program(name="OD-V14")
        report = create_report(program["id"], "2026-08-01", "2026-08-31")

        finalized = validate_success(api.finalize_report(
            report["id"], make_compliance_headers("co-1")))
        # Empty-period floor-division guard.
        assert finalized["revenue_provisional_cents"] == 0
        assert finalized["revenue_final_cents"] == 0
        assert finalized["waiver_ratio_bps"] == 0
        assert finalized["avg_fees_per_overdrafter_centi"] == 0
        assert finalized["scrutiny_flag"] is False

        resp = api.submit_report(report["id"], make_compliance_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_SELF_SUBMISSION_FORBIDDEN)

        submitted = validate_success(api.submit_report(
            report["id"], make_compliance_headers("co-2")))
        assert submitted["status"] == "SUBMITTED"
