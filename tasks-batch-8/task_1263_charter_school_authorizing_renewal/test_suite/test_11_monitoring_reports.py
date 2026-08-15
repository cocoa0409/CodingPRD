"""Monitoring report guards: return/resubmit cycle, standing-band floors, and
per-year uniqueness (PRD §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_open_school, add_monitoring_report, accept_report,
    make_staff_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


class TestReportReturnRequiresNotes:
    def test_return_without_notes_rejected(self, api):
        """PRD §3.3: "When a report needs correction, staff return it
        (`SUBMITTED` → `RETURNED`) with non-empty `return_notes`; missing notes
        are rejected with `ERR_INVALID_REQUEST`, and the notes are recorded on
        the report."

        Design: Corner/state_machines/sm_report_return_requires_notes
        """
        ctx = create_open_school(school_name="SM Report Academy",
                                 applicant_id="applicant_s3")
        report = add_monitoring_report(ctx["school"]["id"], fiscal_year=2028,
                                       academic_score=85, financial_score=85,
                                       operational_score=85)
        res = api.return_monitoring_report(report["id"], {}, STAFF)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        reports = validate_success(
            api.list_monitoring_reports(ctx["school"]["id"], STAFF), 200)
        assert reports[0]["status"] == "SUBMITTED"


class TestReportResubmitFromSubmittedRejected:
    def test_resubmit_requires_returned_status(self, api):
        """PRD §3.3: "Resubmission cycles the report `RETURNED` → `SUBMITTED` —
        any other status draws `ERR_REPORT_INVALID_STATE` — clears
        `return_notes` to null, and recomputes the `compliance_index` from the
        current scores."

        Design: Corner/state_machines/sm_report_resubmit_from_submitted_rejected
        """
        ctx = create_open_school(school_name="SM Resubmit Academy",
                                 applicant_id="applicant_s4")
        report = add_monitoring_report(ctx["school"]["id"], fiscal_year=2028,
                                       academic_score=85, financial_score=85,
                                       operational_score=85)
        assert report["status"] == "SUBMITTED"
        res = api.resubmit_monitoring_report(report["id"], STAFF)
        validate_error(res, ApiErrorId.ERR_REPORT_INVALID_STATE, expected_status=409)
        reports = validate_success(
            api.list_monitoring_reports(ctx["school"]["id"], STAFF), 200)
        assert reports[0]["status"] == "SUBMITTED"


class TestStandingBandFloorBoundaries:
    def test_band_floors_are_inclusive(self, api):
        """PRD §3.3: "Each domain score is mapped to a standing band: a score
        of eighty or above lands `GOOD`, sixty-five up to but not including
        eighty lands `NOTICE`, fifty up to but not including sixty-five lands
        `PROBATION`, and below fifty lands `CRITICAL`; boundaries are inclusive
        at the lower edge of each band, so exactly 80.0 is `GOOD`."

        Design: Corner/calculations/calc_standing_band_floor_boundaries
        """
        ctx = create_open_school(school_name="Calc Band Academy",
                                 applicant_id="applicant_c1")
        report = add_monitoring_report(ctx["school"]["id"], fiscal_year=2028,
                                       academic_score=80, financial_score=65,
                                       operational_score=50)
        # operational 50 < 60 doubles: (0.5*80 + 0.25*65 + 0.5*50)/1.25 = 65.0
        assert report["compliance_index"] == pytest.approx(65.0, abs=0.001)
        accept_report(report["id"], staff_id="staff_c1")
        school = validate_success(api.get_school(ctx["school"]["id"], STAFF), 200)
        assert school["academic_standing"] == "GOOD"          # exactly 80
        assert school["financial_standing"] == "NOTICE"       # exactly 65
        assert school["operational_standing"] == "PROBATION"  # exactly 50

        notices = validate_success(
            api.list_interventions(ctx["school"]["id"], STAFF), 200)
        assert len(notices) == 1
        assert notices[0]["domain"] == "OPERATIONAL"
        assert notices[0]["level"] == "PROBATION"
        assert notices[0]["status"] == "ISSUED"


class TestDuplicateReportYearRejected:
    def test_second_report_same_fiscal_year_rejected(self, api):
        """PRD §3.3: "One report per school per fiscal year is allowed; a
        duplicate is rejected with `ERR_DUPLICATE_RECORD`."

        Design: Corner/validations/val_duplicate_report_year_rejected
        """
        ctx = create_open_school(school_name="Val DupRep Academy",
                                 applicant_id="applicant_v4")
        add_monitoring_report(ctx["school"]["id"], fiscal_year=2028,
                              academic_score=85, financial_score=85,
                              operational_score=85)
        res = api.create_monitoring_report(
            ctx["school"]["id"],
            {"fiscal_year": 2028, "academic_score": 90, "financial_score": 90,
             "operational_score": 90},
            STAFF)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_RECORD, expected_status=409)
