"""Emission report lifecycle: lines, documents, supporting-document gating,
total_reported_emissions calculation, submit window, resubmit cycle.

PRD references:
  - §3.3 Emission Reporting Lifecycle
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_seconds,
    add_emission_line_payload,
    advance_clock,
    assert_emission_data_line,
    assert_emission_report,
    assert_supporting_document,
    create_draft_report,
    add_line,
    upload_document,
    submit_report,
    setup_compliance_open_cycle,
    setup_submitted_report,
    make_enterprise_headers,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 — Initial draft state
# ===========================================================================
class TestEmissionReportCreation:
    def test_draft_report_starts_in_draft_with_zero_totals(self):
        """PRD §3.3: 'The created report begins in status DRAFT with version
        1 (or one greater than the previous version for the same enterprise
        and cycle year), is_current_version true, total_reported_emissions
        zero, total_verified_emissions null, submitted_at null, and
        supporting_document_count zero.'

        Claim: a freshly-created EmissionReport has status=DRAFT,
        is_current_version=true, total_reported_emissions=0,
        total_verified_emissions=null, submitted_at=null,
        supporting_document_count=0, version=1.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        assert_emission_report(rep)
        assert rep["status"] == "DRAFT"
        assert rep["is_current_version"] is True
        assert rep["total_reported_emissions"] == 0
        assert rep.get("total_verified_emissions") is None
        assert rep.get("submitted_at") is None
        assert rep["supporting_document_count"] == 0
        # First version per (enterprise, cycle_year) starts at 1.
        assert rep["version"] == 1


# ===========================================================================
# §3.3 — Supporting documents
# ===========================================================================
class TestSupportingDocuments:
    def test_upload_document_increments_supporting_document_count(self):
        """PRD §3.3: 'On upload, uploaded_at is recorded and the report's
        supporting_document_count is incremented by one.'

        Claim: after one document upload, report.supporting_document_count
        == 1.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        doc = upload_document(
            report_id=rep["id"], enterprise_id=ent["id"]
        )
        assert_supporting_document(doc)
        from test_helpers import get_report
        rep2 = get_report(rep["id"], headers=make_enterprise_headers(ent["id"]))
        assert rep2["supporting_document_count"] == 1


# ===========================================================================
# §3.3 — supporting_document_id requirement (FUEL/PROCESS)
# ===========================================================================
class TestSupportingDocumentRequired:
    @pytest.mark.parametrize("source_category", ["FUEL", "PROCESS"])
    def test_fuel_or_process_line_without_document_rejected(
        self, api, source_category
    ):
        """PRD §3.3: 'A line whose source_category is FUEL or PROCESS
        requires a supporting_document_id; a line of either category
        without one is rejected with ERR_SUPPORTING_DOCUMENT_REQUIRED.'

        Claim: adding a FUEL or PROCESS line without supporting_document_id
        -> ERR_SUPPORTING_DOCUMENT_REQUIRED.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        payload = add_emission_line_payload(
            source_category=source_category,
            activity_data=10.00,
            emission_factor=2.00,
        )
        res = api.add_emission_line(
            rep["id"], payload, make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_SUPPORTING_DOCUMENT_REQUIRED")

    @pytest.mark.parametrize("source_category", ["ELECTRICITY", "FUGITIVE"])
    def test_electricity_or_fugitive_line_without_document_accepted(
        self, source_category
    ):
        """PRD §3.3: 'A line whose source_category is FUEL or PROCESS
        requires a supporting_document_id; a line of either category
        without one is rejected with ERR_SUPPORTING_DOCUMENT_REQUIRED.'

        Claim (contrapositive): ELECTRICITY and FUGITIVE lines do NOT
        require a supporting_document_id, so creation succeeds.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        line = add_line(
            report_id=rep["id"], enterprise_id=ent["id"],
            source_category=source_category,
            activity_data=10.00,
            emission_factor=2.00,
        )
        assert_emission_data_line(line)


# ===========================================================================
# §3.3 — total_reported_emissions calculation
# ===========================================================================
class TestTotalReportedEmissions:
    def test_per_line_round_then_sum(self):
        """PRD §3.3: 'The total reported emissions on a report is computed
        as follows: for each emission data line attached to the report,
        multiply the line's activity_data by its emission_factor, round
        that product half-up to two decimal places, then sum the rounded
        per-line values. ... This rounding order is canonical and must
        not be reversed: rounding the sum of unrounded activity_data *
        emission_factor products produces different cents and is forbidden.'

        Claim: with two ELECTRICITY lines each (activity_data=1.000,
        emission_factor=0.005), each line.source_amount rounds to 0.01
        (round_half_up of 0.005), and report.total_reported_emissions = 0.02
        (per-line then sum). The 'sum then round' alternative would yield 0.01.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
            lines=[
                {"source_category": "ELECTRICITY",
                 "activity_data": 1.000, "emission_factor": 0.005},
                {"source_category": "ELECTRICITY",
                 "activity_data": 1.000, "emission_factor": 0.005},
            ],
        )
        # PRD §3.3: 'When the enterprise submits the report ...
        # total_reported_emissions is recomputed.'
        assert rep["total_reported_emissions"] == pytest.approx(0.02, abs=1e-6)


# ===========================================================================
# §3.3 — Submit preconditions (window, lines, documents)
# ===========================================================================
class TestSubmitPreconditions:
    def test_submit_with_no_lines_rejected(self, api):
        """PRD §3.3: 'Submission is permitted only when the parent cycle's
        status is COMPLIANCE_OPEN, the current time is at or before the
        report's submission deadline, at least one emission data line
        exists, and every line whose source category is FUEL or PROCESS
        carries a supporting_document_id.'

        Claim: submitting a report with zero EmissionDataLine rows ->
        ERR_INVALID_STATE (the state-precondition class per PRD §2.8 priority).
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        res = api.submit_emission_report(
            rep["id"], make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_submit_after_submission_deadline_rejected(self, api):
        """PRD §3.3: 'Submitting after the deadline is rejected with
        ERR_WINDOW_CLOSED'. Submission deadline = compliance_deadline - 90d.

        Claim: advancing the clock past submission_deadline causes
        submit -> ERR_WINDOW_CLOSED.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        # add one ELECTRICITY line so the line-count precondition is satisfied
        add_line(
            report_id=rep["id"], enterprise_id=ent["id"],
            source_category="ELECTRICITY",
            activity_data=10.00, emission_factor=1.00,
        )
        # Move clock 1 second past compliance_deadline (also past
        # submission_deadline since submission_deadline = compliance - 90d).
        advance_clock(add_seconds(cyc["compliance_deadline"], 1))
        res = api.submit_emission_report(
            rep["id"], make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_WINDOW_CLOSED")


# ===========================================================================
# §3.3 — Submit success
# ===========================================================================
class TestSubmitSuccess:
    def test_submit_transitions_to_submitted_and_sets_submitted_at(self):
        """PRD §3.3: 'When the enterprise submits the report, the report
        transitions from DRAFT to SUBMITTED, submitted_at is set to the
        current time, and total_reported_emissions is recomputed.'

        Claim: post-submit report has status='SUBMITTED', non-null
        submitted_at.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
        )
        assert rep["status"] == "SUBMITTED"
        assert rep.get("submitted_at") is not None


# ===========================================================================
# §3.3 — Resubmission cycle (DRAFT -> SUBMITTED -> DRAFT via versioning)
# ===========================================================================
class TestResubmissionCycle:
    def test_new_version_increments_and_marks_previous_not_current(self):
        """PRD §3.3: 'A SUBMITTED or REJECTED report may be resubmitted by
        the enterprise, which creates a new DRAFT report with version equal
        to the previous version plus one for the same (enterprise, cycle_year)
        pair, and sets the previous report's is_current_version to false.'

        Claim: after creating a second report for the same (enterprise,
        cycle_year), the new report.version == previous.version + 1, and
        the previous report's is_current_version becomes false.
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        first = setup_submitted_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"],
        )
        # A new draft for the same (enterprise, cycle_year) creates v2.
        second = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        assert second["version"] == first["version"] + 1, (
            f"PRD §3.3: new version must be previous + 1; got "
            f"{second['version']} after {first['version']}"
        )
        # Previous version's is_current_version becomes false.
        from test_helpers import get_report
        first_after = get_report(
            first["id"], headers=make_enterprise_headers(ent["id"])
        )
        assert first_after["is_current_version"] is False, (
            "PRD §3.3: previous version's is_current_version must be set "
            "to false when a new version is created"
        )
