"""The monthly ALCO reporting cycle: coverage gates, open-breach gates,
segregation of duties, and the volatility of a submitted pack
(PRD §2.10, §3.8)."""

from test_helpers import (
    ALL_PRESET_CODES,
    AN1,
    ApiErrorId,
    acknowledge_breach,
    assert_alco_report,
    close_breach,
    create_alco_report,
    create_book,
    create_run,
    get_alco_report,
    list_breaches,
    make_analyst_headers,
    make_chair_headers,
    setup_full_alco_cycle,
    validate_error,
    validate_success,
)


class TestReportPeriodUniqueness:
    def test_report_period_conflict_rejected(self, api):
        """PRD §3.8: "Only one non-terminal report may exist for a book and
        period — a second creation while a `DRAFT` or `SUBMITTED` report
        exists for the same pair is rejected with
        `ERR_REPORT_PERIOD_CONFLICT` (HTTP 409)."

        Design: Corner/validations/report_period_conflict_rejected
        """
        book = create_book()
        create_alco_report(book["id"], "2026-08")
        resp = api.create_alco_report(book["id"], {"period_month": "2026-08"},
                                      AN1)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_CONFLICT)


class TestRegulatoryCoverageGate:
    def test_report_submit_requires_full_regulatory_coverage(self, api):
        """PRD §3.8: "Submission moves the report `DRAFT → SUBMITTED` and
        requires complete regulatory coverage — a submission while
        `regulatory_coverage_complete` is false is rejected with
        `ERR_REGULATORY_COVERAGE_INCOMPLETE` (HTTP 409)." PRD §3.8:
        "`regulatory_coverage_complete` is true exactly when each of the six
        `preset_code` values has at least one `PUBLISHED` run in the period."

        Design: Corner/endpoints/report_submit_requires_full_regulatory_coverage
        """
        five = [c for c in ALL_PRESET_CODES if c != "REG_DOWN_400"]
        ctx = setup_full_alco_cycle(preset_codes=five, submit=False)
        report = get_alco_report(ctx["report"]["id"])
        assert report["run_count"] == 5
        assert report["regulatory_coverage_complete"] is False, (
            "REG_DOWN_400 has no PUBLISHED run in the period")
        resp = api.submit_alco_report(report["id"],
                                      make_analyst_headers("an-1"))
        validate_error(resp, ApiErrorId.ERR_REGULATORY_COVERAGE_INCOMPLETE)
        assert get_alco_report(report["id"])["status"] == "DRAFT"


class TestOpenBreachGate:
    def test_report_acknowledge_blocked_by_open_breach(self, api):
        """PRD §3.8: "Acknowledgement by the `ALCOChair` moves the report
        `SUBMITTED → ACKNOWLEDGED`, its terminal state, under two guards: the
        `open_breach_count` must be zero, else `ERR_OPEN_BREACHES_REMAIN`
        (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/report_acknowledge_blocked_by_open_breach
        """
        ctx = setup_full_alco_cycle(nii_threshold_pct=5.0,
                                    eve_threshold_pct=12.0)
        report = ctx["report"]
        assert report["status"] == "SUBMITTED"
        resp = api.acknowledge_alco_report(report["id"],
                                           make_chair_headers("ch-1"))
        validate_error(resp, ApiErrorId.ERR_OPEN_BREACHES_REMAIN)
        assert get_alco_report(report["id"])["status"] == "SUBMITTED"

    def test_acknowledge_succeeds_after_all_breaches_closed(self, api):
        """PRD §3.8: "`open_breach_count` counts the book's breaches in the
        period whose status is anything other than `CLOSED`." PRD §3.8: "the
        `open_breach_count` must be zero, else `ERR_OPEN_BREACHES_REMAIN`".
        The six preset runs with 5.0 / 12.0 thresholds open seven breaches
        (U4 2, U3 2, U2 1, D3 1, D4 1).

        Design: Difficulty/cross_entity_state_dependency/report_acknowledge_blocked_by_open_breach
        """
        ctx = setup_full_alco_cycle(nii_threshold_pct=5.0,
                                    eve_threshold_pct=12.0)
        report = get_alco_report(ctx["report"]["id"])
        assert report["open_breach_count"] == 7
        breaches = list_breaches({"book_id": ctx["book"]["id"]})
        assert len(breaches) == 7
        for b in breaches:
            acknowledge_breach(b["id"])
            close_breach(b["id"], "Remediated")
        assert get_alco_report(report["id"])["open_breach_count"] == 0
        acked = validate_success(api.acknowledge_alco_report(
            report["id"], make_chair_headers("ch-1")))
        assert_alco_report(acked)
        assert acked["status"] == "ACKNOWLEDGED"


class TestSubmittedPackVolatility:
    def test_breach_creation_reverts_submitted_report(self, api):
        """PRD §3.8: "whenever a run in the period is published, or a breach
        is created in the period, while the report is `SUBMITTED`, the report
        auto-reverts from `SUBMITTED` to `DRAFT`, `submitted_by_user_id` is
        reset, and the aggregates are recomputed."

        Design: Difficulty/transitive_cascade/breach_creation_reverts_submitted_report
        """
        ctx = setup_full_alco_cycle(nii_threshold_pct=5.0,
                                    eve_threshold_pct=12.0)
        assert ctx["report"]["status"] == "SUBMITTED"
        # A second +200 preset run breaches the EVE limit again (EVE delta
        # -25.33 < -12.0) but not the 5.0 NII limit (-4.57 > -5.0).
        run = create_run(ctx["book"]["id"],
                         ctx["scenarios"]["REG_UP_200"]["id"],
                         ctx["ps"]["id"], ctx["ds"]["id"], ctx["bs"]["id"])
        assert run["breach_summary"] == "EVE"
        report = get_alco_report(ctx["report"]["id"])
        assert report["status"] == "DRAFT"
        assert report["submitted_by_user_id"] is None

    def test_reverting_resets_submitter_and_keeps_aggregates_recomputed(
            self, api):
        """PRD §3.8: "the report auto-reverts from `SUBMITTED` to `DRAFT`,
        `submitted_by_user_id` is reset, and the aggregates are recomputed."
        PRD §3.8: "These aggregates are recomputed whenever runs are
        published, breaches are created, acknowledged, or closed, or the
        report is created."

        Design: Difficulty/transitive_cascade/breach_creation_reverts_submitted_report
        """
        ctx = setup_full_alco_cycle(nii_threshold_pct=5.0,
                                    eve_threshold_pct=12.0)
        before = get_alco_report(ctx["report"]["id"])
        assert before["open_breach_count"] == 7
        create_run(ctx["book"]["id"], ctx["scenarios"]["REG_UP_200"]["id"],
                   ctx["ps"]["id"], ctx["ds"]["id"], ctx["bs"]["id"])
        report = get_alco_report(ctx["report"]["id"])
        assert report["status"] == "DRAFT"
        assert report["submitted_by_user_id"] is None
        assert report["open_breach_count"] == 8, (
            "the new EVE breach is recomputed into the reverted pack")


class TestReportSegregation:
    def test_report_self_acknowledge_violates_segregation(self, api):
        """PRD §3.8: "the acknowledger's `X-User-ID` must differ from
        `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).
        The server records `acknowledged_by_user_id`." PRD §2.10: "an ALCO
        report may not be acknowledged by the same operator who submitted
        it."

        Design: Corner/rbac/report_self_acknowledge_violates_segregation
        """
        # No policy limits: zero breaches, so only the segregation guard
        # stands between the submitted report and acknowledgement.
        ctx = setup_full_alco_cycle(submitter_user_id="an-1")
        report = ctx["report"]
        assert report["status"] == "SUBMITTED"
        assert report["submitted_by_user_id"] == "an-1"
        resp = api.acknowledge_alco_report(report["id"],
                                           make_chair_headers("an-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        acked = validate_success(api.acknowledge_alco_report(
            report["id"], make_chair_headers("ch-1")))
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["acknowledged_by_user_id"] == "ch-1"
