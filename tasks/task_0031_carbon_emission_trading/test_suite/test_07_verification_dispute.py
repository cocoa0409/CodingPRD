"""Verification, dispute, finalize lifecycle.

PRD references:
  - §3.4 Verification, Dispute, and Finalization
  - §2.8 Validation Priority Order
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_hours,
    add_seconds,
    advance_clock,
    assert_verification_assignment,
    assign_verifier_payload,
    current_clock_iso,
    dispute_emission_report_payload,
    finalize_report,
    get_report,
    issue_verification_report,
    make_enterprise_headers,
    make_verifier_agency_headers,
    setup_submitted_report,
    setup_verified_report,
    setup_compliance_open_cycle,
    unique_agency_id,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 — assign-verifier preconditions
# ===========================================================================
class TestAssignVerifier:
    def test_assign_verifier_with_visit_under_seven_days_rejected(
        self, api, regulator_headers
    ):
        """PRD §3.4: 'the visit must be at least 7 days in the future from
        the time of assignment, otherwise the request is rejected with
        ERR_WINDOW_CLOSED'.

        Claim: scheduled_visit_at = now + 6d 23h 59m -> ERR_WINDOW_CLOSED.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        cur = current_clock_iso()
        bad_visit = add_hours(add_days(cur, 6), 23 + 59 / 60.0)  # ~6d 23h 59m
        payload = assign_verifier_payload(
            agency_id=unique_agency_id(),
            scheduled_visit_at=bad_visit,
        )
        res = api.assign_verifier(rep["id"], payload, regulator_headers)
        validate_error(res, "ERR_WINDOW_CLOSED")

    def test_assign_verifier_with_visit_at_seven_days_accepted(
        self, api, regulator_headers
    ):
        """PRD §3.4: 'the visit must be at least 7 days in the future from
        the time of assignment'.

        Claim: scheduled_visit_at = now + 7d 0h 0m exactly succeeds
        (boundary inclusive on the AT-LEAST side).
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        cur = current_clock_iso()
        ok_visit = add_days(cur, 7)
        payload = assign_verifier_payload(
            agency_id=unique_agency_id(),
            scheduled_visit_at=ok_visit,
        )
        res = api.assign_verifier(rep["id"], payload, regulator_headers)
        assignment = validate_success(res, expected_status=201)
        assert_verification_assignment(assignment)
        assert assignment["status"] == "ASSIGNED"

    def test_assign_verifier_to_self_rejected(self, api, regulator_headers):
        """PRD §3.4: 'the assigned agency_id must not equal the
        enterprise_id of the enterprise being verified, otherwise the
        request is rejected with ERR_VERIFIER_CONFLICT_OF_INTEREST.'

        Claim: agency_id == enterprise_id -> ERR_VERIFIER_CONFLICT_OF_INTEREST.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        cur = current_clock_iso()
        ok_visit = add_days(cur, 8)
        payload = assign_verifier_payload(
            agency_id=ent["id"],  # self!
            scheduled_visit_at=ok_visit,
        )
        res = api.assign_verifier(rep["id"], payload, regulator_headers)
        validate_error(res, "ERR_VERIFIER_CONFLICT_OF_INTEREST")


# ===========================================================================
# §3.4 — Verification report issuance
# ===========================================================================
class TestIssueVerificationReport:
    def test_issue_report_transitions_report_to_verified(self):
        """PRD §3.4: 'The verifier then issues the verification report,
        transitioning the assignment from ON_SITE_DONE to REPORT_ISSUED
        with report_issued_at set to the current time, and the report from
        UNDER_VERIFICATION to VERIFIED with total_verified_emissions and
        per-line verified_amount written.'

        Claim: after complete-onsite + issue-report, the EmissionReport.status
        is VERIFIED and assignment.status is REPORT_ISSUED with non-null
        report_issued_at.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, issued = setup_verified_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00,
                "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        assert verified_report["status"] == "VERIFIED"
        assert issued["status"] == "REPORT_ISSUED"
        assert issued.get("report_issued_at") is not None

    def test_total_verified_emissions_sums_per_line_verified_amounts(self):
        """PRD §3.4: 'the report's total_verified_emissions is the sum of
        these rounded line amounts (no extra rounding across lines).'

        Claim: with one line whose verified_amount=55.00,
        total_verified_emissions == 55.00.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, _issued = setup_verified_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00,
                "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        assert verified_report["total_verified_emissions"] == pytest.approx(
            55.00, abs=0.01
        )


# ===========================================================================
# §3.4 — Dispute window
# ===========================================================================
class TestDisputeWindow:
    def test_dispute_after_fourteen_days_rejected(self, api):
        """PRD §3.4: 'A VERIFIED report may be disputed by the enterprise
        with a payload containing ground (the textual reason), but only
        within 14 days of the assignment's report_issued_at; outside that
        window the request is rejected with ERR_WINDOW_CLOSED.'

        Claim: at clock = report_issued_at + 14d 0h 1s, dispute ->
        ERR_WINDOW_CLOSED.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, issued = setup_verified_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00,
                "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        # Move clock just past 14 days after report_issued_at.
        advance_clock(add_seconds(add_days(issued["report_issued_at"], 14), 1))
        res = api.dispute_emission_report(
            verified_report["id"],
            dispute_emission_report_payload(),
            make_enterprise_headers(ent["id"]),
        )
        validate_error(res, "ERR_WINDOW_CLOSED")


# ===========================================================================
# §3.4 — Dispute lifecycle (cycle through DISPUTED -> VERIFIED)
# ===========================================================================
class TestDisputeCycle:
    def test_dispute_then_resolve_returns_to_verified(
        self, api, regulator_headers
    ):
        """PRD §3.4: 'A regulator resolves the dispute, optionally
        supplying an adjusted_total_verified_emissions; the assignment
        moves from DISPUTED to RESOLVED and the report returns from
        DISPUTED to VERIFIED.'

        Claim: report cycles VERIFIED -> DISPUTED -> VERIFIED, and the
        assignment status sequence is REPORT_ISSUED -> DISPUTED -> RESOLVED.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, issued = setup_verified_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00,
                "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        # Dispute within window.
        res_d = api.dispute_emission_report(
            verified_report["id"],
            dispute_emission_report_payload(),
            make_enterprise_headers(ent["id"]),
        )
        disputed = validate_success(res_d, expected_status=200)
        assert disputed["status"] == "DISPUTED"

        # Regulator resolves.
        res_r = api.resolve_dispute(issued["id"], regulator_headers)
        resolved = validate_success(res_r, expected_status=200)
        assert resolved["status"] == "RESOLVED"

        # Re-fetch the report; should be back to VERIFIED.
        from test_helpers import get_report
        rep_after = get_report(
            verified_report["id"],
            headers=make_enterprise_headers(ent["id"]),
        )
        assert rep_after["status"] == "VERIFIED"


# ===========================================================================
# §3.4 — Finalize lock
# ===========================================================================
class TestReportFinalize:
    def test_finalize_locks_report(self):
        """PRD §3.4: 'After the verification report is issued and the 14-day
        dispute window has either elapsed or the enterprise has waived
        dispute, a regulator finalizes the report. ... the report
        transitions from VERIFIED to FINALIZED and is locked, serving as
        the authoritative input for the compliance declaration.'

        Claim: post-finalize report.status == FINALIZED.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, issued = setup_verified_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00,
                "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        advance_clock(add_days(issued["report_issued_at"], 14.5))
        finalized = finalize_report(report_id=verified_report["id"])
        assert finalized["status"] == "FINALIZED"
