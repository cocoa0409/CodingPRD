"""Reporting period and call report workflows: amendment cycle, late filing,
edit gates, terminal-state lockdowns, and orderly close."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    advance_clock_past,
    create_bank,
    create_period,
    add_exposure,
    add_instrument,
    create_prepared_call_report,
    setup_accepted_report,
    set_clock,
    make_capital_analyst_headers,
    PREPARER_USER_ID,
    SUBMITTER_USER_ID,
)


class TestReportingPeriodLifecycle(object):
    def test_reporting_period_initial_state_open(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.2: "The period opens in OPEN status."

        Design: Corner/state_machines/reporting_period_initial_state_open
        """
        bank = create_bank("CH-INI-001", legal_name="InitBank")
        # Future-dated quarter so the default clock (2026-08-01) has not yet
        # passed the period end.
        period = create_period(bank["id"], "2026-09-30", 2026, "Q3")
        assert period["status"] == "OPEN"

    def test_period_filing_due_after_period_end_and_late_filing_flag(
        self, api, system_operator_headers, capital_analyst_headers, regulator_reviewer_headers
    ):
        """PRD §3.2: "Once the logical clock passes period_end_date, the
        period moves OPEN → FILING_DUE" and "The period's late_filing flag is
        set to true exactly when the first successful submission of the
        period's call report occurs strictly after filing_due_at."
        PRD §3.2: "filing_due_at falls 35 days after the period end for
        first-, second-, and third-quarter periods and 40 days after for
        fourth-quarter periods, in both cases at exactly 17:00:00 UTC."

        Design: Corner/state_machines/reporting_period_initial_state_open
        """
        bank = create_bank("CH-INI-002", legal_name="InitBank2")
        # Q3 2026: period end 2026-09-30, after the default clock 2026-08-01.
        period = create_period(bank["id"], "2026-09-30", 2026, "Q3")
        # Q3: 2026-09-30 + 35 days = 2026-11-04 at 17:00:00Z.
        assert period["filing_due_at"] == "2026-11-04T17:00:00Z", (
            f"filing_due_at: expected 2026-11-04T17:00:00Z, got {period['filing_due_at']}"
        )
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=100_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000)
        report = create_prepared_call_report(bank["id"], period["id"])
        assert report["status"] == "VALIDATED"
        # Advance past period end but before the deadline (clock only moves forward).
        set_clock("2026-10-01T00:00:00Z")
        period_now = validate_success(
            api.get_reporting_period(bank["id"], period["id"], capital_analyst_headers)
        )
        assert period_now["status"] == "FILING_DUE"
        # Advance strictly past the filing deadline, then submit -> late.
        set_clock("2026-11-04T17:00:01Z")
        submitted = validate_success(
            api.submit_call_report(
                bank["id"], period["id"], report["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        assert submitted["status"] == "SUBMITTED"
        period_after = validate_success(
            api.get_reporting_period(bank["id"], period["id"], capital_analyst_headers)
        )
        assert period_after["late_filing"] is True

    def test_call_report_invalid_submit_from_draft(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.3: "A successful submission moves the report VALIDATED →
        SUBMITTED"

        Design: Corner/state_machines/call_report_invalid_submit_from_draft
        """
        bank = create_bank("CH-ITR-001", legal_name="InvTrBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=100_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000)
        report = get_success_data(api.create_call_report(bank["id"], period["id"], {}, capital_analyst_headers))
        assert report["status"] == "DRAFT"
        # Move the period unambiguously to FILING_DUE so only the report's
        # DRAFT state can reject the submission.
        advance_clock_past("2026-06-30")
        res = api.submit_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_call_report_double_prepare_rejected(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.3: "Preparation also records the preparing analyst's
        identity on the report as its prepared_by_user_id, and the report
        moves from DRAFT to PREPARED"

        Design: Corner/state_machines/call_report_double_prepare_idempotent_or_rejected
        """
        bank = create_bank("CH-IDM-001", legal_name="IdemBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=100_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000)
        report = create_prepared_call_report(bank["id"], period["id"])
        assert report["status"] == "VALIDATED"
        res = api.prepare_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestAmendmentCycle(object):
    def test_amendment_open_creates_incremented_draft(self, api, system_operator_headers,
                                                      capital_analyst_headers, regulator_reviewer_headers):
        """PRD §3.4: "Opening an amendment moves the period ACCEPTED →
        AMENDMENT_OPEN, spins up a fresh report in DRAFT whose
        amendment_sequence increments the prior report's and whose
        supersedes_call_report_id references it, and moves the prior report to
        AMENDED_SUPERSEDED."

        Design: Difficulty/non_linear_state_machine/reporting_period_amendment_cycle
        """
        bank, period, report = setup_accepted_report(
            "CH-CYC-001", cet1_cents=10_000_000_000, rwa_cents=100_000_000_000
        )
        amend = validate_success(
            api.open_amendment(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        assert amend["amendment_sequence"] == 1
        assert amend["supersedes_call_report_id"] == report["id"]
        assert amend["status"] == "DRAFT"
        prior = validate_success(
            api.get_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        assert prior["status"] == "AMENDED_SUPERSEDED"
        period_now = validate_success(
            api.get_reporting_period(bank["id"], period["id"], capital_analyst_headers)
        )
        assert period_now["status"] == "AMENDMENT_OPEN"

    def test_amendment_full_cycle_reaches_re_accepted(self, api, system_operator_headers,
                                                      capital_analyst_headers, regulator_reviewer_headers):
        """PRD §3.4: "When the newest report for the period is VALIDATED with
        edit_failures_open_count at zero, an analyst submits it and the period
        moves AMENDMENT_OPEN → RE_SUBMITTED with the newest report's
        submitted_at stamped. A RegulatorReviewer then accepts the amendment
        while the newest report is SUBMITTED, moving the period to
        RE_ACCEPTED."

        Design: Difficulty/non_linear_state_machine/reporting_period_amendment_cycle
        """
        bank, period, report = setup_accepted_report(
            "CH-CYC-002", cet1_cents=10_000_000_000, rwa_cents=100_000_000_000
        )
        amend = validate_success(
            api.open_amendment(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        prepared = validate_success(
            api.prepare_call_report(
                bank["id"], period["id"], amend["id"],
                make_capital_analyst_headers(PREPARER_USER_ID),
            )
        )
        assert prepared["status"] == "VALIDATED"
        submitted = validate_success(
            api.submit_call_report(
                bank["id"], period["id"], amend["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        assert submitted["status"] == "SUBMITTED"
        period_mid = validate_success(
            api.get_reporting_period(bank["id"], period["id"], capital_analyst_headers)
        )
        assert period_mid["status"] == "RE_SUBMITTED"
        accepted = validate_success(
            api.accept_call_report(bank["id"], period["id"], amend["id"], regulator_reviewer_headers)
        )
        assert accepted["status"] == "ACCEPTED"
        period_final = validate_success(
            api.get_reporting_period(bank["id"], period["id"], capital_analyst_headers)
        )
        assert period_final["status"] == "RE_ACCEPTED"


class TestEditExceptionRules(object):
    def _setup_fatal_edit_report(self, api, capital_analyst_headers, charter_id):
        """ADVANCED bank whose collateral haircut makes rwa_advanced fall
        below rwa_standardized -> EDIT_FLOOR_VIOLATION (FATAL) at prepare."""
        bank = create_bank(charter_id, methodology="ADVANCED")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=100_000_000_000,
            risk_weight_bps=10000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=5000,
        )
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000_000)
        report = create_prepared_call_report(bank["id"], period["id"])
        assert report["status"] == "EDITS_OUTSTANDING", (
            f"Setup: expected EDITS_OUTSTANDING, got {report['status']}"
        )
        # Move the period unambiguously to FILING_DUE so submission takes the
        # FILING_DUE -> SUBMITTED path.
        advance_clock_past("2026-06-30")
        assert report["edit_failures_open_count"] > 0
        edits, _meta = validate_paginated(
            api.list_edit_exceptions(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        fatal = [e for e in edits if e["severity"] == "FATAL"]
        assert len(fatal) >= 1, "Setup: expected at least one FATAL edit"
        return bank, period, report, fatal[0]

    def test_edit_exception_fatal_cannot_be_explained(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.3: "a FATAL edit must be resolved — attempting to explain
        one is rejected as an illegal transition with
        ERR_INVALID_STATE_TRANSITION (HTTP 409)."

        Design: Corner/state_machines/edit_exception_fatal_cannot_be_explained
        """
        bank, period, report, fatal_edit = self._setup_fatal_edit_report(
            api, capital_analyst_headers, "CH-FAT-001"
        )
        res = api.explain_edit_exception(
            bank["id"], period["id"], report["id"], fatal_edit["id"],
            {"resolution_note": "Trying to explain a FATAL edit"},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_edit_exception_resolve_requires_note(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.3: "on resolution the note is mandatory whenever the
        severity is FATAL or QUALITY and optional for INFORMATIONAL ... and a
        missing note where one is required is rejected with
        ERR_EDIT_NOTE_REQUIRED (HTTP 422)."

        Design: Corner/state_machines/edit_exception_resolve_requires_note
        """
        bank, period, report, fatal_edit = self._setup_fatal_edit_report(
            api, capital_analyst_headers, "CH-NOT-001"
        )
        res = api.resolve_edit_exception(
            bank["id"], period["id"], report["id"], fatal_edit["id"],
            {"resolution_note": ""},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_EDIT_NOTE_REQUIRED)

    def test_edit_failure_zero_count_unblocks_submit(self, api, system_operator_headers,
                                                     capital_analyst_headers, regulator_reviewer_headers):
        """PRD §3.3: "A report still carrying open exceptions cannot be
        submitted — the attempt is rejected with ERR_UNRESOLVED_EDITS
        (HTTP 409)" and "Either action decrements the report's
        edit_failures_open_count, and when the last open exception closes
        against a report in EDITS_OUTSTANDING, the report auto-advances to
        VALIDATED."

        Design: Difficulty/boundary_precision_check/edit_failure_zero_count_unblocks_submit
        """
        bank, period, report, fatal_edit = self._setup_fatal_edit_report(
            api, capital_analyst_headers, "CH-EDT-001"
        )
        # Blocked while open count > 0 (report is in EDITS_OUTSTANDING).
        blocked = api.submit_call_report(
            bank["id"], period["id"], report["id"],
            make_capital_analyst_headers(SUBMITTER_USER_ID),
        )
        assert blocked.status_code == 409, (
            f"Expected 409 while edits outstanding, got {blocked.status_code}"
        )
        # Resolve the FATAL edit with a note -> count drops to 0 -> VALIDATED.
        resolved = validate_success(
            api.resolve_edit_exception(
                bank["id"], period["id"], report["id"], fatal_edit["id"],
                {"resolution_note": "Collins floor applied — RWA restated at standardized"},
                capital_analyst_headers,
            )
        )
        assert resolved["status"] == "RESOLVED"
        after = validate_success(
            api.get_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        assert after["edit_failures_open_count"] == 0
        assert after["status"] == "VALIDATED"
        # The same report now submits.
        submitted = validate_success(
            api.submit_call_report(
                bank["id"], period["id"], report["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        assert submitted["status"] == "SUBMITTED"

    def test_edit_boundary_resolve_each_open_edit_until_zero(self, api, system_operator_headers,
                                                             capital_analyst_headers):
        """PRD §3.3: "Either action decrements the report's
        edit_failures_open_count, and when the last open exception closes
        against a report in EDITS_OUTSTANDING, the report auto-advances to
        VALIDATED."

        Design: Difficulty/boundary_precision_check/edit_failure_zero_count_unblocks_submit
        """
        bank, period, report, _fatal = self._setup_fatal_edit_report(
            api, capital_analyst_headers, "CH-EDT-002"
        )
        # Resolve every open edit; the report must auto-advance to VALIDATED
        # exactly when the counter reaches zero.
        edits, _meta = validate_paginated(
            api.list_edit_exceptions(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        open_edits = [e for e in edits if e["status"] == "OPEN"]
        for edit in open_edits:
            validate_success(
                api.resolve_edit_exception(
                    bank["id"], period["id"], report["id"], edit["id"],
                    {"resolution_note": "Restated and corrected"},
                    capital_analyst_headers,
                )
            )
        after = validate_success(
            api.get_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        assert after["edit_failures_open_count"] == 0
        assert after["status"] == "VALIDATED"


class TestOrderlyPeriodClose(object):
    def test_close_out_of_order_rejected_then_in_order_succeeds(self, api, system_operator_headers,
                                                                capital_analyst_headers,
                                                                regulator_reviewer_headers):
        """PRD §3.4: "A period may be closed only from ACCEPTED or
        RE_ACCEPTED, and only when every earlier-dated period of the same bank
        is already CLOSED; an out-of-order close is rejected with
        ERR_TEMPORAL_VIOLATION (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/reporting_period_close_chronological_order
        """
        bank = create_bank("CH-TP2-001", legal_name="TempBank2")
        p1 = create_period(bank["id"], "2026-03-31", 2026, "Q1")
        p2 = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], p1["id"], exposure_at_default_cents=50_000_000_000)
        add_exposure(bank["id"], p2["id"], exposure_at_default_cents=50_000_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000_000)
        # Move both periods unambiguously to FILING_DUE before submissions.
        advance_clock_past("2026-06-30")
        for period in (p1, p2):
            report = create_prepared_call_report(bank["id"], period["id"])
            validate_success(
                api.submit_call_report(
                    bank["id"], period["id"], report["id"],
                    make_capital_analyst_headers(SUBMITTER_USER_ID),
                )
            )
            validate_success(
                api.accept_call_report(bank["id"], period["id"], report["id"], regulator_reviewer_headers)
            )
        # Closing P2 while P1 is still open is out of chronological order.
        bad = api.close_reporting_period(bank["id"], p2["id"], capital_analyst_headers)
        validate_error(bad, ApiErrorId.ERR_TEMPORAL_VIOLATION)
        # Closing in order succeeds.
        closed_p1 = validate_success(api.close_reporting_period(bank["id"], p1["id"], capital_analyst_headers))
        assert closed_p1["status"] == "CLOSED"
        closed_p2 = validate_success(api.close_reporting_period(bank["id"], p2["id"], capital_analyst_headers))
        assert closed_p2["status"] == "CLOSED"

    def test_close_re_accepted_period_out_of_order_rejected(self, api, system_operator_headers,
                                                            capital_analyst_headers,
                                                            regulator_reviewer_headers):
        """PRD §3.4: "A period may be closed only from ACCEPTED or
        RE_ACCEPTED, and only when every earlier-dated period of the same bank
        is already CLOSED; an out-of-order close is rejected with
        ERR_TEMPORAL_VIOLATION (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/reporting_period_close_chronological_order
        """
        bank = create_bank("CH-TP2-003", legal_name="TempBank4")
        p1 = create_period(bank["id"], "2026-03-31", 2026, "Q1")
        p2 = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], p1["id"], exposure_at_default_cents=50_000_000_000)
        add_exposure(bank["id"], p2["id"], exposure_at_default_cents=50_000_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000_000)
        # Move both periods unambiguously to FILING_DUE before submissions.
        advance_clock_past("2026-06-30")
        # P1: file, accept, then a full amendment cycle to reach RE_ACCEPTED.
        report1 = create_prepared_call_report(bank["id"], p1["id"])
        validate_success(
            api.submit_call_report(
                bank["id"], p1["id"], report1["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        accepted1 = validate_success(
            api.accept_call_report(bank["id"], p1["id"], report1["id"], regulator_reviewer_headers)
        )
        amend = validate_success(
            api.open_amendment(bank["id"], p1["id"], accepted1["id"], capital_analyst_headers)
        )
        prepared_amend = validate_success(
            api.prepare_call_report(
                bank["id"], p1["id"], amend["id"],
                make_capital_analyst_headers(PREPARER_USER_ID),
            )
        )
        validate_success(
            api.submit_call_report(
                bank["id"], p1["id"], prepared_amend["id"],
                make_capital_analyst_headers("analyst-submitter-2"),
            )
        )
        validate_success(
            api.accept_call_report(bank["id"], p1["id"], prepared_amend["id"], regulator_reviewer_headers)
        )
        p1_now = validate_success(api.get_reporting_period(bank["id"], p1["id"], capital_analyst_headers))
        assert p1_now["status"] == "RE_ACCEPTED"
        # P2: file and accept (stays ACCEPTED).
        report2 = create_prepared_call_report(bank["id"], p2["id"])
        validate_success(
            api.submit_call_report(
                bank["id"], p2["id"], report2["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        validate_success(
            api.accept_call_report(bank["id"], p2["id"], report2["id"], regulator_reviewer_headers)
        )
        # Closing P2 while P1 (earlier, RE_ACCEPTED) is not yet CLOSED fails.
        bad = api.close_reporting_period(bank["id"], p2["id"], capital_analyst_headers)
        validate_error(bad, ApiErrorId.ERR_TEMPORAL_VIOLATION)
        # Closing in order succeeds; RE_ACCEPTED is a permitted source state.
        closed_p1 = validate_success(api.close_reporting_period(bank["id"], p1["id"], capital_analyst_headers))
        assert closed_p1["status"] == "CLOSED"
        closed_p2 = validate_success(api.close_reporting_period(bank["id"], p2["id"], capital_analyst_headers))
        assert closed_p2["status"] == "CLOSED"


class TestCloseStateVsTemporal(object):
    def test_close_dual_violation_state_error_wins(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in a fixed order, so that earlier failures mask later
        ones. ... Fifth, whether the target entity's current state permits the
        requested transition (ERR_INVALID_STATE_TRANSITION, HTTP 409). ...
        Ninth, temporal windows (ERR_TEMPORAL_VIOLATION)."
        PRD §3.4: "A period may be closed only from ACCEPTED or RE_ACCEPTED"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_period_close
        """
        bank = create_bank("CH-PRI-003", legal_name="PriBank2")
        p1 = create_period(bank["id"], "2026-03-31", 2026, "Q1")
        p2 = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        # Both the state check (P2 is OPEN, not ACCEPTED) and the temporal
        # check (P1, earlier-dated, is not CLOSED) could reject this close.
        # The state check is fifth in §2.9's fixed order, temporal is ninth.
        res = api.close_reporting_period(bank["id"], p2["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_close_state_error_when_earlier_period_accepted_but_unclosed(
        self, api, system_operator_headers, capital_analyst_headers, regulator_reviewer_headers
    ):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in a fixed order, so that earlier failures mask later
        ones. ... Fifth, whether the target entity's current state permits the
        requested transition (ERR_INVALID_STATE_TRANSITION, HTTP 409). ...
        Ninth, temporal windows (ERR_TEMPORAL_VIOLATION)."
        PRD §3.4: "A period may be closed only from ACCEPTED or RE_ACCEPTED,
        and only when every earlier-dated period of the same bank is already
        CLOSED"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_period_close
        """
        bank = create_bank("CH-PRI-004", legal_name="PriBank3")
        p1 = create_period(bank["id"], "2026-03-31", 2026, "Q1")
        p2 = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], p1["id"], exposure_at_default_cents=50_000_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000_000)
        # Move P1 unambiguously to FILING_DUE before its submission.
        advance_clock_past("2026-03-31")
        # P1 filed and accepted but never closed; P2 left unfiled.
        report1 = create_prepared_call_report(bank["id"], p1["id"])
        validate_success(
            api.submit_call_report(
                bank["id"], p1["id"], report1["id"],
                make_capital_analyst_headers(SUBMITTER_USER_ID),
            )
        )
        validate_success(
            api.accept_call_report(bank["id"], p1["id"], report1["id"], regulator_reviewer_headers)
        )
        # Close P2: wrong state (OPEN) AND out of chronological order (P1 not
        # CLOSED). State, checked fifth, masks the ninth temporal check.
        res = api.close_reporting_period(bank["id"], p2["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
