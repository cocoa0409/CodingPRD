"""Population surveys, trend classification boundaries, and colony dissolution."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_coordinator_headers,
    setup_caretaker_with_colony, create_cat, create_survey,
)


class TestPopulationTrend:
    def test_population_trend_declining(self, api):
        """PRD §2.11: "The ratio is compared unrounded against two thresholds: a
        decline of 20 percent or more — that is, a ratio of −0.20 or lower —
        classifies the colony `DECLINING`"
        Surveys 10 -> 7 give a ratio of -0.30, below the decline threshold.

        Design: Corner/calculations/population_trend_declining
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=10)
        ch = make_coordinator_headers()
        create_survey(col, headers=ch, surveyed_on="2026-05-01T00:00:00Z",
                      observed_count=10, eartipped_count=0)
        create_survey(col, headers=ch, surveyed_on="2026-08-01T00:00:00Z",
                      observed_count=7, eartipped_count=5)

        report = validate_success(api.get_population_report(col["id"], ch))
        assert report["trend"] == "DECLINING", \
            f"expected DECLINING, got {report.get('trend')}"

    def test_population_trend_boundary_flat_at_minus_19(self, api):
        """PRD §2.11: "a decline of 20 percent or more — that is, a ratio of
        −0.20 or lower — classifies the colony `DECLINING`; growth of 20 percent
        or more — a ratio of +0.20 or higher — classifies it `GROWING`; anything
        strictly between the two is `FLAT`. Both thresholds are inclusive."
        Surveys 100 -> 81 give -0.19, strictly inside the band, hence FLAT.

        Design: Corner/calculations/population_trend_boundary_flat_at_minus_19
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=100)
        ch = make_coordinator_headers()
        create_survey(col, headers=ch, surveyed_on="2026-05-01T00:00:00Z",
                      observed_count=100, eartipped_count=0)
        create_survey(col, headers=ch, surveyed_on="2026-08-01T00:00:00Z",
                      observed_count=81, eartipped_count=0)

        report = validate_success(api.get_population_report(col["id"], ch))
        assert report["trend"] == "FLAT", \
            f"-0.19 is strictly inside the inclusive thresholds; got {report.get('trend')}"

    def test_population_trend_zero_baseline_growing(self, api):
        """PRD §2.11: "A zero baseline is a pinned special case rather than an
        error: when the first survey observed zero cats, the colony is `GROWING`
        if the latest survey observed any cats at all and `FLAT` if it also
        observed zero."

        Design: Corner/calculations/population_trend_zero_baseline_growing
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        ch = make_coordinator_headers()
        create_survey(col, headers=ch, surveyed_on="2026-05-01T00:00:00Z",
                      observed_count=0, eartipped_count=0)
        create_survey(col, headers=ch, surveyed_on="2026-08-01T00:00:00Z",
                      observed_count=4, eartipped_count=0)

        report = validate_success(api.get_population_report(col["id"], ch))
        assert report["trend"] == "GROWING", \
            f"zero baseline with any later cats must be GROWING; got {report.get('trend')}"

    def test_population_report_computed_read(self, api):
        """PRD §2.11: "A colony with fewer than two surveys reports
        `INSUFFICIENT_DATA`."

        Design: Corner/endpoints/population_report_computed_read
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=3)
        ch = make_coordinator_headers()
        create_survey(col, headers=ch, surveyed_on="2026-08-01T00:00:00Z",
                      observed_count=3, eartipped_count=1)

        report = validate_success(api.get_population_report(col["id"], ch))
        assert report["trend"] == "INSUFFICIENT_DATA"


class TestSurveyConsistency:
    def test_survey_eartipped_gt_observed_rejected(self, api):
        """PRD §3.9: "Two consistency rules guard intake, each rejected with
        `ERR_SURVEY_INCONSISTENT` (HTTP 422): the ear-tipped count may not exceed
        the observed count, and the survey date may not lie in the future
        relative to the logical clock."

        Design: Corner/validations/survey_eartipped_gt_observed_rejected
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=5)
        resp = api.create_population_survey(
            col["id"],
            {"surveyed_on": "2026-08-01T00:00:00Z", "observed_count": 5,
             "eartipped_count": 6},
            make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_SURVEY_INCONSISTENT, expected_status=422)


class TestColonyDissolution:
    def test_dissolve_colony_with_resident_cats_rejected(self, api):
        """PRD §3.9: "A `ProgramCoordinator` may dissolve a colony only when every
        resident cat has reached a terminal state — `RETURNED`,
        `COLONY_STERILIZED`, `ADOPTED`, or `DECEASED`; while any resident cat
        remains in a non-terminal state the dissolution is rejected with
        `ERR_COLONY_NOT_DISSOLVABLE` (HTTP 409)."

        Design: Corner/validations/dissolve_colony_with_resident_cats_rejected
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        create_cat(col, intake_tag="DS1", approximate_age_months=24)

        resp = api.dissolve_colony(col["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_COLONY_NOT_DISSOLVABLE,
                       expected_status=409)
