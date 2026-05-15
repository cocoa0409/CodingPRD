"""Case reporting, late-flag, deduplication, ownership — PRD §3.2, §3.10."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_case,
    create_case_payload,
    create_institution,
    create_person,
    create_region,
    file_case,
    iso_utc,
    iso_utc_midnight,
    make_hospital_reporter_headers,
    setup_district_with_hospital,
    validate_error,
    validate_success,
)


# ===========================================================================
# Case creation basics — PRD §3.2
# ===========================================================================
class TestCaseCreation:

    def test_create_case_defaults_status_reported(self, api):
        """PRD §3.2: "The case status begins at REPORTED."

        Claim: a newly filed case has status REPORTED.
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-CASE-1",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        assert_case(case)
        assert case["status"] == "REPORTED"
        assert case["case_type"] == "CONFIRMED"
        assert case["person_id"] == person["id"]
        assert case["reporting_institution_id"] == hospital["id"]

    def test_create_case_with_unknown_person_returns_reference_not_found(
        self, api,
    ):
        """PRD §2.6: "Foreign keys carried in the request body ... are
        resolved separately; a missing body FK yields
        ERR_REFERENCE_NOT_FOUND."

        Claim: filing a case with an unresolvable person_id →
        ERR_REFERENCE_NOT_FOUND.
        """
        _region, hospital = setup_district_with_hospital(
            district_code="D-CASE-FK",
        )
        bad_payload = create_case_payload(
            person_id="00000000-0000-0000-0000-000000000000",
            reporting_institution_id=hospital["id"],
            case_type="CONFIRMED",
        )
        resp = api.create_case(
            bad_payload, make_hospital_reporter_headers(hospital["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Late-report flag — PRD §3.2 case_report_lateness
# ===========================================================================
class TestLateReportFlag:

    def test_report_within_window_is_on_time(self, api):
        """PRD §3.2: "On creation the server stamps reported_at with the
        current wall clock and computes report_deadline_at as the
        onset_date plus the report-window constant — 24 hours from
        onset. The boolean is_late_report is then set to true exactly
        when reported_at is strictly later than report_deadline_at;
        equality counts as on-time and the flag is persisted once at
        creation and not recomputed later."

        Claim: filing a case where onset_date is today (UTC midnight)
        within the 24-hour window flags is_late_report == false.
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-LATE-1",
        )
        person = create_person(district_code=region["district_code"])
        # Onset date set to "today midnight" — server's "now" should be
        # at most a few seconds past the test start, well inside 24h.
        today_midnight = iso_utc_midnight(datetime.now(timezone.utc))
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
            onset_date=today_midnight,
        )
        assert case["is_late_report"] is False, (
            f"Onset_date today_midnight should be on-time, "
            f"got is_late_report={case['is_late_report']}"
        )

    def test_report_past_deadline_is_late(self, api):
        """PRD §3.2: "The boolean is_late_report is then set to true
        exactly when reported_at is strictly later than
        report_deadline_at."

        Claim: filing a case where onset_date is more than 24h before
        now flags is_late_report == true. We park onset_date 3 calendar
        days in the past so the strict-greater comparison is
        unambiguous.
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-LATE-2",
        )
        person = create_person(district_code=region["district_code"])
        three_days_ago_midnight = iso_utc_midnight(
            datetime.now(timezone.utc) - timedelta(days=3),
        )
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
            onset_date=three_days_ago_midnight,
        )
        assert case["is_late_report"] is True, (
            f"Onset 3 days ago should produce is_late_report=true, "
            f"got is_late_report={case['is_late_report']}"
        )


# ===========================================================================
# Deduplication — PRD §3.2
# ===========================================================================
class TestCaseDeduplication:

    def test_duplicate_filing_marks_second_deduplicated(self, api):
        """PRD §3.2: "Two cases for the same (person_id, case_type)
        cannot both be in non-terminal status. When a hospital files a
        duplicate report for a person who already has a non-terminal
        case (REPORTED, UNDER_TRACING, or CONFIRMED) of the same type,
        the new row is auto-marked DEDUPLICATED with its
        superseded_by_case_id pointing at the surviving case."

        Claim: second sequential file for the same (person_id,
        case_type) is auto-marked DEDUPLICATED with
        superseded_by_case_id set to the first case.id.
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-DEDUP-1",
        )
        person = create_person(district_code=region["district_code"])

        first = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        assert first["status"] == "REPORTED"

        second = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        assert second["status"] == "DEDUPLICATED"
        assert second["superseded_by_case_id"] == first["id"], (
            f"PRD §3.2: superseded_by_case_id must point at surviving "
            f"case {first['id']!r}, got {second['superseded_by_case_id']!r}"
        )

    def test_duplicate_different_case_type_is_not_deduplicated(self, api):
        """PRD §3.2: "Two cases for the same (person_id, case_type)
        cannot both be in non-terminal status."

        Claim: two cases for the same person but different case_type
        coexist — the (person_id, case_type) tuple is the dedup key,
        not person_id alone.
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-DEDUP-2",
        )
        person = create_person(district_code=region["district_code"])

        first = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        second = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="ASYMPTOMATIC",
        )
        assert first["status"] == "REPORTED"
        assert second["status"] == "REPORTED", (
            f"Different case_type tuple — second case should NOT be "
            f"deduplicated; got status={second['status']}"
        )
        assert second.get("superseded_by_case_id") in (None, "")


# ===========================================================================
# Institution-active check — PRD §2.7
# ===========================================================================
class TestInstitutionActiveCheck:

    def test_filing_ignores_unrelated_active_institutions(self, api):
        """PRD §2.7: "Four mutating endpoints — case filing, test-order
        creation, test-result ingestion, and contact-event ingestion —
        additionally require that the acting ReportingInstitution carry
        status equal to ACTIVE."

        Claim: filing a case with a freshly-created ACTIVE institution
        succeeds (defaults to ACTIVE per §3.1, so this is the happy
        path for the institution-active validation).
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-ACTIVE-1",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        assert case["status"] == "REPORTED"
