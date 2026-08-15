"""Coalition and regulatory reporting: due-date offsets, lateness scoring, and
segregation of duties on submission."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_external_report,
    assert_timestamp_instant,
    create_external_report,
    create_staff_member,
    make_hospital_administrator_headers,
    make_liaison_officer_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _liaison_admin_pair():
    liaison = create_staff_member(full_name="Lo User", department="ADMINISTRATION",
                                  role_qualifications=["LIAISON_OFFICER"])
    admin = create_staff_member(full_name="Ha User", department="ADMINISTRATION")
    return liaison, admin


class TestFilingDeadlines:
    def test_external_report_due_offsets_and_hours_late(self, api):
        """PRD §3.9: "The filing deadline is computed at creation from the report
        type: `due_at` is `period_end` plus 24 hours for `SITREP` and
        `RESOURCE_REQUEST`, plus 72 hours for `SURGE_CAPACITY`, and plus 720 hours
        — thirty days — for `AAR_SUMMARY`."
        PRD §3.9: "Submission stamps `submitted_at`, advances the report's
        `version`, and scores lateness: `submitted_late` is true exactly when
        `submitted_at` falls strictly after `due_at` — filing precisely at the
        deadline is on time — and `hours_late` is the number of seconds between
        `due_at` and `submitted_at`, floored at zero, divided by 3600, and rounded
        half-up to two decimal places."
        PRD §3.9: "Late filings are accepted and flagged, never rejected — a
        regulator would rather see a late report than no report."

        Design: Corner/calculations/external_report_due_offsets_and_hours_late
        """
        liaison, admin = _liaison_admin_pair()
        sitrep = create_external_report(
            creator_id=liaison["id"], audience="STATE_DOH", report_type="SITREP",
            body_summary="sitrep body",
        )
        aar_summary = create_external_report(
            creator_id=liaison["id"], audience="CMS", report_type="AAR_SUMMARY",
            body_summary="aar summary",
        )
        assert_timestamp_instant(sitrep["due_at"], "2026-08-11T00:00:00Z")
        # period_end + 24h
        assert_timestamp_instant(aar_summary["due_at"], "2026-09-09T00:00:00Z")
        # period_end + 720h (thirty days)

        set_clock("2026-08-11T03:36:00Z")
        submitted = validate_success(
            api.submit_external_report(
                sitrep["id"], make_hospital_administrator_headers(admin["id"])
            )
        )
        assert_external_report(submitted)
        assert submitted["status"] == "SUBMITTED", "late filing accepted, not rejected"
        assert submitted["submitted_late"] is True
        assert submitted["hours_late"] == pytest.approx(3.6, abs=1e-9), (
            "3h36m past due at 2dp round-half-up"
        )


class TestSubmissionSegregation:
    def test_report_submit_by_creator_rejected_segregation(self, api):
        """PRD §2.7: "An external report records `created_by_id`, and its
        submission is rejected with `ERR_SEGREGATION_OF_DUTIES` when the submitter
        is the author — a `LiaisonOfficer` who drafted a report may not submit it,
        and neither may a `HospitalAdministrator` who drafted one on another's
        behalf."
        PRD §3.9: "Submission — `DRAFT` → `SUBMITTED`, terminal and immutable
        thereafter — may be performed by a `LiaisonOfficer` or a
        `HospitalAdministrator`, but never by the draft's own author (§2.7,
        `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/report_submit_by_creator_rejected_segregation
        """
        liaison, admin = _liaison_admin_pair()
        report = create_external_report(
            creator_id=liaison["id"], audience="REGIONAL_COALITION",
            report_type="SITREP", body_summary="coalition sitrep",
        )

        resp = api.submit_external_report(
            report["id"], make_liaison_officer_headers(liaison["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        submitted = validate_success(
            api.submit_external_report(
                report["id"], make_hospital_administrator_headers(admin["id"])
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_late"] is False, (
            "submitted at the 2026-08-01 startup clock, well before due 2026-08-11"
        )
        assert submitted["hours_late"] == pytest.approx(0.0, abs=1e-9)
