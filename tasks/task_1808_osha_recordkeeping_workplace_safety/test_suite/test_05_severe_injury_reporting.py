"""Severe-injury agency reporting: clocks, immutability, risk-score feed."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_severe_report,
    create_case,
    create_classified_case,
    create_corrective_action,
    file_severe_report,
    get_establishment,
    set_clock,
    setup_org,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OFFICER


class TestOneReportPerCase:
    def test_severe_report_duplicate_per_case_rejected(self, api):
        """PRD §3.6: "Only one report may exist per case, a duplicate failing
        with `ERR_DUPLICATE`, and inconsistent report timestamps fail with
        `ERR_SEVERE_REPORT_REQUIRED`."

        Design: Corner/state_machines/severe_report_duplicate_per_case_rejected
        """
        _, establishment, employee = setup_org(fein="56-0000014",
                                               site_name="Site SR")
        case = create_case(establishment["id"], employee["id"],
                           "2026-08-01T10:00:00Z", description="Sev",
                           body_part="eyes", is_severe_event="EYE_LOSS")
        file_severe_report(case["id"], "EYE_LOSS", "2026-08-01T10:00:00Z",
                           "2026-08-01T20:00:00Z")

        resp = api.create_severe_report(
            case["id"],
            {"report_kind": "EYE_LOSS",
             "occurred_at": "2026-08-01T10:00:00Z",
             "reported_to_agency_at": "2026-08-01T21:00:00Z"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestSevereInjuryClockBoundaries:
    def test_fatality_uses_eight_hour_clock(self, api):
        """PRD §3.6: "The reporting `deadline` is computed at creation:
        exactly eight hours after `occurred_at` for a `FATALITY`, and exactly
        twenty-four hours after for the other three kinds."

        Design: Corner/calculations/severe_injury_fatality_8h_clock
        """
        _, establishment, employee = setup_org(fein="78-0000016",
                                               site_name="Site Fat")
        case = create_case(establishment["id"], employee["id"],
                           "2026-08-01T06:00:00Z", description="Fatality",
                           body_part="multiple",
                           is_severe_event="FATALITY")
        report = file_severe_report(case["id"], "FATALITY",
                                    "2026-08-01T06:00:00Z",
                                    "2026-08-01T15:00:00Z")
        assert_severe_report(report)
        assert report["deadline"].startswith("2026-08-01T14:00:00"), (
            "FATALITY deadline is occurred_at + 8 hours")
        assert report["status"] == "LATE", (
            "Reported at 15:00 against a 14:00 deadline is LATE")
        assert report["within_clock"] is False

    def test_report_exactly_at_24h_deadline_is_timely(self, api):
        """PRD §3.6: "The `within_clock` flag records whether
        `reported_to_agency_at` fell at or before the deadline — the boundary
        is inclusive and the comparison is to the second — and the report's
        `status` is fixed atomically at creation to `TIMELY` or `LATE`
        accordingly."

        Design: Difficulty/boundary_precision_check/severe_report_exactly_at_24h_deadline
        """
        _, establishment, employee = setup_org(fein="55-8889990",
                                               site_name="Lab 6")
        case = create_case(establishment["id"], employee["id"],
                           "2026-08-02T08:00:00Z",
                           description="Chemical splash hospitalized",
                           body_part="eyes", event_type="POISONING",
                           is_severe_event="INPATIENT_HOSPITALIZATION")
        resp = api.create_severe_report(
            case["id"],
            {"report_kind": "INPATIENT_HOSPITALIZATION",
             "occurred_at": "2026-08-02T08:00:00Z",
             "reported_to_agency_at": "2026-08-03T08:00:00Z"},
            OFFICER)
        report = validate_success(resp, 201)
        assert_severe_report(report)
        assert report["deadline"].startswith("2026-08-03T08:00:00")
        assert report["within_clock"] is True, (
            "Reported exactly at the 24h deadline: boundary is inclusive")
        assert report["status"] == "TIMELY"

    def test_report_one_second_past_24h_deadline_is_late(self, api):
        """PRD §3.6: "The `within_clock` flag records whether
        `reported_to_agency_at` fell at or before the deadline — the boundary
        is inclusive and the comparison is to the second — and the report's
        `status` is fixed atomically at creation to `TIMELY` or `LATE`
        accordingly."

        Design: Difficulty/boundary_precision_check/severe_report_exactly_at_24h_deadline
        """
        _, establishment, employee = setup_org(fein="55-8889991",
                                               site_name="Lab 7")
        case = create_case(establishment["id"], employee["id"],
                           "2026-08-02T08:00:00Z",
                           description="Second worker hospitalized",
                           body_part="respiratory", event_type="RESPIRATORY",
                           is_severe_event="INPATIENT_HOSPITALIZATION")
        report = file_severe_report(case["id"], "INPATIENT_HOSPITALIZATION",
                                    "2026-08-02T08:00:00Z",
                                    "2026-08-03T08:00:01Z")
        assert_severe_report(report)
        assert report["within_clock"] is False, (
            "One second past the 24h deadline misses the inclusive boundary")
        assert report["status"] == "LATE"


class TestLateReportRiskCascade:
    def test_late_severe_report_feeds_risk_score(self, api):
        """PRD §3.6: "A `LATE` filing is a compliance event in its own right.
        It recomputes the establishment's posture at creation and contributes
        ten points per late report within the trailing 365 days to the risk
        score of §2.7."
        PRD §2.7: "The score weighs five signals: 2.0 times the live TRIR for
        the logical clock's current year, plus 3.0 times the live DART rate
        for that year, plus 5.0 for each corrective action currently in
        `OVERDUE`, plus 8.0 for each citation currently in `OVERDUE`, plus
        10.0 for each severe-injury report filed `LATE` within the trailing
        365 days."
        PRD §2.7: "a score of 25.0 or higher but below 50.0 yields `WATCH`"

        Design: Corner/cross_cutting_layers/late_severe_report_feeds_risk_score
        """
        _, establishment, employee = setup_org(fein="19-0000038",
                                               site_name="LS Site")
        set_clock("2026-08-01T06:00:00Z")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-01T05:00:00Z")
        for label in ("L1", "L2", "L3"):
            create_corrective_action(establishment["id"],
                                     case_id=case["id"], description=label,
                                     assigned_to="op-l",
                                     due_date="2026-08-03")
        set_clock("2026-08-04T00:00:00Z")

        fatality = create_case(establishment["id"], employee["id"],
                               "2026-07-30T06:00:00Z", description="Fatal",
                               body_part="multiple",
                               is_severe_event="FATALITY")
        report = file_severe_report(fatality["id"], "FATALITY",
                                    "2026-07-30T06:00:00Z",
                                    "2026-07-30T20:00:00Z")
        assert report["status"] == "LATE", (
            "FATALITY deadline 2026-07-30T14:00:00Z; reported 20:00")

        est = get_establishment(establishment["id"])
        assert est["risk_score"] == pytest.approx(25.0, abs=0.01), (
            "3 overdue actions x 5.0 + 1 late report x 10.0")
        assert est["posture"] == "WATCH"
