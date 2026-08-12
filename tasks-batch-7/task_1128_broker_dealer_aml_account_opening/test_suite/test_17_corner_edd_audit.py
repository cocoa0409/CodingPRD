"""Corner queue: EDD review scheduling and audit engagement/finding discipline."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    begin_edd_review,
    begin_fieldwork,
    complete_edd_review,
    create_edd_review,
    create_engagement,
    create_finding,
    get_account,
    run_daily_sweep,
    set_clock,
    setup_engagement_with_finding,
    setup_pending_account,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    make_auditor_headers,
    make_officer_headers,
)


class TestEddInvalidDateRangeRejected:
    def test_empty_period_rejected(self, api):
        """PRD §3.4: "The period is half-open: it includes its start date and excludes
        its end date, `period_end` must be later than `period_start`
        (`ERR_INVALID_DATE_RANGE` otherwise)".
        period_start == period_end describes an empty interval and is rejected (400).

        Design: Corner/validations/edd_invalid_date_range_rejected
        """
        ctx = setup_pending_account(verify_doc=False)
        resp = api_client.create_edd_review(
            ctx["account"]["id"],
            {
                "period_start": "2026-05-01",
                "period_end": "2026-05-01",
                "trigger_reason": "empty",
            },
            TEST_USERS["analyst_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
        assert error["error_id"] == "ERR_INVALID_DATE_RANGE"
        assert resp.status_code == 400


class TestEddRefreshScheduleMediumTier:
    def test_medium_review_due_in_24_months_and_strict_overdue(self, api):
        """PRD §3.4: "A completion with decision `APPROVED` captures
        `tier_at_completion` from the account's current `risk_tier` — immutable
        thereafter — and schedules `refresh_due_date` as the completion date plus an
        interval fixed by that captured tier: twelve calendar months for `HIGH`,
        twenty-four for `MEDIUM`, thirty-six for `LOW`, preserving the day of month."
        PRD §3.4: "When the daily sweep later finds an `APPROVED` review whose
        `refresh_due_date` is strictly earlier than the clock date, the review flips to
        `REFRESH_DUE` — a date equal to the clock date is not yet due — and posture
        recomputes again, since a `REFRESH_DUE` review is itself an elevation trigger."
        MEDIUM tier completed 2026-05-01 -> due 2028-05-01; the sweep on the due date
        does not flip, the next day flips and elevates posture.

        Design: Corner/calculations/edd_refresh_schedule_medium_tier
        """
        ctx = setup_pending_account(
            country_risk_tier="HIGH",
            product_set=["LOW_PRICED_SECURITIES"],
            verify_doc=False,
            full_name="C5",
            tax_id="TIN-C05",
        )
        account = ctx["account"]
        assert account["risk_tier"] == "MEDIUM", (
            f"HIGH country (25) + LPS (15) = 40 -> MEDIUM, got {account['risk_tier']}"
        )
        review = create_edd_review(
            account["id"], period_start="2026-04-01", period_end="2026-05-01",
            trigger_reason="onboarding",
        )
        begin_edd_review(review["id"])
        completed = complete_edd_review(review["id"], "APPROVED")
        assert completed["tier_at_completion"] == "MEDIUM"
        assert completed["refresh_due_date"] == "2028-05-01", (
            f"MEDIUM interval is 24 months, got {completed['refresh_due_date']}"
        )

        set_clock("2028-05-01T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["edd_reviews_flagged"] == 0, (
            "a refresh_due_date equal to the clock date is not yet due"
        )

        set_clock("2028-05-02T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["edd_reviews_flagged"] == 1
        resp = api_client.get_edd_review(review["id"], TEST_USERS["analyst_headers"])
        assert validate_success(resp)["status"] == "REFRESH_DUE"
        assert get_account(account["id"])["aml_posture"] == "ELEVATED"


class TestEngagementCloseWithOpenFindingsRejected:
    def test_open_finding_blocks_close_then_terminal_finding_allows(self, api):
        """PRD §3.9: "An engagement closes from `REPORTED` once every one of its
        findings has reached `REMEDIATED` or `ACCEPTED_RISK`; open findings block the
        close with `ERR_ENGAGEMENT_HAS_OPEN_FINDINGS`."

        Design: Corner/state_machines/engagement_close_with_open_findings_rejected
        """
        ctx = setup_engagement_with_finding(
            severity="LOW",
            engagement_state="REPORTED",
            scope_unit="CIP_PROCESS",
            start_date="2026-03-01",
            end_date="2026-04-01",
            description="minor filing gap",
        )
        engagement_id = ctx["engagement"]["id"]

        resp = api_client.close_engagement(engagement_id, TEST_USERS["auditor_headers"])
        error = validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_HAS_OPEN_FINDINGS)
        assert error["error_id"] == "ERR_ENGAGEMENT_HAS_OPEN_FINDINGS"

        resp = api_client.accept_risk(
            ctx["finding"]["id"],
            {"rationale": "cost of fix exceeds risk"},
            TEST_USERS["auditor_headers"],
        )
        validate_success(resp)
        resp = api_client.close_engagement(engagement_id, TEST_USERS["auditor_headers"])
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"


class TestFindingAcceptRiskHighSeverityRejected:
    def test_high_severity_risk_acceptance_rejected(self, api):
        """PRD §3.9: "an auditor may accept the risk of an `OPEN` finding outright,
        moving it to the terminal `ACCEPTED_RISK` with a `rationale` — but only for
        `LOW` or `MEDIUM` severity findings; `HIGH` and `CRITICAL` findings must be
        remediated, and the attempt yields `ERR_RISK_ACCEPTANCE_NOT_ALLOWED`."

        Design: Corner/state_machines/finding_accept_risk_high_severity_rejected
        """
        ctx = setup_engagement_with_finding(
            severity="HIGH",
            scope_unit="TRANSACTION_MONITORING",
            start_date="2026-03-01",
            end_date="2026-04-01",
            description="rule gap",
        )
        resp = api_client.accept_risk(
            ctx["finding"]["id"], {"rationale": "try"}, TEST_USERS["auditor_headers"]
        )
        error = validate_error(resp, ApiErrorId.ERR_RISK_ACCEPTANCE_NOT_ALLOWED)
        assert error["error_id"] == "ERR_RISK_ACCEPTANCE_NOT_ALLOWED"
        assert resp.status_code == 409


class TestFindingAgingBoundaryAndSeverityEscalation:
    def test_deadline_day_not_overdue_next_day_aged_and_escalated(self, api):
        """PRD §3.9: "A finding's `remediation_deadline` is fixed at issuance from its
        initial severity: thirty days for `CRITICAL`, sixty for `HIGH`, ninety for
        `MEDIUM`, one hundred eighty for `LOW`, counted in calendar days from the
        created date, and the deadline never moves afterwards. The daily sweep ages
        findings: an `OPEN` or `REMEDIATION_SUBMITTED` finding whose deadline is
        strictly earlier than the clock date has `is_overdue` set true and its severity
        escalated one level — `LOW` to `MEDIUM`, `MEDIUM` to `HIGH`, `HIGH` to
        `CRITICAL`, with `CRITICAL` unchanged — while a deadline equal to the clock
        date is not yet overdue."
        MEDIUM created 2026-05-01 -> deadline 2026-07-30; swept on 2026-07-30 nothing
        ages; swept on 2026-07-31 the finding is overdue and escalates to HIGH.

        Design: Corner/calculations/finding_aging_boundary_and_severity_escalation
        """
        ctx = setup_engagement_with_finding(
            severity="MEDIUM",
            scope_unit="AML_PROGRAM",
            start_date="2026-04-01",
            end_date="2026-06-01",
            description="CIP sampling gap",
        )
        finding = ctx["finding"]
        assert finding["remediation_deadline"] == "2026-07-30", (
            f"MEDIUM + 90 days from 2026-05-01, got {finding['remediation_deadline']}"
        )

        set_clock("2026-07-30T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["findings_aged"] == 0, "deadline day is not yet overdue"

        set_clock("2026-07-31T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["findings_aged"] == 1

        resp = api_client.get_finding(finding["id"], TEST_USERS["auditor_headers"])
        aged = validate_success(resp)
        assert aged["is_overdue"] is True
        assert aged["severity"] == "HIGH", (
            f"MEDIUM escalates one level to HIGH, got {aged['severity']}"
        )


class TestFindingVerifySodSameIdentityRejected:
    def test_verifier_identity_equal_to_submitter_rejected(self, api):
        """PRD §2.10: "The auditor who verifies a finding's remediation must not be
        the officer who submitted it: verification compares `X-User-ID` to the
        finding's `submitted_by`, and equality is likewise rejected with
        `ERR_SOD_VIOLATION`."
        PRD §3.9: "`CONFIRM` moves `REMEDIATION_SUBMITTED` → `REMEDIATED`" when a
        distinct auditor verifies.

        Design: Corner/rbac/finding_verify_sod_same_identity_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        engagement = create_engagement(
            auditor_id="auditor-1", scope_unit="CIP_PROCESS",
            start_date="2026-04-01", end_date="2026-06-01",
        )
        begin_fieldwork(engagement["id"], auditor_id="auditor-1")
        finding = create_finding(
            engagement["id"], auditor_id="auditor-1", severity="MEDIUM",
            description="doc retention gap",
        )
        resp = api_client.submit_remediation(
            finding["id"], {"remediation_note": "fixed retention"},
            make_officer_headers("officer-77"),
        )
        validate_success(resp)

        resp = api_client.verify_remediation(
            finding["id"], {"decision": "CONFIRM"}, make_auditor_headers("officer-77")
        )
        error = validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert error["error_id"] == "ERR_SOD_VIOLATION"
        assert resp.status_code == 403

        resp = api_client.verify_remediation(
            finding["id"], {"decision": "CONFIRM"}, make_auditor_headers("auditor-9")
        )
        verified = validate_success(resp)
        assert verified["status"] == "REMEDIATED"
