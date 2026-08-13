"""Ballast water reporting: deadlines, overdue transition, submission,
rejection loop, and terminal-state lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_report,
    assert_timestamp_equals,
    find_noncompliance,
    find_report,
    get_voyage,
    list_reports,
    set_clock,
    setup_voyage_in_progress,
    submit_report_ok,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestReportDeadlines:
    def test_report_due_at_pre_arrival_minus_24h(self, api, flag_surveyor_headers):
        """PRD section 3.4: "A `PRE_ARRIVAL` report is due 24 hours before
        `arrived_at`."
        PRD section 3.2: "instantiating a `PRE_ARRIVAL` report in `DRAFT` whose
        deadline is 24 hours before `arrived_at`."
        PRD section 3.4: "The report's own `is_overdue` flag is true exactly when its
        `status` is `DRAFT` and the current UTC is past `due_at`."

        Design: Corner/calculations/report_due_at_pre_arrival_minus_24h
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100032", vessel_name="MV Avocet", voyage_number="V9401",
            arrived_at="2026-08-10T00:00:00Z",
        )
        report = find_report(vessel["id"], voyage["id"], "PRE_ARRIVAL")
        assert_report(report)
        # arrived_at 2026-08-10T00:00:00Z minus 24 hours.
        assert_timestamp_equals(report["due_at"], "2026-08-09T00:00:00Z",
                                label="PRE_ARRIVAL due_at")
        assert report["status"] == "DRAFT"
        # Logical clock 2026-08-01T00:00:00Z is before the deadline.
        assert report["is_overdue"] is False


class TestOverdueStrictGreaterCrossing:
    def _setup_late_voyage(self):
        return setup_voyage_in_progress(
            imo_number="9000025", vessel_name="MV Yarrow", voyage_number="V9003",
            arrived_at="2026-08-10T00:00:00Z",
        )

    def test_report_not_overdue_at_exact_due_at(self, api, flag_surveyor_headers):
        """PRD section 3.4: "The report's own `is_overdue` flag is true exactly when
        its `status` is `DRAFT` and the current UTC is past `due_at`."

        Design: Difficulty/resource_temporal_overlap/report_overdue_strict_greater_crossing
        """
        vessel, plan, voyage = self._setup_late_voyage()
        # due_at == 2026-08-09T00:00:00Z; at the deadline exactly the clock is not
        # yet PAST due_at, so the flag stays false.
        set_clock("2026-08-09T00:00:00Z")
        report = find_report(vessel["id"], voyage["id"], "PRE_ARRIVAL")
        assert_timestamp_equals(report["due_at"], "2026-08-09T00:00:00Z",
                                label="PRE_ARRIVAL due_at")
        assert report["is_overdue"] is False

    def test_report_flips_overdue_one_second_past_due(self, api, flag_surveyor_headers):
        """PRD section 3.4: "A report in `DRAFT` whose deadline passes while still
        unsubmitted flips the voyage's `reporting_status` to `OVERDUE` and creates a
        noncompliance record with `source_type` `REPORT_OVERDUE`."
        PRD section 3.10: "an overdue report 10"
        PRD section 3.10: "A score of at least 70 yields `CRITICAL`; at least 40
        yields `MAJOR`; otherwise `MINOR`."

        Design: Difficulty/resource_temporal_overlap/report_overdue_strict_greater_crossing
        """
        vessel, plan, voyage = self._setup_late_voyage()
        set_clock("2026-08-09T00:00:01Z")

        report = find_report(vessel["id"], voyage["id"], "PRE_ARRIVAL")
        assert report["is_overdue"] is True

        refreshed = get_voyage(vessel["id"], voyage["id"])
        assert refreshed["reporting_status"] == "OVERDUE"

        record = find_noncompliance(vessel["id"], voyage["id"], source_type="REPORT_OVERDUE")
        # Score 10 (overdue report), posture OPEN at detection -> MINOR.
        assert record["severity"] == "MINOR"


class TestReportRejectionLoop:
    def _setup_submitted_report(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000008", vessel_name="MV Heron", voyage_number="V4003",
            arrived_at="2026-08-10T00:00:00Z",
        )
        report = find_report(vessel["id"], voyage["id"], "PRE_ARRIVAL")
        submit_report_ok(vessel["id"], voyage["id"], report["id"])
        return vessel, voyage, report

    def test_reject_returns_reporting_status_to_due(self, api, flag_surveyor_headers):
        """PRD section 3.4: "or reject it with a `rejection_reason`, moving the report
        to `REJECTED` and returning the voyage's `reporting_status` to `DUE` so the
        master must resubmit."

        Design: Difficulty/non_linear_state_machine/report_reject_returns_reporting_axis_to_due
        """
        vessel, voyage, report = self._setup_submitted_report()
        resp = api.reject_report(vessel["id"], voyage["id"], report["id"],
                                 {"rejection_reason": "missing tank-level uptake rows"},
                                 flag_surveyor_headers)
        rejected = validate_success(resp, 200)
        assert rejected["status"] == "REJECTED"

        refreshed = get_voyage(vessel["id"], voyage["id"])
        assert refreshed["reporting_status"] == "DUE", (
            "reporting axis must loop back to DUE on rejection"
        )

    def test_reject_sets_reason_and_leaves_compliance_axis_untouched(
            self, api, flag_surveyor_headers):
        """PRD section 3.4: "or reject it with a `rejection_reason`, moving the report
        to `REJECTED` and returning the voyage's `reporting_status` to `DUE` so the
        master must resubmit. Both `ACKNOWLEDGED` and `REJECTED` are terminal for the
        report."
        PRD section 3.4: "Each voyage carries a parallel `reporting_status` axis —
        `NOT_DUE`, `DUE`, `SUBMITTED`, `ACKNOWLEDGED`, or `OVERDUE` — independent of
        `compliance_status`."

        Design: Difficulty/non_linear_state_machine/report_reject_returns_reporting_axis_to_due
        """
        vessel, voyage, report = self._setup_submitted_report()
        resp = api.reject_report(vessel["id"], voyage["id"], report["id"],
                                 {"rejection_reason": "missing tank-level uptake rows"},
                                 flag_surveyor_headers)
        rejected = validate_success(resp, 200)
        assert rejected["rejection_reason"] == "missing tank-level uptake rows"

        refreshed = get_voyage(vessel["id"], voyage["id"])
        assert refreshed["compliance_status"] == "IN_PROGRESS", (
            "report rejection must not touch the compliance axis"
        )


class TestReportTerminalLockdown:
    def test_report_acknowledge_twice_returns_409(self, api, vessel_master_headers,
                                                  flag_surveyor_headers):
        """PRD section 3.4: "Both `ACKNOWLEDGED` and `REJECTED` are terminal for the
        report."
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/report_acknowledge_twice_returns_409
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100023", vessel_name="MV Noddy", voyage_number="V9303",
            arrived_at="2026-08-10T00:00:00Z",
        )
        report = find_report(vessel["id"], voyage["id"], "PRE_ARRIVAL")
        submit_report_ok(vessel["id"], voyage["id"], report["id"])
        ack = api.acknowledge_report(vessel["id"], voyage["id"], report["id"],
                                     flag_surveyor_headers)
        validate_success(ack, 200)

        resp = api.acknowledge_report(vessel["id"], voyage["id"], report["id"],
                                      flag_surveyor_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
