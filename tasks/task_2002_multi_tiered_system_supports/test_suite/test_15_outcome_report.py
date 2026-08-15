"""District outcome reporting by subgroup (PRD §3.9)."""
from test_helpers import (
    SUBGROUP_CODES,
    TEST_USERS,
    build_outcome_report_cohort,
    validate_success,
)

LEAD = TEST_USERS["team_lead_headers"]


class TestSubgroupOutcomeIndex:
    def test_outcome_index_with_small_cohort_penalty(self, api):
        """PRD §3.9: "For each subgroup code in `ELL`, `FRL`, `IEP`, `BLACK`,
        `HISPANIC`, `WHITE`, `ASIAN`, and `MULTI`, the cohort is every student in
        the district whose `subgroup_codes` contain that code. The at-risk subset
        is those cohort members whose latest `risk_band` in the target window is
        `TIER_2` or `TIER_3`. The moved-up subset is the at-risk members whose
        `current_tier` today is strictly lower-risk than their band — a `TIER_2`
        band now standing at `TIER_1`, or a `TIER_3` band now standing at `TIER_1`
        or `TIER_2`."
        PRD §3.9: "The raw index is the moved-up count multiplied by one hundred
        and divided by the at-risk count, with the denominator pinned at a
        minimum of one so that an empty at-risk cohort yields zero rather than an
        undefined value."
        PRD §3.9: "A small-cohort penalty then applies: when the subgroup's total
        district enrollment is fewer than thirty students, five points are
        subtracted from the raw index before any rounding."
        PRD §3.9: "The published index is the adjusted value truncated down to a
        whole number, floored at zero — penalty first, truncation second, floor
        last."
        PRD §3.9: "The report returns an object mapping each subgroup code to its
        integer index."

        Cohort shape: ELL has 35 enrolled (no penalty), 10 at-risk, 4 moved up ->
        40. BLACK has 20 enrolled (penalty 5), 5 at-risk, 3 moved up -> raw 60,
        adjusted 55. FRL has no students at all -> raw 0 against the pinned
        denominator, minus 5, floored at 0.

        Design: Corner/calculations/subgroup_outcome_index_correct_result
        """
        district, school, window = build_outcome_report_cohort(api)
        resp = api.get_outcome_report(district["id"], window["id"], LEAD)
        report = validate_success(resp, 200)
        assert isinstance(report, dict), "the report maps subgroup code -> index"
        for code in SUBGROUP_CODES:
            assert code in report, f"report must carry an index for {code}"
            assert isinstance(report[code], int)
        assert report["ELL"] == 40, (
            "4 moved up of 10 at-risk, enrollment 35 >= 30 so no penalty")
        assert report["BLACK"] == 55, (
            "3 moved up of 5 at-risk = 60, minus 5 small-cohort penalty -> 55")
        assert report["FRL"] == 0, (
            "empty at-risk cohort yields raw 0; penalty then floor keep it at 0")
