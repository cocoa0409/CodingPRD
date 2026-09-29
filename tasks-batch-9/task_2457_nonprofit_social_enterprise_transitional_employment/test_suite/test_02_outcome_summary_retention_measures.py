"""Funder reporting: the same placement read under both retention measures."""

from test_helpers import (
    EmploymentStatus,
    RetentionMeasure,
    RetentionOutcome,
    WageVerificationStatus,
    assert_ratio,
    fixtures,
    make_funder_analyst_headers,
    validate_success,
)

WINDOW = {
    "period_start": "2026-09-01T00:00:00Z",
    "period_end": "2027-06-30T00:00:00Z",
}


def _reporting_environment(api):
    """One graduate placed on 2026-10-01, read from beyond the 180-day mark."""
    program = fixtures.placed_participant_program(api)
    fixtures.set_clock(api, "2027-04-01T00:00:00Z")
    return program


def _summary(api, business_line_id, retention_measure):
    params = dict(WINDOW)
    params["retention_measure"] = retention_measure
    return validate_success(
        api.get_outcome_summary(
            business_line_id, make_funder_analyst_headers(), params
        )
    )


class TestRetentionMeasureVariants:
    """A single active-but-unconfirmed placement scores differently per measure."""

    def test_cohort_based_scores_an_unconfirmed_placement_as_a_non_retention(self, api):
        """The cohort measure counts only a confirmed 180-day outcome.

        "Under `COHORT_BASED`, `retention_denominator` is the number of window
        placements whose `hire_date` plus 180 days falls at or before the window's
        `period_end` — that is, only placements that had a full 180-day chance
        inside the window — and `retention_numerator` is the number of those whose
        `retention_outcome` is `RETAINED_180`; a placement still `ACTIVE` but never
        confirmed at 180 days therefore scores as a non-retention."

        Design: Difficulty/dual_variant_calc/outcome_retention_cohort_vs_point_in_time_same_placement
        """
        program = _reporting_environment(api)

        summary = _summary(
            api, program["business_line"]["id"], RetentionMeasure.COHORT_BASED
        )

        assert summary["retention_measure"] == RetentionMeasure.COHORT_BASED
        assert summary["retention_denominator"] == 1
        assert summary["retention_numerator"] == 0
        assert_ratio(summary["retention_rate"], 0.0000, "retention_rate")

    def test_point_in_time_scores_the_same_placement_as_fully_retained(self, api):
        """The point-in-time measure asks only whether the job is live now.

        "Under `POINT_IN_TIME`, `retention_denominator` is all window placements
        regardless of elapsed time and `retention_numerator` is those whose
        `employment_status` is `ACTIVE` as of the logical clock's current instant."

        Design: Difficulty/dual_variant_calc/outcome_retention_cohort_vs_point_in_time_same_placement
        """
        program = _reporting_environment(api)

        summary = _summary(
            api, program["business_line"]["id"], RetentionMeasure.POINT_IN_TIME
        )

        assert summary["retention_measure"] == RetentionMeasure.POINT_IN_TIME
        assert summary["retention_denominator"] == 1
        assert summary["retention_numerator"] == 1
        assert_ratio(summary["retention_rate"], 1.0000, "retention_rate")

    def test_cohort_and_enrolment_figures_are_identical_under_both_measures(self, api):
        """Only the retention triple depends on the measure; the cohort does not.

        "The enrolled cohort is the participants of that line whose `enrolled_at`
        falls inside the window, so a re-entered participant is selected by their
        most recent enrollment; `enrolled_count` is the size of that cohort and
        `placed_count` is the number of them whose `status` is `PLACED` or
        `ALUMNI_RETAINED`."

        Design: Difficulty/dual_variant_calc/outcome_retention_cohort_vs_point_in_time_same_placement
        """
        program = _reporting_environment(api)
        line_id = program["business_line"]["id"]

        cohort = _summary(api, line_id, RetentionMeasure.COHORT_BASED)
        point_in_time = _summary(api, line_id, RetentionMeasure.POINT_IN_TIME)

        for summary in (cohort, point_in_time):
            assert summary["business_line_id"] == line_id
            assert summary["enrolled_count"] == 1
            assert summary["placed_count"] == 1
            assert_ratio(summary["placement_rate"], 1.0000, "placement_rate")
            assert summary["verified_placement_count"] == 0
            assert summary["average_wage_progression_pct"] is None

    def test_reading_the_summary_moves_nothing_on_the_placement(self, api):
        """Funder reporting is a pure read over a window.

        "**Funder reporting** is a pure read over a window."

        Design: Difficulty/dual_variant_calc/outcome_retention_cohort_vs_point_in_time_same_placement
        """
        program = _reporting_environment(api)
        line_id = program["business_line"]["id"]

        _summary(api, line_id, RetentionMeasure.COHORT_BASED)
        _summary(api, line_id, RetentionMeasure.POINT_IN_TIME)

        placement = fixtures.read_placement(api, program["placement"]["id"])
        assert placement["employment_status"] == EmploymentStatus.ACTIVE
        assert placement["retention_outcome"] == RetentionOutcome.PENDING
        assert placement["wage_verification_status"] == WageVerificationStatus.UNVERIFIED
