"""Annual reporting at one instant: the March deadline decides lateness on the filing call, the
report year gates every disclosure, and the attestation must cover what the camp already told
the office."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    annual_report_payload,
    annual_report_submit_payload,
    incident_disclosure_payload,
)
from test_helpers.test_users import make_camp_director_headers
from test_helpers.types import (
    AnnualReportDecision,
    AnnualReportStatus,
    CampType,
    DisclosureStatus,
    HealthStaffingLevel,
    IncidentType,
    PopulationServed,
)
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)


def _camp_with_two_draft_reports(api):
    """One camp holding a 2026 report still in time and a 2025 report already overdue."""
    fx.reset_clock(api)
    camp = fx.register_camp(
        api,
        name="Reporting Camp",
        camp_type=CampType.DAY,
        state_code="OH",
        population_served=PopulationServed.YOUTH_ONLY,
        health_staffing_level=HealthStaffingLevel.FIRST_AIDER_ONLY,
    )
    return {
        "camp": camp,
        "report_2026": fx.open_annual_report(api, camp["id"], 2026),
        "report_2025": fx.open_annual_report(api, camp["id"], 2025),
    }


def _disclosure_attempt(api, camp_id, report_id, incident_type, occurred_at):
    return api.create_incident_disclosure(
        incident_disclosure_payload(report_id, incident_type, occurred_at),
        make_camp_director_headers(camp_id),
    )


def _filing_attempt(api, camp_id, report_id, declared_incident_count):
    return api.submit_annual_report(
        report_id,
        annual_report_submit_payload(declared_incident_count),
        make_camp_director_headers(camp_id),
    )


def test_the_report_year_gates_every_disclosure_filed_under_it(api):
    """PRD §3.9: "the calendar year of `occurred_at` must equal the report's `report_year`, or
    the filing is rejected with `ERR_INCIDENT_OUTSIDE_REPORT_YEAR` (HTTP 422)."

    Design: Corner/validations/report_year_gates_each_disclosure_and_the_attested_count_must_cover_them
    """
    world = _camp_with_two_draft_reports(api)
    camp_id = world["camp"]["id"]
    assert world["report_2026"]["due_date"] == "2027-03-01"
    assert world["report_2025"]["due_date"] == "2026-03-01"
    for report in (world["report_2026"], world["report_2025"]):
        assert report["status"] == AnnualReportStatus.DRAFT
        assert report["disclosed_incident_count"] == 0

    validate_error(
        _disclosure_attempt(
            api,
            camp_id,
            world["report_2026"]["id"],
            IncidentType.HOSPITALIZATION,
            "2025-07-04T14:00:00.000Z",
        ),
        ApiErrorId.INCIDENT_OUTSIDE_REPORT_YEAR,
        422,
    )
    assert fx.read_annual_report(api, world["report_2026"]["id"])[
        "disclosed_incident_count"
    ] == 0

    hospitalization = fx.disclose_incident(
        api,
        camp_id,
        world["report_2026"]["id"],
        IncidentType.HOSPITALIZATION,
        "2026-07-04T14:00:00.000Z",
    )
    medication_error = fx.disclose_incident(
        api,
        camp_id,
        world["report_2026"]["id"],
        IncidentType.MEDICATION_ERROR,
        "2026-07-05T09:00:00.000Z",
    )
    # Neither arrived against an accepted report, so both are on time.
    assert hospitalization["status"] == DisclosureStatus.REPORTED
    assert medication_error["status"] == DisclosureStatus.REPORTED
    # The camp holds no state licence, so the state is owed no notification.
    assert hospitalization["state_notification_required"] is False
    assert fx.read_annual_report(api, world["report_2026"]["id"])[
        "disclosed_incident_count"
    ] == 2


def test_the_attestation_may_not_undercount_the_disclosures_already_filed(api):
    """PRD §3.9: "the declared count must be at least the report's `disclosed_incident_count`,
    or the filing is rejected with `ERR_DECLARED_COUNT_BELOW_DISCLOSED` (HTTP 422) — a camp
    cannot attest to fewer incidents than it has already disclosed."

    Design: Corner/validations/report_year_gates_each_disclosure_and_the_attested_count_must_cover_them
    """
    world = _camp_with_two_draft_reports(api)
    camp_id = world["camp"]["id"]
    report_id = world["report_2026"]["id"]
    fx.disclose_incident(
        api, camp_id, report_id, IncidentType.HOSPITALIZATION, "2026-07-04T14:00:00.000Z"
    )
    fx.disclose_incident(
        api, camp_id, report_id, IncidentType.MEDICATION_ERROR, "2026-07-05T09:00:00.000Z"
    )

    validate_error(
        _filing_attempt(api, camp_id, report_id, 1),
        ApiErrorId.DECLARED_COUNT_BELOW_DISCLOSED,
        422,
    )
    held = fx.read_annual_report(api, report_id)
    assert held["status"] == AnnualReportStatus.DRAFT
    assert held["submitted_at"] is None

    filed = validate_success(_filing_attempt(api, camp_id, report_id, 2))
    # The clock date 2026-08-01 is inside the 2027-03-01 deadline.
    assert filed["status"] == AnnualReportStatus.SUBMITTED
    assert filed["declared_incident_count"] == 2
    assert is_iso8601_timestamp(filed["submitted_at"])
    assert filed["submitted_at"].startswith("2026-08-01T00:00:00")
    assert filed["attested_by_user_id"] == camp_id


def test_a_second_report_for_the_same_year_shares_the_cycle_year_rule(api):
    """PRD §3.9: "a second report for the same camp and year is rejected with
    `ERR_DUPLICATE_CYCLE_YEAR` (HTTP 409)."

    Design: Corner/validations/report_year_gates_each_disclosure_and_the_attested_count_must_cover_them
    """
    world = _camp_with_two_draft_reports(api)
    camp_id = world["camp"]["id"]

    validate_error(
        api.create_annual_report(
            annual_report_payload(camp_id, 2026), make_camp_director_headers(camp_id)
        ),
        ApiErrorId.DUPLICATE_CYCLE_YEAR,
        409,
    )
    assert fx.read_annual_report(api, world["report_2026"]["id"])["report_year"] == 2026


def test_the_identical_filing_lands_late_once_the_deadline_has_passed(api):
    """PRD §3.9: "when the logical clock's calendar date is on or before `due_date` the report
    lands in `SUBMITTED`, and when it is after `due_date` the report lands in `LATE`."

    Design: Corner/validations/report_year_gates_each_disclosure_and_the_attested_count_must_cover_them
    """
    world = _camp_with_two_draft_reports(api)
    camp_id = world["camp"]["id"]
    report_id = world["report_2025"]["id"]

    filed = validate_success(_filing_attempt(api, camp_id, report_id, 0))
    assert filed["status"] == AnnualReportStatus.LATE
    assert filed["declared_incident_count"] == 0
    assert filed["attested_by_user_id"] == camp_id

    # Both landings are reviewable and reach the same target.
    reviewed = fx.review_annual_report(
        api, report_id, AnnualReportDecision.ACCEPT, "late filing accepted"
    )
    assert reviewed["status"] == AnnualReportStatus.ACCEPTED
    assert reviewed["reviewer_note"] == "late filing accepted"
