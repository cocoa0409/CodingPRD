"""Determination reversal cascades and community benefit reporting: account
balance conservation, the application revision loop, and the report amendment
cycle."""
from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    assert_community_benefit_report,
    build_verified_application,
    create_active_policy,
    create_determination,
    create_report,
    file_report,
    finalize_determination,
    get_account,
    get_application,
    get_report,
    list_determination_adjustments,
    post_adjustment,
    recompute_report,
    reopen_report,
    request_documents,
    resume_review,
    reverse_determination,
    set_clock,
    setup_posted_writeoff,
    setup_verified_application,
    upload_and_verify,
    validate_error,
)


def _approved_with_writeoff(**overrides):
    """APPROVED application (TIER_FULL on responsibility 500000 by default)
    with the WRITE_OFF posted; account RESOLVED."""
    overrides.setdefault("patient_name", "Cyclical Casey")
    overrides.setdefault("mrn", "MRN-CYC-1")
    overrides.setdefault("ssn_last4", "8888")
    overrides.setdefault("date_of_birth", "1990-01-01")
    overrides.setdefault("reported_income", 2000000)
    overrides.setdefault("accounts", ((500000, 0),))
    overrides.setdefault("tax_return_amount", 2000000)
    overrides.setdefault("members", (("SELF", 36),))
    overrides.setdefault("encounter_date", "2026-01-05")
    ctx = setup_posted_writeoff(**overrides)
    return ctx


class TestApplicationRevisionLoop:
    def test_reversal_reopens_approved_application(self, api):
        """PRD §3.8: "The application itself returns `APPROVED → UNDER_REVIEW`
        for re-determination — the revision loop that makes determinations
        legitimately supersede one another, and the reason creation is
        OCC-guarded."

        Design: Difficulty/non_linear_state_machine/application_review_document_cycle_and_reopen
        """
        ctx = setup_verified_application(
            patient_name="Cyclical Casey", mrn="MRN-CYC-1", ssn_last4="8888",
            date_of_birth="1990-01-01", reported_income=2000000,
            accounts=((500000, 0),), tax_return_amount=2000000,
            members=(("SELF", 36),),
        )
        app_id = ctx["application"]["id"]
        # exercise the document loop: UNDER_REVIEW -> PENDING_DOCUMENTS -> UNDER_REVIEW
        pending = request_documents(app_id, ["BANK_STATEMENT"])
        assert pending["status"] == "PENDING_DOCUMENTS"
        upload_and_verify(
            app_id, ctx["members"][0]["id"], doc_type="BANK_STATEMENT",
            amount_cents=100000, period_start="2026-01-01",
            period_end="2026-01-31",
        )
        resumed = resume_review(app_id)
        assert resumed["status"] == "UNDER_REVIEW"
        assert resumed["requested_doc_types"] == []
        det = create_determination(
            app_id, "VERIFIED_APPLICATION", [ctx["accounts"][0]["id"]]
        )
        det = finalize_determination(det["id"])
        app = get_application(app_id)
        assert app["status"] == "APPROVED"
        reversed_det = reverse_determination(det["id"], reason="audit finding")
        assert reversed_det["status"] == "REVERSED"
        app = get_application(app_id)
        assert app["status"] == "UNDER_REVIEW", (
            "reversal of the FINAL determination reopens the decided application"
        )

    def test_reversal_restores_account_balance_and_posture(self, api):
        """PRD §3.8: "First, every `POSTED` write-off adjustment of this
        determination moves to `REVERSED` with `reversed_at` stamped; refund
        adjustments are left `POSTED`. Second, each affected account recomputes
        its `adjusted_balance_cents`, and any account that had been `RESOLVED`
        but now shows `amount_outstanding_cents` greater than zero transitions
        back to `NOTICE_PERIOD`."

        Design: Difficulty/non_linear_state_machine/application_review_document_cycle_and_reopen
        """
        ctx = _approved_with_writeoff()
        account_id = ctx["accounts"][0]["id"]
        det_id = ctx["determination"]["id"]
        account = get_account(account_id)
        assert account["collection_posture"] == "RESOLVED"
        reverse_determination(det_id, reason="audit finding")
        adjustments = list_determination_adjustments(det_id)
        write_offs = [a for a in adjustments if a["adjustment_type"] == "WRITE_OFF"]
        assert len(write_offs) == 1
        assert write_offs[0]["status"] == "REVERSED"
        assert write_offs[0]["reversed_at"] is not None
        account = get_account(account_id)
        assert account["adjusted_balance_cents"] == 500000, "write-off reversed"
        assert account["amount_outstanding_cents"] == 500000
        assert account["collection_posture"] == "NOTICE_PERIOD", (
            "RESOLVED re-opens to NOTICE_PERIOD once a balance reappears"
        )


class TestWriteOffReversalConservation:
    def _conserve_setup(self):
        """75.00% write-off (750000 on responsibility 1000000) posted."""
        return setup_posted_writeoff(
            patient_name="Conserve Connie", mrn="MRN-CONS-1", ssn_last4="1717",
            date_of_birth="1986-07-07", reported_income=3750000,
            accounts=((1000000, 0),), tax_return_amount=3750000,
            members=(("SELF", 39),),
        )

    def test_writeoff_reverse_pair_conserves_balance(self, api):
        """PRD §2.12: "First, `adjusted_balance_cents` is the account's
        creation-fixed `patient_responsibility_cents` minus the sum of
        `amount_cents` over all of the account's `POSTED` write-off
        adjustments."
        PRD §3.10: "Adjustments are durable with one asymmetry: a `WRITE_OFF`
        can be reversed only through reversal of its owning determination
        (§3.8), which stamps `reversed_at` and recomputes the account's
        `adjusted_balance_cents`; a `REFUND` adjustment is never reversible,
        and any reversal attempt against one is rejected with
        `ERR_REFUND_NOT_REVERSIBLE` (HTTP 409)."

        Design: Difficulty/compensating_invariant/writeoff_reverse_pair_conserves_account_balance
        """
        ctx = self._conserve_setup()
        adjustment = ctx["adjustment"]
        assert adjustment["amount_cents"] == 750000, "75.00% of 1000000"
        account = get_account(ctx["accounts"][0]["id"])
        assert account["adjusted_balance_cents"] == 250000
        reverse_determination(
            ctx["determination"]["id"], headers=COMPLIANCE, reason="post-payment audit"
        )
        account = get_account(ctx["accounts"][0]["id"])
        assert account["adjusted_balance_cents"] == 1000000, (
            "forward + compensating pair leaves zero drift on the balance"
        )

    def test_writeoff_reversal_restores_outstanding(self, api):
        """PRD §3.8: "First, every `POSTED` write-off adjustment of this
        determination moves to `REVERSED` with `reversed_at` stamped; refund
        adjustments are left `POSTED`. Second, each affected account recomputes
        its `adjusted_balance_cents`, and any account that had been `RESOLVED`
        but now shows `amount_outstanding_cents` greater than zero transitions
        back to `NOTICE_PERIOD`."

        Design: Difficulty/compensating_invariant/writeoff_reverse_pair_conserves_account_balance
        """
        ctx = self._conserve_setup()
        reverse_determination(
            ctx["determination"]["id"], headers=COMPLIANCE, reason="post-payment audit"
        )
        account = get_account(ctx["accounts"][0]["id"])
        assert account["amount_outstanding_cents"] == 1000000
        adjustments = list_determination_adjustments(ctx["determination"]["id"])
        write_off = [a for a in adjustments if a["id"] == ctx["adjustment"]["id"]][0]
        assert write_off["status"] == "REVERSED"


class TestReportAmendmentCycle:
    def _filed_report_with_writeoff(self):
        """One FINAL determination (2026) with one POSTED WRITE_OFF 500000;
        report 2026 created (totals computed) and FILED."""
        ctx = _approved_with_writeoff(
            patient_name="Reporter Rita", mrn="MRN-REP-1", ssn_last4="9999",
        )
        report = create_report(2026)
        assert report["status"] == "OPEN"
        file_report(report["id"])
        return ctx, report["id"]

    def test_report_file_reopen_refile_cycle(self, api):
        """PRD §3.12: "Filing by a `ComplianceOfficer` requires the report to
        be `OPEN` or `REOPENED` (`ERR_REPORT_NOT_FILEABLE`, HTTP 409) and
        requires `totals_stale` to be false (`ERR_REPORT_TOTALS_STALE`,
        HTTP 409); a successful file stamps `filed_at` from the logical clock.
        A `FILED` report may be reopened explicitly by a `ComplianceOfficer`
        (reopening anything else is `ERR_REPORT_NOT_FILED`, HTTP 409), and is
        also reopened automatically when a determination reversal touches its
        reporting year per §3.8 — either path sets `totals_stale` true,
        blocking refiling. Recompute is the only way to clear the flag: it
        re-runs the full aggregation from the `POSTED` adjustment ledger and
        sets `totals_stale` false, after which the report may be filed again.
        The amendment cycle is `OPEN → FILED → REOPENED → FILED`."

        Design: Difficulty/non_linear_state_machine/community_benefit_report_file_reopen_refile_cycle
        """
        _ctx, report_id = self._filed_report_with_writeoff()
        reopened = reopen_report(report_id)
        assert reopened["status"] == "REOPENED"
        assert reopened["totals_stale"] is True
        recomputed = recompute_report(report_id)
        assert recomputed["totals_stale"] is False
        refiled = file_report(report_id)
        assert refiled["status"] == "FILED", "the amendment cycle closes back at FILED"

    def test_report_totals_survive_amendment_cycle(self, api):
        """PRD §3.12: "Creation computes the initial totals immediately and
        leaves the report `OPEN` with `totals_stale` false."
        PRD §3.12: "Recompute is the only way to clear the flag: it re-runs the
        full aggregation from the `POSTED` adjustment ledger and sets
        `totals_stale` false, after which the report may be filed again."

        Design: Difficulty/non_linear_state_machine/community_benefit_report_file_reopen_refile_cycle
        """
        _ctx, report_id = self._filed_report_with_writeoff()
        reopen_report(report_id)
        recompute_report(report_id)
        report = file_report(report_id)
        assert_community_benefit_report(report)
        assert report["total_write_offs_cents"] == 500000, (
            "no ledger mutation across the cycle — totals are conserved"
        )
        assert report["totals_stale"] is False
        assert report["accounts_assisted_count"] == 1


class TestReportReversalRecomputeCycle:
    def _two_determination_filed_report(self):
        """Two patients, each with a FINAL 2026 determination and a posted
        write-off: A 500000 (TIER_FULL), B 750000 (75.00%). Report 2026 FILED
        with total 1250000."""
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx_a = build_verified_application(
            patient_name="Ledger Lara", mrn="MRN-LED-A", ssn_last4="1818",
            date_of_birth="1987-08-08", reported_income=2000000,
            accounts=((500000, 0),), tax_return_amount=2000000,
            members=(("SELF", 38),),
        )
        det_a = finalize_determination(
            create_determination(
                ctx_a["application"]["id"], "VERIFIED_APPLICATION",
                [ctx_a["accounts"][0]["id"]],
            )["id"]
        )
        post_adjustment(ctx_a["accounts"][0]["id"], det_a["id"])
        ctx_b = build_verified_application(
            patient_name="Ledger Leo", mrn="MRN-LED-B", ssn_last4="1919",
            date_of_birth="1987-09-09", reported_income=3750000,
            accounts=((1000000, 0),), tax_return_amount=3750000,
            members=(("SELF", 38),),
        )
        det_b = finalize_determination(
            create_determination(
                ctx_b["application"]["id"], "VERIFIED_APPLICATION",
                [ctx_b["accounts"][0]["id"]],
            )["id"]
        )
        post_adjustment(ctx_b["accounts"][0]["id"], det_b["id"])
        report = create_report(2026)
        assert report["total_write_offs_cents"] == 1250000, (
            "setup sanity: 500000 + 750000"
        )
        file_report(report["id"])
        return det_b, report["id"]

    def test_reversal_reopens_filed_report(self, api):
        """PRD §3.8: "Third, if a community benefit report in `FILED` status
        exists whose `reporting_year` contains this determination's
        `finalized_at`, that report moves to `REOPENED` with `totals_stale` set
        true."

        Design: Difficulty/compensating_invariant/report_reversal_recompute_cycle_conserves_filed_totals
        """
        det_b, report_id = self._two_determination_filed_report()
        reverse_determination(det_b["id"], headers=COMPLIANCE, reason="audit clawback")
        report = get_report(report_id)
        assert report["status"] == "REOPENED"
        assert report["totals_stale"] is True
        resp = api.file_report(report_id, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REPORT_TOTALS_STALE)

    def test_refile_after_recompute_restores_ledger_equality(self, api):
        """PRD §3.12: "The aggregation sweeps `POSTED` adjustments only —
        `REVERSED` rows are excluded — whose determination's `finalized_at`
        falls in the half-open year window from January 1 of the reporting year
        up to (but excluding) January 1 of the following year; `finalized_at`
        is thus the membership key for the reporting year."
        PRD §3.12: "Recompute is the only way to clear the flag: it re-runs the
        full aggregation from the `POSTED` adjustment ledger and sets
        `totals_stale` false, after which the report may be filed again."

        Design: Difficulty/compensating_invariant/report_reversal_recompute_cycle_conserves_filed_totals
        """
        det_b, report_id = self._two_determination_filed_report()
        reverse_determination(det_b["id"], headers=COMPLIANCE, reason="audit clawback")
        recompute_report(report_id)
        report = file_report(report_id)
        assert report["status"] == "FILED"
        assert report["total_write_offs_cents"] == 500000, (
            "exactly the POSTED ledger sum after the reversal — the "
            "reverse+recompute pair restores report/ledger reconciliation"
        )
        assert report["accounts_assisted_count"] == 1


class TestReportGuardsAndAggregation:
    def test_report_year_window_and_basis_split(self, api):
        """PRD §3.12: "The aggregation sweeps `POSTED` adjustments only —
        `REVERSED` rows are excluded — whose determination's `finalized_at`
        falls in the half-open year window from January 1 of the reporting year
        up to (but excluding) January 1 of the following year; `finalized_at`
        is thus the membership key for the reporting year. Within that sweep,
        `total_write_offs_cents` sums `amount_cents` over `WRITE_OFF` rows,
        `total_standard_write_offs_cents` restricts the same sum to
        determinations with `basis` `VERIFIED_APPLICATION`,
        `total_presumptive_write_offs_cents` restricts it to `basis`
        `PRESUMPTIVE_SCORE`, `total_refunds_cents` sums `amount_cents` over
        `REFUND` rows, and `accounts_assisted_count` counts the distinct
        account ids having at least one `POSTED` write-off in the window."

        Design: Corner/calculations/report_aggregation_excludes_reversed_and_other_years
        """
        _approved_with_writeoff(
            patient_name="Sweep Sue", mrn="MRN-SWP-1", ssn_last4="0026",
        )
        rep25 = create_report(2025)
        assert rep25["total_write_offs_cents"] == 0, (
            "the determination finalized in 2026 is outside [2025-01-01, 2026-01-01)"
        )
        rep26 = create_report(2026)
        assert_community_benefit_report(rep26)
        assert rep26["total_write_offs_cents"] == 500000
        assert rep26["total_standard_write_offs_cents"] == 500000
        assert rep26["total_presumptive_write_offs_cents"] == 0
        assert rep26["accounts_assisted_count"] == 1
        assert rep26["totals_stale"] is False

    def test_report_year_duplicate_rejected(self, api):
        """PRD §3.12: "A `ComplianceOfficer` opens a community benefit report
        for a calendar `reporting_year`, unique across all reports
        (`ERR_REPORT_YEAR_DUPLICATE`, HTTP 409)."

        Design: Corner/validations/report_year_duplicate_rejected
        """
        create_report(2026)
        resp = api.create_report({"reporting_year": 2026}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REPORT_YEAR_DUPLICATE)

    def test_file_with_stale_totals_rejected(self, api):
        """PRD §3.12: "Filing by a `ComplianceOfficer` requires the report to
        be `OPEN` or `REOPENED` (`ERR_REPORT_NOT_FILEABLE`, HTTP 409) and
        requires `totals_stale` to be false (`ERR_REPORT_TOTALS_STALE`,
        HTTP 409); a successful file stamps `filed_at` from the logical clock."

        Design: Corner/validations/report_file_with_stale_totals_rejected
        """
        report = create_report(2026)
        file_report(report["id"])
        reopen_report(report["id"])
        resp = api.file_report(report["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REPORT_TOTALS_STALE)
