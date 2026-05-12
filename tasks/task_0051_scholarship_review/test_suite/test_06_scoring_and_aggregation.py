"""Score submission, rubric mismatch, over-quota, and the
trimmed/full-mean aggregation paths."""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    make_reviewer_headers,
    setup_application_under_review,
    setup_review_complete,
    submit_score_payload,
    validate_error,
    validate_paginated,
)


class TestScoreSubmission:

    def test_score_rubric_keys_must_match_exactly(self):
        """PRD §3.5: "an object whose keys must be exactly the set of
        keys of the scholarship's rubric_weights (the same set, no more
        and no fewer; any discrepancy yields ERR_SCORE_RUBRIC_MISMATCH)".

        Claim: criterion_scores with extra/missing key ->
        ERR_SCORE_RUBRIC_MISMATCH.
        """
        state = setup_application_under_review(
            rubric_weights={"core": 60, "extra": 40},
        )
        reviewer = state["reviewers"][0]
        # Wrong: only one of the two keys.
        resp = api_client.submit_score(
            state["scholarship"]["id"], state["application"]["id"],
            submit_score_payload(criterion_scores={"core": 50}),
            make_reviewer_headers(reviewer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCORE_RUBRIC_MISMATCH.value)

    def test_fourth_score_rejected_as_over_quota(self):
        """PRD §3.5: "If a fourth score submission is attempted for an
        application that already has three scores ... the request is
        rejected with ERR_SCORE_OVER_QUOTA."

        Claim: a fourth submit on an already-3-score application -> 409
        ERR_SCORE_OVER_QUOTA.
        """
        # Reach REVIEW_COMPLETE (3 scores submitted).
        state = setup_review_complete()
        # Try submitting a 4th score from one of the reviewers.
        fourth = state["reviewers"][0]
        resp = api_client.submit_score(
            state["scholarship"]["id"], state["application"]["id"],
            submit_score_payload(
                criterion_scores={"core": 50},
            ),
            make_reviewer_headers(fourth["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCORE_OVER_QUOTA.value)

    def test_third_score_triggers_auto_aggregation(self):
        """PRD §3.6: "The instant the third Score row is recorded for an
        application, the system automatically advances the application
        from UNDER_REVIEW to REVIEW_COMPLETE and computes its final
        aggregated_score_x100."

        Claim: after 3rd score, application.status == REVIEW_COMPLETE
        and aggregated_score_x100 is set.
        """
        state = setup_review_complete()
        app = state["application"]
        assert app["status"] == "REVIEW_COMPLETE"
        assert app.get("aggregated_score_x100") is not None


class TestAggregationVariants:

    def test_full_mean_when_stddev_zero(self):
        """PRD §3.6: "The full-mean variant applies in the degenerate
        case: when the standard deviation across the three scores is
        zero ... no score is flagged as an outlier and the
        aggregated_score_x100 is the round-half-up of the simple mean."

        Claim: 3 identical scores -> all is_outlier=false and
        aggregated_score_x100 = simple mean.
        # difficulty: boundary_precision_check/outlier_z_strict_inequality_on_scores
        """
        # All raw_total_x100 = 50 * 100 = 5000 when rubric={core:100}
        state = setup_review_complete(
            criterion_scores_list=[
                {"core": 50}, {"core": 50}, {"core": 50},
            ],
            rubric_weights={"core": 100},
            outlier_z_threshold_x100=200,
        )
        from test_helpers import validate_paginated
        scores, _ = validate_paginated(
            api_client.list_scores(
                state["scholarship"]["id"],
                state["application"]["id"], ADMIN,
            ),
        )
        # All three is_outlier should be false.
        for s in scores:
            assert s["is_outlier"] is False, (
                "PRD §3.6 stddev==0 path: no score is flagged as outlier"
            )
        assert state["application"]["aggregated_score_x100"] == 5000

    def test_trimmed_mean_drops_one_outlier(self):
        """PRD §3.6: "a score is marked as an outlier — its is_outlier
        flag flipped to true — when the absolute difference between its
        raw_total_x100 and the mean, multiplied by 100, is strictly
        greater than the scholarship's outlier_z_threshold_x100
        multiplied by the standard deviation".
        PRD §3.6: "The application's aggregated_score_x100 is then set
        to the arithmetic mean of the raw_total_x100 values across the
        kept set, rounded half-up to the nearest integer."

        Claim: scores (8000, 8500, 2000) with z_threshold=100 -> only
        the 2000 is trimmed; kept mean = 8250.
        # difficulty: dual_variant_calc/score_aggregation_trimmed_vs_full_mean
        """
        # rubric={core:100}, scores={core:80,85,20} -> raw_total = (8000,
        # 8500, 2000). Mean = (8000+8500+2000)/3 = 6166.667. Stddev =
        # sqrt( ((8000-6166.67)^2 + (8500-6166.67)^2 + (2000-6166.67)^2)/3 )
        # = sqrt( (1833.33^2 + 2333.33^2 + (-4166.67)^2)/3 )
        # = sqrt( (3361111.6 + 5444444.4 + 17361135.6)/3 )
        # = sqrt(8722230.5) ≈ 2953.4. With threshold_x100=100 (i.e., 1.00):
        # check |raw - mean| * 100 > threshold * stddev
        # For 2000: |2000 - 6166.67|*100 = 416667 > 100*2953.4 = 295340 yes
        # For 8000: |8000-6166.67|*100 = 183333 < 295340 -> not outlier
        # For 8500: |8500-6166.67|*100 = 233333 < 295340 -> not outlier
        # Kept mean = (8000+8500)/2 = 8250.
        state = setup_review_complete(
            criterion_scores_list=[
                {"core": 80}, {"core": 85}, {"core": 20},
            ],
            rubric_weights={"core": 100},
            outlier_z_threshold_x100=100,
        )
        assert state["application"]["aggregated_score_x100"] == 8250
        # Score with raw_total 2000 should be marked outlier.
        from test_helpers import validate_paginated
        scores, _ = validate_paginated(
            api_client.list_scores(
                state["scholarship"]["id"],
                state["application"]["id"], ADMIN,
            ),
        )
        by_raw = {s["raw_total_x100"]: s for s in scores}
        assert by_raw[2000]["is_outlier"] is True
        assert by_raw[8000]["is_outlier"] is False
        assert by_raw[8500]["is_outlier"] is False
