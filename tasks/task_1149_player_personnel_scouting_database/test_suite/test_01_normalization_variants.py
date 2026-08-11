"""Cross-scout normalization variants (PRD §3.3)."""
import pytest

from test_helpers import (
    GM_HEADERS,
    api_client,
    create_director,
    create_outcome,
    create_prospect,
    create_report,
    create_scout,
    lock_report,
    make_drafted_prospect,
    submit_report,
    validate_success,
)


class TestNormalizedGradeProvisionalVsFinal:
    def test_provisional_variant_uses_season_stats(self, api):
        """PRD §3.3: "if the authoring scout's `locked_grade_mean` is null
        (in-season), the **provisional** variant uses the scout's
        `season_grade_mean` and `season_grade_stdev`". With season stats
        mean 6.00 stdev 1.00 and raw 7.00 the z-score is 1.0, mapped back as
        5.0 + 1.5*1.0 = 6.50.

        Design: Difficulty/dual_variant_calc/normalized_grade_provisional_vs_final
        """
        s1 = create_scout(
            level="AREA",
            full_name="Prov Scout",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.00,
        )
        d1 = create_director(full_name="Dir One")
        p1 = create_prospect(s1, full_name="Prospect A", position="QB", college="State U")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        submit_report(r1["id"], s1)
        locked = lock_report(r1["id"], d1)
        assert locked["normalized_grade"] == pytest.approx(6.50, abs=0.005), (
            f"provisional variant: 5.0 + 1.5*(7.00-6.00)/1.00 = 6.50, got "
            f"{locked['normalized_grade']}"
        )

    def test_final_variant_uses_locked_stats(self, api):
        """PRD §3.3: "once the scout's `locked_grade_mean` is set (offseason
        lock published), the **final** variant uses `locked_grade_mean` and
        `locked_grade_stdev`." With locked stats mean 6.00 stdev 0.75 and
        raw 7.00 the normalized grade is 5.0 + 1.5*(7.00-6.00)/0.75 = 7.00.

        Design: Difficulty/dual_variant_calc/normalized_grade_provisional_vs_final
        """
        s2 = create_scout(
            level="AREA",
            full_name="Fin Scout",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.00,
            locked_grade_mean=6.00,
            locked_grade_stdev=0.75,
        )
        d1 = create_director(full_name="Dir One")
        p2 = create_prospect(s2, full_name="Prospect B", position="QB", college="Tech")
        r2 = create_report(p2["id"], s2, raw_grade=7.00, scheme_fit=1.00)
        submit_report(r2["id"], s2)
        locked = lock_report(r2["id"], d1)
        assert locked["normalized_grade"] == pytest.approx(7.00, abs=0.005), (
            f"final variant: 5.0 + 1.5*(7.00-6.00)/0.75 = 7.00, got "
            f"{locked['normalized_grade']}"
        )

    def test_identical_raw_grade_yields_different_normalized_per_variant(self, api):
        """PRD §3.3: "Because the two statistic pairs generally differ, the
        same `raw_grade` yields a different `normalized_grade` under the two
        variants."

        Design: Difficulty/dual_variant_calc/normalized_grade_provisional_vs_final
        """
        s1 = create_scout(
            level="AREA",
            full_name="Prov Scout",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.00,
        )
        s2 = create_scout(
            level="AREA",
            full_name="Fin Scout",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.00,
            locked_grade_mean=6.00,
            locked_grade_stdev=0.75,
        )
        d1 = create_director(full_name="Dir One")
        p1 = create_prospect(s1, full_name="PA", position="QB", college="State U")
        p2 = create_prospect(s2, full_name="PB", position="QB", college="Tech")
        r1 = create_report(p1["id"], s1, raw_grade=7.00, scheme_fit=1.00)
        r2 = create_report(p2["id"], s2, raw_grade=7.00, scheme_fit=1.00)
        submit_report(r1["id"], s1)
        submit_report(r2["id"], s2)
        n1 = lock_report(r1["id"], d1)["normalized_grade"]
        n2 = lock_report(r2["id"], d1)["normalized_grade"]
        assert n1 == pytest.approx(6.50, abs=0.005)
        assert n2 == pytest.approx(7.00, abs=0.005)
        assert n1 != n2, (
            "identical raw_grade 7.00 must produce different normalized grades "
            "under provisional vs final variants"
        )


class TestScoutAccuracyRmseVsHitRate:
    def _setup_two_outcomes(self):
        """One scout; two prospects each with a LOCKED report and one outcome."""
        s1 = create_scout(
            level="AREA",
            full_name="Eval Scout",
            weight=1.0,
            season_grade_mean=6.00,
            season_grade_stdev=1.50,
        )
        d1 = create_director(full_name="Dir One")
        # p1: raw 9.00 -> z=(9-6)/1.5=2.0 -> normalized 5.0+1.5*2=8.00; outcome 90
        p1 = make_drafted_prospect(s1, d1, raw_grade=9.00, full_name="Hit Guy", position="WR", college="State U")
        # p2: raw 7.00 -> z=(7-6)/1.5=0.6667 -> normalized 5.0+1.5*0.6667=6.00; outcome 50
        p2 = make_drafted_prospect(s1, d1, raw_grade=7.00, full_name="Miss Guy", position="WR", college="Tech")
        create_outcome(p1["id"], season_year=2026, games_started=16, pro_bowl=True, outcome_percentile=90)
        create_outcome(p2["id"], season_year=2026, games_started=8, pro_bowl=False, outcome_percentile=50)
        return s1

    def test_rmse_accuracy_penalizes_magnitude(self, api):
        """PRD §3.9: "The root-mean-square of these errors is taken, and the
        accuracy is 100 minus ten times that root-mean-square, rounded half-up
        to 2 decimal places, floored at 0." Errors are -1.0 (8.00 - 90/10)
        and +1.0 (6.00 - 50/10); RMSE = 1.0, accuracy = 90.00.

        Design: Difficulty/dual_variant_calc/scout_accuracy_rmse_vs_hit_rate
        """
        s1 = self._setup_two_outcomes()
        resp = api_client.get_scout_evaluation(s1["id"], GM_HEADERS)
        data = validate_success(resp)
        assert data["evaluated_report_count"] == 2
        assert data["rmse_accuracy"] == pytest.approx(90.00, abs=0.005)

    def test_hit_rate_accuracy_binary_on_high_predictions(self, api):
        """PRD §3.9: "The predictions are the eligible reports whose
        `normalized_grade` is at least 7.00; a prediction is a hit when its
        outcome's `outcome_percentile` is at least 70." Here only the 8.00
        report predicts; its outcome 90 hits, so hit rate = 100.00.

        Design: Difficulty/dual_variant_calc/scout_accuracy_rmse_vs_hit_rate
        """
        s1 = self._setup_two_outcomes()
        resp = api_client.get_scout_evaluation(s1["id"], GM_HEADERS)
        data = validate_success(resp)
        assert data["hit_rate_accuracy"] == pytest.approx(100.00, abs=0.005)
        # The two variants genuinely measure different things; on this input
        # rmse_accuracy (90.00) != hit_rate_accuracy (100.00).
        assert data["rmse_accuracy"] != data["hit_rate_accuracy"]
