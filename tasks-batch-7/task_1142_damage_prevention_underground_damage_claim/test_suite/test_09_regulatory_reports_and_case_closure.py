"""Regulatory filings, late-filing penalties, amendment chains, and case closure
(PRD §3.3, §3.9)."""
from test_helpers import (
    ApiErrorId,
    add_evidence,
    assert_regulatory_report,
    create_case,
    create_excavator,
    create_incident_report,
    create_regulatory_report_payload,
    file_report,
    get_case,
    get_success_data,
    make_adjuster_headers,
    make_intake_headers,
    make_manager_headers,
    record_payment,
    set_clock,
    setup_issued_invoice_case,
    setup_paid_case,
    validate_error,
    validate_success,
)

MANAGER = make_manager_headers("mgr-1")
ADJUSTER = make_adjuster_headers("adj-1")


class TestFilingDeadline:
    def test_filing_exactly_at_deadline_is_on_time(self, api):
        """PRD §3.9: "The deadline is thirty days after the case's `occurred_at` for an
        `INCIDENT` report, or thirty days after the report's `period_end` for a
        `QUARTERLY_SUMMARY`; the boundary is inclusive, so filing exactly on the deadline
        is on time. Filing on or before the deadline yields `days_late` 0 and
        `penalty_cents` 0."

        Design: Difficulty/boundary_precision_check/filing_deadline_inclusive_boundary_on_time
        """
        set_clock("2026-03-31T00:00:00Z")
        excavator = create_excavator()
        case = create_case(excavator["id"], "50 Lake Rd", "GAS", "MINOR",
                           "2026-03-01T00:00:00Z")
        report = create_incident_report(case["id"], payload_notes="initial")
        resp = api.file_regulatory_report(report["id"], ADJUSTER)
        filed = validate_success(resp)
        assert_regulatory_report(filed)
        assert filed["status"] == "FILED"
        # occurred 2026-03-01T00:00:00Z + 30 days == 2026-03-31T00:00:00Z == clock
        assert filed["filed_at"].startswith("2026-03-31T00:00:00")
        assert filed["days_late"] == 0
        assert filed["penalty_cents"] == 0

    def test_filing_one_day_past_deadline_incurs_one_day_penalty(self, api):
        """PRD §3.9: "Filing past the deadline yields `days_late` equal to the whole days
        between deadline and `filed_at` (at least 1), and a penalty equal to 5000 cents
        plus 500 cents per day late, capped at 100000 cents." One day past:
        5000 + 500*1 = 5500.

        Design: Difficulty/boundary_precision_check/filing_deadline_inclusive_boundary_on_time
        """
        set_clock("2026-04-01T00:00:00Z")
        excavator = create_excavator()
        case = create_case(excavator["id"], "50 Lake Rd", "GAS", "MINOR",
                           "2026-03-01T00:00:00Z")
        report = create_incident_report(case["id"], payload_notes="one day late")
        filed = validate_success(api.file_regulatory_report(report["id"], ADJUSTER))
        assert filed["days_late"] == 1
        assert filed["penalty_cents"] == 5500

    def test_late_filing_penalty_ten_days_late(self, api):
        """PRD §3.9: "Filing past the deadline yields `days_late` equal to the whole days
        between deadline and `filed_at` (at least 1), and a penalty equal to 5000 cents
        plus 500 cents per day late, capped at 100000 cents." Ten days past:
        5000 + 500*10 = 10000.

        Design: Corner/calculations/late_filing_penalty_ten_days_late
        """
        set_clock("2026-04-10T00:00:00Z")
        excavator = create_excavator()
        case = create_case(excavator["id"], "12 Twelfth St", "GAS", "MINOR",
                           "2026-03-01T00:00:00Z")
        report = create_incident_report(case["id"], payload_notes="late")
        filed = validate_success(api.file_regulatory_report(report["id"], ADJUSTER))
        assert filed["status"] == "FILED"
        assert filed["days_late"] == 10
        assert filed["penalty_cents"] == 10000


class TestQuarterlyPeriods:
    def test_shared_boundary_day_conflicts(self, api):
        """PRD §3.9: "Two non-`SUPERSEDED` `QUARTERLY_SUMMARY` reports whose periods
        overlap — including sharing a boundary day — conflict, and the new report is
        rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)." Quarterly periods are
        closed, inclusive intervals, so [03-31, 06-30] shares 03-31 with [01-01, 03-31].

        Design: Difficulty/resource_temporal_overlap/quarterly_report_periods_closed_interval_boundary_conflict
        """
        resp_q1 = api.create_regulatory_report(
            create_regulatory_report_payload(
                report_type="QUARTERLY_SUMMARY", period_start="2026-01-01T00:00:00Z",
                period_end="2026-03-31T00:00:00Z", payload_notes="Q1",
            ),
            ADJUSTER,
        )
        validate_success(resp_q1, expected_status=201)
        resp_overlap = api.create_regulatory_report(
            create_regulatory_report_payload(
                report_type="QUARTERLY_SUMMARY", period_start="2026-03-31T00:00:00Z",
                period_end="2026-06-30T00:00:00Z", payload_notes="overlap",
            ),
            ADJUSTER,
        )
        validate_error(resp_overlap, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP, expected_status=409)

    def test_next_day_period_accepted(self, api):
        """PRD §3.9: "a `QUARTERLY_SUMMARY` report requires `damage_case_id` to be null
        and instead carries `period_start` and `period_end` describing a closed,
        inclusive interval." A period starting the day after the existing period's last
        day shares no day with it, so it is accepted in `DRAFT`.

        Design: Difficulty/resource_temporal_overlap/quarterly_report_periods_closed_interval_boundary_conflict
        """
        resp_q1 = api.create_regulatory_report(
            create_regulatory_report_payload(
                report_type="QUARTERLY_SUMMARY", period_start="2026-01-01T00:00:00Z",
                period_end="2026-03-31T00:00:00Z", payload_notes="Q1",
            ),
            ADJUSTER,
        )
        validate_success(resp_q1, expected_status=201)
        resp_q2 = api.create_regulatory_report(
            create_regulatory_report_payload(
                report_type="QUARTERLY_SUMMARY", period_start="2026-04-01T00:00:00Z",
                period_end="2026-06-30T00:00:00Z", payload_notes="Q2",
            ),
            ADJUSTER,
        )
        report_q2 = validate_success(resp_q2, expected_status=201)
        assert report_q2["status"] == "DRAFT"


class TestAmendChain:
    def test_amend_draft_rejected_then_amend_filed_supersedes(self, api):
        """PRD §3.9: "Amending a report that is not `FILED` — still `DRAFT` or already
        `SUPERSEDED` — is rejected with `ERR_AMEND_CHAIN_BROKEN` (HTTP 409)." and
        "Amending creates a successor `RegulatoryReport` in `DRAFT` whose
        `amends_report_id` is the original report's id and whose `report_type`,
        `damage_case_id`, and period fields are copied from the original; the original
        moves to `SUPERSEDED`."

        Design: Corner/errors/amend_draft_rejected_then_amend_filed_supersedes
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "35 Upsilon St", "GAS", "MINOR",
                           "2026-05-01T09:00:00Z")
        report = create_incident_report(case["id"], payload_notes="v1")
        resp_early = api.amend_regulatory_report(report["id"], {"payload_notes": "too early"},
                                                 ADJUSTER)
        validate_error(resp_early, ApiErrorId.ERR_AMEND_CHAIN_BROKEN, expected_status=409)

        file_report(report["id"])
        resp_amend = api.amend_regulatory_report(report["id"], {"payload_notes": "v2"},
                                                 ADJUSTER)
        successor = validate_success(resp_amend)
        assert successor["status"] == "DRAFT"
        assert successor["amends_report_id"] == report["id"]
        original = get_success_data(api.get_regulatory_report(report["id"], MANAGER))
        assert original["status"] == "SUPERSEDED"


class TestCaseClosure:
    def test_close_gate_error_then_success(self, api):
        """PRD §3.9: "A `RecoveryManager` closes a case when three conditions all hold:
        the case's `investigation_status` is `FAULT_FINAL`; its `recovery_status` is
        `RECOVERED`; and no `INCIDENT` `RegulatoryReport` for the case is still in
        `DRAFT`. When any condition fails, the close is rejected with
        `ERR_CASE_NOT_CLOSABLE` (HTTP 409)."

        Design: Corner/errors/close_gate_error_then_success
        """
        ctx = setup_issued_invoice_case(dig_site_address="41 Beth St")
        case = ctx["case"]
        invoice = ctx["invoice"]
        # Gate unmet: recovery still INVOICED (invoice unpaid).
        resp_early = api.close_case(case["id"], MANAGER)
        validate_error(resp_early, ApiErrorId.ERR_CASE_NOT_CLOSABLE, expected_status=409)
        # Pay in full -> invoice PAID -> case RECOVERED; file the incident report so no
        # INCIDENT report remains in DRAFT.
        record_payment("EXCAVATOR", ctx["excavator"]["id"], 120000,
                       claim_invoice_id=invoice["id"])
        report = create_incident_report(case["id"], payload_notes="filing")
        file_report(report["id"])
        resp_close = api.close_case(case["id"], MANAGER)
        closed = validate_success(resp_close)
        assert closed["investigation_status"] == "CLOSED"

    def test_closed_case_rejects_new_evidence(self, api):
        """PRD §3.3: "Adding evidence to a case that is already `CLOSED` is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/closed_case_rejects_new_evidence
        """
        ctx = setup_paid_case(dig_site_address="7 Seventh St")
        case = ctx["case"]
        report = create_incident_report(case["id"], payload_notes="filing")
        file_report(report["id"])
        closed = validate_success(api.close_case(case["id"], MANAGER))
        assert closed["investigation_status"] == "CLOSED"
        resp = api.create_evidence_item(
            {
                "damage_case_id": case["id"], "evidence_type": "PHOTO",
                "captured_at": "2026-05-02T11:00:00Z", "description": "late",
            },
            make_intake_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        case_after = get_case(case["id"])
        assert case_after["evidence_count"] == 1
