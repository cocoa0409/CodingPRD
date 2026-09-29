"""The three cascades a substantiated investigation fires at once."""

import pytest

from test_helpers import (
    AuditStatus,
    CaseStatus,
    CaseTriggerReason,
    CaseScenario,
    FacilityPosture,
    FindingCode,
    FindingSeverity,
    FindingStatus,
    MeasureScenario,
    MeasureVariant,
    PublicationStatus,
    SubmissionScenario,
    SubmissionStatus,
    TEST_DEFAULTS,
    approx_ratio,
    build_draft_submission,
    find_finding,
    validate_success,
)

RESOLUTION_NOTE = (
    "Unsupported hours confirmed; measure to be recomputed on supported hours only."
)


@pytest.fixture
def sanction_scenario(client):
    """An accepted and published 2026Q2 quarter whose 2026-04-04 weekend shift
    has no payroll support, a later VALIDATED 2026Q3 quarter for the same
    facility, and an investigation over the published measure that has already
    heard the facility once."""
    scenario = build_draft_submission(client)
    universe = scenario.universe

    supported = scenario.capture_supported_hours(
        work_date="2026-04-01",
        shift_start="07:00",
        shift_end="19:00",
        paid_hours=12.00,
        document_ref="TC-C0401",
    )
    scenario.capture_hours(
        work_date="2026-04-04", shift_start="07:00", shift_end="19:00"
    )
    scenario.report_reconciled_census("2026-04-01", 2, 2)
    scenario.report_reconciled_census("2026-04-04", 2, 2)
    scenario.verify_hours(supported["id"])

    scenario.validate()
    scenario.submit()
    scenario.accept()

    measure = MeasureScenario(scenario)
    measure.publish()

    later_period = universe.open_period(
        period_code=TEST_DEFAULTS["SECOND_PERIOD_CODE"],
        start_date=TEST_DEFAULTS["SECOND_PERIOD_START"],
        end_date=TEST_DEFAULTS["SECOND_PERIOD_END"],
        submission_deadline=TEST_DEFAULTS["SECOND_PERIOD_DEADLINE"],
        correction_window_end=TEST_DEFAULTS["SECOND_PERIOD_CORRECTION_END"],
    )
    later = SubmissionScenario(universe, reporting_period_id=later_period["id"])
    later.capture_hours(
        work_date="2026-07-01", shift_start="07:00", shift_end="15:00"
    )
    later.report_census("2026-07-01", 2, 2)
    later.validate()

    case = CaseScenario(
        scenario,
        trigger_reason=CaseTriggerReason.UNSUPPORTED_HOURS.value,
        detail="Half of the reported 2026Q2 hours have no payroll support.",
        staffing_measure_id=measure.id,
    )
    case.request_info("Provide timecards for the 2026-04-04 shift.")
    case.respond("No timecard exists for the 2026-04-04 shift.")

    return scenario, measure, later, case


class TestSubstantiationCascade:
    def test_01_substantiation_closes_the_case_after_the_facility_was_heard(
        self, sanction_scenario
    ):
        """PRD: "**Substantiation** is permitted from either `INFO_REQUESTED` or
        `UNDER_REVIEW`, but in both cases only after the facility has been heard at
        least once: the case's `facility_response_count` must be at least 1, and a
        substantiation attempted before any response is refused with
        `ERR_CASE_RESPONSE_REQUIRED`." PRD: "Substantiation records
        `substantiated_by_user_id` and the supplied `resolution_note`, moves
        `status` to `SUBSTANTIATED`".

        Design: Difficulty/transitive_cascade/substantiation_cascade_sanctions_facility_and_reverts_other_submission
        """
        _, _, _, case = sanction_scenario

        data = case.substantiate(RESOLUTION_NOTE)

        assert data["status"] == CaseStatus.SUBSTANTIATED.value
        assert data["facility_response_count"] == 1
        assert data["resolution_note"] == RESOLUTION_NOTE

    def test_02_the_first_cascade_rewrites_the_published_measure_in_place(
        self, api, sanction_scenario
    ):
        """PRD: "From `UNDER_AUDIT` it moves to `AUDIT_REVISED` when the case is
        substantiated, and that path rewrites the measure in place:
        `measure_variant` flips to `AUDIT_ADJUSTED`, `total_nurse_hprd`, `rn_hprd`,
        and `weekend_total_nurse_hprd` are recomputed under the audit-adjusted
        reading". Only the 2026-04-01 shift is `SUPPORTED`, so 12.00 hours fall
        over the 4 audited resident days and the weekend figure collapses to zero.

        Design: Difficulty/transitive_cascade/substantiation_cascade_sanctions_facility_and_reverts_other_submission
        """
        _, measure, _, case = sanction_scenario
        case.substantiate(RESOLUTION_NOTE)

        data = measure.refresh()
        assert data["audit_status"] == AuditStatus.AUDIT_REVISED.value
        assert data["measure_variant"] == MeasureVariant.AUDIT_ADJUSTED.value
        assert data["total_nurse_hprd"] == approx_ratio(3.0000)
        assert data["rn_hprd"] == approx_ratio(3.0000)
        assert data["weekend_total_nurse_hprd"] == approx_ratio(0.0000)

    def test_03_the_revised_measure_is_rerated_and_stays_published(
        self, sanction_scenario
    ):
        """PRD: "`total_nurse_points`, `rn_points`, `days_with_zero_rn_hours`, and
        `staffing_rating` are re-derived from those new figures by the same
        four-step assignment". PRD: "`publication_status` is untouched by audit
        transitions — a published measure whose rating has been revised downward
        remains published, under a new number." The revised 3.0000 scores 4 nurse
        points against 5 RN points, and the weekend floor knocks the combined star
        from 4 down to 3.

        Design: Difficulty/transitive_cascade/substantiation_cascade_sanctions_facility_and_reverts_other_submission
        """
        _, measure, _, case = sanction_scenario
        assert measure.refresh()["staffing_rating"] == 5

        case.substantiate(RESOLUTION_NOTE)

        data = measure.refresh()
        assert data["total_nurse_points"] == 4
        assert data["rn_points"] == 5
        assert data["days_with_zero_rn_hours"] == 0
        assert data["staffing_rating"] == 3
        assert data["publication_status"] == PublicationStatus.PUBLISHED.value

    def test_04_the_second_cascade_sanctions_the_facility_and_relabels_its_rating(
        self, api, sanction_scenario
    ):
        """PRD: "the facility's `posture` is re-derived, which sets it to
        `SANCTIONED` and refreshes `substantiated_case_count` and
        `open_case_count`." PRD: "`latest_staffing_rating` is the
        `staffing_rating` of the facility's `StaffingMeasure` whose
        `publication_status` is `PUBLISHED`".

        Design: Difficulty/transitive_cascade/substantiation_cascade_sanctions_facility_and_reverts_other_submission
        """
        scenario, _, _, case = sanction_scenario
        universe = scenario.universe
        case.substantiate(RESOLUTION_NOTE)

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["posture"] == FacilityPosture.SANCTIONED.value
        assert facility["substantiated_case_count"] == 1
        assert facility["open_case_count"] == 0
        assert facility["latest_staffing_rating"] == 3

    def test_05_the_third_cascade_reverts_the_other_validated_quarter(
        self, sanction_scenario
    ):
        """PRD: "every `VALIDATED` submission of that facility reverts to `DRAFT`,
        gains a `FATAL` `FACILITY_SANCTIONED` finding, and has its `version`
        incremented by one."

        Design: Difficulty/transitive_cascade/substantiation_cascade_sanctions_facility_and_reverts_other_submission
        """
        _, _, later, case = sanction_scenario
        version_before = later.refresh()["version"]

        case.substantiate(RESOLUTION_NOTE)

        data = later.refresh()
        assert data["status"] == SubmissionStatus.DRAFT.value
        assert data["open_fatal_finding_count"] == 1
        assert data["version"] == version_before + 1

        finding = find_finding(later.findings(), FindingCode.FACILITY_SANCTIONED.value)
        assert finding is not None
        assert finding["severity"] == FindingSeverity.FATAL.value
        assert finding["status"] == FindingStatus.OPEN.value

    def test_06_the_source_quarter_of_the_investigation_is_left_accepted(
        self, sanction_scenario
    ):
        """PRD: the third cascade names "every `VALIDATED` submission of that
        facility", and the ladder description likewise "reverts every `VALIDATED`
        submission of the facility back to `DRAFT` with a fatal
        `FACILITY_SANCTIONED` finding raised on each". An `ACCEPTED` quarter is not
        in that population.

        Design: Difficulty/transitive_cascade/substantiation_cascade_sanctions_facility_and_reverts_other_submission
        """
        scenario, _, _, case = sanction_scenario
        case.substantiate(RESOLUTION_NOTE)

        data = scenario.refresh()
        assert data["status"] == SubmissionStatus.ACCEPTED.value
        assert data["open_fatal_finding_count"] == 0
