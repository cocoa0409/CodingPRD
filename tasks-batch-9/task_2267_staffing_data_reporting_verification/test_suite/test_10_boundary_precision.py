"""Boundary values that the specification pins to the inclusive side."""

import pytest

from test_helpers import (
    AuditStatus,
    CensusDayStatus,
    FindingCode,
    FindingSeverity,
    FindingStatus,
    MeasureScenario,
    MeasureVariant,
    PublicationStatus,
    approx_hours,
    approx_ratio,
    build_draft_submission,
    find_finding,
    findings_with_code,
    validate_success,
)


@pytest.fixture
def tolerance_boundary_quarter(client):
    """A DRAFT quarter with one census day exactly at the five-percent variance
    tolerance and one a single resident past it, both reconciled."""
    scenario = build_draft_submission(client)
    at_tolerance = scenario.report_census("2026-04-01", 105, 100)
    past_tolerance = scenario.report_census("2026-04-02", 106, 100)
    return (
        scenario,
        scenario.reconcile_census(at_tolerance["id"]),
        scenario.reconcile_census(past_tolerance["id"]),
    )


@pytest.fixture
def five_star_boundary_quarter(client):
    """An ACCEPTED quarter engineered so the as-submitted reading lands exactly on
    the 3.6000 five-star floor with the weekend figure exactly on its own 2.4000
    floor: three 8.80-hour weekday shifts, two 4.80-hour weekend shifts, and five
    reconciled census days counting 2 residents each."""
    scenario = build_draft_submission(client)
    for work_date in ("2026-04-01", "2026-04-02", "2026-04-03"):
        scenario.capture_hours(
            work_date=work_date, shift_start="07:00", shift_end="15:48"
        )
    for work_date in ("2026-04-04", "2026-04-05"):
        scenario.capture_hours(
            work_date=work_date, shift_start="07:00", shift_end="11:48"
        )
    for day in range(1, 6):
        scenario.report_reconciled_census(f"2026-04-0{day}", 2, 2)

    scenario.validate()
    scenario.submit()
    scenario.accept()
    return scenario


class TestCensusVarianceAtTolerance:
    def test_01_a_variance_of_exactly_five_percent_reconciles(
        self, tolerance_boundary_quarter
    ):
        """PRD: "The tolerance is a relative variance of 0.0500 — five percent —
        and the comparison is made against the already-rounded `variance_pct`, with
        the boundary itself counting as agreement. A `variance_pct` of 0.0500 or
        less moves the day to `RECONCILED`; anything strictly greater moves it to
        `DISPUTED`. A facility-reported count of 105 against an MDS count of 100
        produces exactly 0.0500 and reconciles; 106 against 100 produces 0.0600 and
        disputes."

        Design: Difficulty/boundary_precision_check/census_variance_exactly_at_tolerance_reconciles
        """
        _, at_tolerance, _ = tolerance_boundary_quarter

        assert at_tolerance["variance_pct"] == approx_ratio(0.0500)
        assert at_tolerance["status"] == CensusDayStatus.RECONCILED.value

    def test_02_a_variance_one_step_past_the_tolerance_disputes(
        self, tolerance_boundary_quarter
    ):
        """PRD: "A facility-reported count of 105 against an MDS count of 100
        produces exactly 0.0500 and reconciles; 106 against 100 produces 0.0600 and
        disputes."

        Design: Difficulty/boundary_precision_check/census_variance_exactly_at_tolerance_reconciles
        """
        _, _, past_tolerance = tolerance_boundary_quarter

        assert past_tolerance["variance_pct"] == approx_ratio(0.0600)
        assert past_tolerance["status"] == CensusDayStatus.DISPUTED.value

    def test_03_only_the_disputed_day_raises_a_variance_finding(
        self, tolerance_boundary_quarter
    ):
        """PRD: "Moving to `RECONCILED` stores the recomputed `variance_pct` and
        resolves any `OPEN` finding with `code` `CENSUS_VARIANCE` whose
        `subject_ref` equals that `census_date`. Moving to `DISPUTED` stores
        `variance_pct` and creates a `ValidationFinding` with `code`
        `CENSUS_VARIANCE`, `severity` `WARNING`, `status` `OPEN`, and `subject_ref`
        equal to that `census_date`."

        Design: Difficulty/boundary_precision_check/census_variance_exactly_at_tolerance_reconciles
        """
        scenario, _, _ = tolerance_boundary_quarter

        variance_findings = findings_with_code(
            scenario.findings(), FindingCode.CENSUS_VARIANCE.value
        )
        assert len(variance_findings) == 1

        finding = variance_findings[0]
        assert finding["subject_ref"] == "2026-04-02"
        assert finding["severity"] == FindingSeverity.WARNING.value
        assert finding["status"] == FindingStatus.OPEN.value

    def test_04_the_validation_pass_counts_the_variance_among_open_warnings(
        self, tolerance_boundary_quarter
    ):
        """PRD: a successful validation run "rebuilds the finding set, refreshes
        `open_fatal_finding_count` and `open_warning_finding_count`". PRD:
        "`CENSUS_VARIANCE`, `severity` `WARNING`, one finding per census day whose
        `status` is `DISPUTED`."

        Design: Difficulty/boundary_precision_check/census_variance_exactly_at_tolerance_reconciles
        """
        scenario, _, _ = tolerance_boundary_quarter

        data = scenario.validate()

        open_warnings = [
            finding
            for finding in scenario.findings()
            if finding["severity"] == FindingSeverity.WARNING.value
            and finding["status"] == FindingStatus.OPEN.value
        ]
        assert data["open_warning_finding_count"] == len(open_warnings)
        assert find_finding(
            open_warnings, FindingCode.CENSUS_VARIANCE.value, "2026-04-02"
        )


class TestTotalNurseHprdAtFiveStarFloor:
    def test_01_the_metric_lands_exactly_on_the_five_star_tier_floor(
        self, five_star_boundary_quarter
    ):
        """PRD: "Step one is two independent tier lookups, every boundary of which
        is inclusive. `total_nurse_points` is 5 when `total_nurse_hprd` is at least
        3.6000" and "`rn_points` is 5 when `rn_hprd` is at least 0.7500". The
        quarter's 36.00 direct-care hours over 10 resident days is exactly 3.6000.

        Design: Difficulty/boundary_precision_check/total_nurse_hprd_exactly_at_five_star_tier_floor
        """
        scenario = five_star_boundary_quarter

        data = MeasureScenario(scenario).measure

        assert data["total_nurse_hprd"] == approx_ratio(3.6000)
        assert data["total_nurse_points"] == 5
        assert data["rn_hprd"] == approx_ratio(3.6000)
        assert data["rn_points"] == 5

    def test_02_a_weekend_figure_equal_to_the_floor_does_not_downgrade(
        self, five_star_boundary_quarter
    ):
        """PRD: "when `weekend_total_nurse_hprd` is null, or is strictly less than
        2.4000, the star is reduced by one but never below 1; when it is exactly
        2.4000 or greater, the star is unchanged. The floor is therefore exclusive —
        equalling it does not downgrade." PRD: "When that count reaches 4 or more,
        `staffing_rating` is forced to 1 regardless of everything computed above;
        otherwise `staffing_rating` is the star that survived step three." The two
        weekend shifts contribute 9.60 hours over 4 weekend resident days.

        Design: Difficulty/boundary_precision_check/total_nurse_hprd_exactly_at_five_star_tier_floor
        """
        scenario = five_star_boundary_quarter

        data = MeasureScenario(scenario).measure

        assert data["weekend_total_nurse_hprd"] == approx_ratio(2.4000)
        assert data["days_with_zero_rn_hours"] == 0
        assert data["staffing_rating"] == 5

    def test_03_the_new_measure_is_seeded_as_an_unaudited_provisional_reading(
        self, five_star_boundary_quarter
    ):
        """PRD: "The new `StaffingMeasure` copies `facility_id` and
        `reporting_period_id` from the source submission, sets `measure_variant` to
        `AS_SUBMITTED`, `publication_status` to `PROVISIONAL`, `audit_status` to
        `NOT_AUDITED`, `published_at` and `appeal_deadline` to null,
        `has_open_appeal` to false, and `computed_by_user_id` to the acting
        identity."

        Design: Difficulty/boundary_precision_check/total_nurse_hprd_exactly_at_five_star_tier_floor
        """
        scenario = five_star_boundary_quarter

        data = MeasureScenario(scenario).measure

        assert data["measure_variant"] == MeasureVariant.AS_SUBMITTED.value
        assert data["publication_status"] == PublicationStatus.PROVISIONAL.value
        assert data["audit_status"] == AuditStatus.NOT_AUDITED.value
        assert data["published_at"] is None
        assert data["appeal_deadline"] is None

    def test_04_the_accepted_hours_that_feed_the_boundary_are_the_stored_rollups(
        self, api, five_star_boundary_quarter
    ):
        """PRD: "`weekend_direct_care_hours` is the sum of `direct_care_hours`
        restricted to entries whose `is_weekend` is true" and "`total_resident_days`
        is the exact integer sum of `resident_count`".

        Design: Difficulty/boundary_precision_check/total_nurse_hprd_exactly_at_five_star_tier_floor
        """
        scenario = five_star_boundary_quarter

        data = validate_success(
            api.get_submission(scenario.id, scenario.universe.coord_headers)
        )
        assert data["total_direct_care_hours"] == approx_hours(36.00)
        assert data["weekend_direct_care_hours"] == approx_hours(9.60)
        assert data["total_resident_days"] == 10
