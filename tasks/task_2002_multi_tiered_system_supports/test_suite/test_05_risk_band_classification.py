"""Risk-band classification under the default cut-score rule (PRD §3.3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_screening_score,
    create_screening_window,
    define_cut_point,
    enroll_student,
    record_score,
    record_screening_score_payload,
    set_clock,
    setup_district_school,
    validate_success,
)

TEACHER = TEST_USERS["teacher_headers"]


class TestCutScoreClassification:
    def test_cut_score_bands_by_threshold_not_cohort(self, api):
        """PRD §3.3: "Under the default cut-score rule, a `raw_score` at or below
        the cut point's `tier3_max_score` bands as `TIER_3`; otherwise a
        `raw_score` at or below the `tier2_max_score` bands as `TIER_2`; anything
        higher bands as `TIER_1`."
        PRD §3.3: "The two variants consume identical inputs and can disagree on
        the same data; the cut-score variant is what the API returns and
        persists."

        The cohort is deliberately bottom-heavy (nine prior scores at or below
        80, all under tier3_max_score=90), so a percentile-norm reader would band
        the top scorer TIER_1; the persisted cut-score rule must instead band a
        raw_score of 95 (above 90, at or below 120) as TIER_2.

        Design: Difficulty/dual_variant_calc/risk_band_cut_score_vs_percentile
        """
        district, school = setup_district_school(api)
        d_id, s_id = district["id"], school["id"]
        define_cut_point(api, d_id, s_id, window_kind="FALL", grade_level=3,
                         subject="READING", tier2_max_score=120,
                         tier3_max_score=90)
        window = create_screening_window(api, d_id, s_id, window_kind="FALL",
                                         opens_on="2026-08-01",
                                         closes_on="2026-08-31")
        set_clock(api, "2026-08-10T12:00:00Z")
        # Nine low performers establish a bottom-heavy cohort.
        for i, raw in enumerate([60, 60, 62, 65, 70, 72, 75, 78, 80]):
            low = enroll_student(api, d_id, s_id, full_name=f"L{i + 1}",
                                 grade_level=3)
            record_score(api, d_id, s_id, window["id"], low["id"], raw_score=raw)
        target = enroll_student(api, d_id, s_id, full_name="X", grade_level=3)

        resp = api.record_screening_score(
            d_id, s_id, window["id"],
            record_screening_score_payload(target["id"], subject="READING",
                                           raw_score=95),
            TEACHER)
        score = validate_success(resp, 201)
        assert_screening_score(score)
        assert score["risk_band"] == "TIER_2", (
            "cut-score rule: 95 > tier3_max 90 and 95 <= tier2_max 120 -> TIER_2, "
            "regardless of the bottom-heavy cohort")

    @pytest.mark.parametrize("raw_score,expected_band", [
        (90, "TIER_3"),    # at tier3_max_score (inclusive)
        (91, "TIER_2"),    # one above tier3_max_score
        (120, "TIER_2"),   # at tier2_max_score (inclusive)
        (121, "TIER_1"),   # one above tier2_max_score
    ], ids=["at-tier3-max", "tier3-max-plus-1", "at-tier2-max",
            "tier2-max-plus-1"])
    def test_cut_score_threshold_boundaries(self, api, raw_score, expected_band):
        """PRD §3.3: "Under the default cut-score rule, a `raw_score` at or below
        the cut point's `tier3_max_score` bands as `TIER_3`; otherwise a
        `raw_score` at or below the `tier2_max_score` bands as `TIER_2`; anything
        higher bands as `TIER_1`."

        Both thresholds are inclusive ("at or below"): tier2_max=120,
        tier3_max=90.

        Design: Difficulty/dual_variant_calc/risk_band_cut_score_vs_percentile
        """
        district, school = setup_district_school(api)
        d_id, s_id = district["id"], school["id"]
        define_cut_point(api, d_id, s_id, window_kind="FALL", grade_level=3,
                         subject="READING", tier2_max_score=120,
                         tier3_max_score=90)
        window = create_screening_window(api, d_id, s_id, window_kind="FALL",
                                         opens_on="2026-08-01",
                                         closes_on="2026-08-31")
        set_clock(api, "2026-08-10T12:00:00Z")
        student = enroll_student(api, d_id, s_id, full_name="B", grade_level=3)
        resp = api.record_screening_score(
            d_id, s_id, window["id"],
            record_screening_score_payload(student["id"], subject="READING",
                                           raw_score=raw_score),
            TEACHER)
        score = validate_success(resp, 201)
        assert score["risk_band"] == expected_band, (
            f"raw_score {raw_score} with cuts 120/90 must band {expected_band}")
