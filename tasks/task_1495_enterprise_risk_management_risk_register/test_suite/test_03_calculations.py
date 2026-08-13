"""Calculations: band edges, KRI thresholds, progress rollup, scenario scoring,
report aggregation — and the two dual-variant / combinatorial depth tests."""
import pytest

from test_helpers import (
    api_client,
    validate_success, get_success_data,
    assert_risk,
    create_category, create_risk, create_identified_risk,
    create_assessed_risk, create_residual_assessed_risk,
    create_active_control, create_active_mapping, create_proposed_mapping,
    approve_mapping, create_inherent_assessment, create_residual_assessment,
    create_active_kri, observe_kri, create_in_progress_plan,
    add_action, done_action, get_risk, get_plan, advance_clock,
    create_emerging_risk, create_report, finalize_report,
    make_risk_owner_headers, make_risk_manager_headers,
    make_control_owner_headers, make_board_reporter_headers,
    make_internal_auditor_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER, USER_CONTROL_OWNER,
    USER_BOARD_REPORTER, USER_INTERNAL_AUDITOR,
)


# ---------------------------------------------------------------------------
# Corner: calculations
# ---------------------------------------------------------------------------

class TestInherentBandEdges:
    """PRD §2.6: "a score from 1 to 4 inclusive is `LOW`, from 5 to 9 inclusive
    is `MEDIUM`, from 10 to 15 inclusive is `HIGH`, and from 16 to 25 inclusive
    is `CRITICAL`." """

    def test_score_4_is_low_edge(self):
        """PRD §2.6: "a score from 1 to 4 inclusive is `LOW`".

        Design: Corner/calculations/inherent_band_edges_low_medium_high_critical
        """
        risk = create_assessed_risk(likelihood=2, impact=2)
        assert risk["inherent_score"] == 4
        assert risk["inherent_band"] == "LOW"

    def test_score_9_is_medium_edge(self):
        """PRD §2.6: "from 5 to 9 inclusive is `MEDIUM`".

        Design: Corner/calculations/inherent_band_edges_low_medium_high_critical
        """
        risk = create_assessed_risk(likelihood=3, impact=3)
        assert risk["inherent_score"] == 9
        assert risk["inherent_band"] == "MEDIUM"

    def test_score_16_is_critical_edge(self):
        """PRD §2.6: "from 16 to 25 inclusive is `CRITICAL`".

        Design: Corner/calculations/inherent_band_edges_low_medium_high_critical
        """
        risk = create_assessed_risk(likelihood=4, impact=4)
        assert risk["inherent_score"] == 16
        assert risk["inherent_band"] == "CRITICAL"


class TestKriBelowDirection:
    """PRD §3.6: "For a `BELOW` indicator, the result is `RED_BREACH` when the
    value is strictly less than the red threshold, `AMBER_BREACH` when it is
    strictly less than the amber threshold and at least the red threshold, and
    `NORMAL` otherwise." """

    def _below_kri(self):
        cat = create_category(name="BLW")
        kri = create_active_kri(
            cat["id"], name="Coverage ratio", direction="BELOW",
            amber_threshold=40, red_threshold=20,
            min_observation_interval_days=0,
        )
        # Observations below are timestamped after the default logical clock
        # (2026-08-01T00:00:00Z); advance the clock first so they are not in
        # the future (PRD §3.6 ERR_OBSERVATION_IN_FUTURE).
        advance_clock("2026-08-02T00:00:00Z")
        return kri

    def test_below_amber_yields_amber(self):
        """PRD §3.6: "`AMBER_BREACH` when it is strictly less than the amber
        threshold and at least the red threshold".

        Design: Corner/calculations/kri_below_direction_evaluation
        """
        kri = self._below_kri()
        obs = observe_kri(kri["id"], 39, "2026-08-01T01:00:00Z")
        assert obs["resulting_breach_status"] == "AMBER_BREACH"

    def test_equal_to_red_is_not_breach_under_below(self):
        """PRD §3.6: "Breach evaluation uses strict comparisons — equality with
        a threshold is never a breach of that band." — equality with the red
        threshold is not a RED breach; per the same section's BELOW formula
        ("`AMBER_BREACH` when it is strictly less than the amber threshold and
        at least the red threshold"), value == red (and < amber) lands in the
        AMBER band, exactly as in the ABOVE twin case
        (TestKriRedThresholdStrictInequality).

        Design: Corner/calculations/kri_below_direction_evaluation
        """
        kri = self._below_kri()
        observe_kri(kri["id"], 39, "2026-08-01T01:00:00Z")
        obs = observe_kri(kri["id"], 20, "2026-08-01T02:00:00Z")
        assert obs["resulting_breach_status"] == "AMBER_BREACH"

    def test_below_red_yields_red(self):
        """PRD §3.6: "`RED_BREACH` when the value is strictly less than the
        red threshold".

        Design: Corner/calculations/kri_below_direction_evaluation
        """
        kri = self._below_kri()
        observe_kri(kri["id"], 39, "2026-08-01T01:00:00Z")
        observe_kri(kri["id"], 20, "2026-08-01T02:00:00Z")
        obs = observe_kri(kri["id"], 19, "2026-08-01T03:00:00Z")
        assert obs["resulting_breach_status"] == "RED_BREACH"


class TestTreatmentProgressRollup:
    """PRD §3.5: "`progress_pct`: one hundred multiplied by the number of
    `DONE` actions divided by the total number of actions, rounded half-up to
    two decimal places — and exactly 0.00 when the plan has no actions at all." """

    def test_zero_actions_yields_zero(self):
        """PRD §3.5: "exactly 0.00 when the plan has no actions at all".

        Design: Corner/calculations/treatment_progress_rollup_two_of_three
        """
        risk = create_residual_assessed_risk(treatment_budget_cents=500_000)
        plan = create_in_progress_plan(risk["id"], budget_cents=100_000)
        got = get_plan(plan["id"])
        assert got["progress_pct"] == pytest.approx(0.00)

    def test_two_of_three_is_66_67(self):
        """PRD §3.5: "`progress_pct`: one hundred multiplied by the number of
        `DONE` actions divided by the total number of actions, rounded half-up
        to two decimal places".

        Design: Corner/calculations/treatment_progress_rollup_two_of_three
        """
        risk = create_residual_assessed_risk(treatment_budget_cents=500_000)
        plan = create_in_progress_plan(risk["id"], budget_cents=100_000)
        a1 = add_action(plan["id"], "a1")
        a2 = add_action(plan["id"], "a2")
        add_action(plan["id"], "a3")
        done_action(a1["id"])
        done_action(a2["id"])
        got = get_plan(plan["id"])
        assert got["progress_pct"] == pytest.approx(66.67, abs=0.01)


class TestEmergingScenarioScoring:
    """PRD §3.7: "Registration computes the `scenario_score`: severity
    multiplied by probability multiplied by the stress factor, rounded half-up
    to a whole number." """

    def test_default_stress_factor_one(self):
        """PRD §3.7: "an optional `stress_factor` multiplier between 0.5 and
        3.0 inclusive, defaulting to 1.0".

        Design: Corner/calculations/emerging_scenario_score_with_stress_multiplier
        """
        cat = create_category(name="ES")
        er = create_emerging_risk(
            cat["id"], title="E1", scenario_severity=4, scenario_probability=3,
        )
        assert er["scenario_score"] == 12

    def test_stress_factor_lifts_score(self):
        """PRD §3.7: "Registration computes the `scenario_score`: severity
        multiplied by probability multiplied by the stress factor, rounded
        half-up to a whole number."

        Design: Corner/calculations/emerging_scenario_score_with_stress_multiplier
        """
        cat = create_category(name="ES")
        er = create_emerging_risk(
            cat["id"], title="E2", scenario_severity=4, scenario_probability=3,
            stress_factor=1.5,
        )
        assert er["scenario_score"] == 18


class TestReportEmptyRegister:
    def test_draft_risks_excluded_from_aggregation(self):
        """PRD §3.8: "Included risks are exactly those in `ASSESSED`,
        `TREATMENT`, `MONITORING`, or `REASSESSMENT`; `DRAFT`, `IDENTIFIED`,
        and `CLOSED` risks are excluded".

        Design: Corner/calculations/report_empty_register_aggregation_zero
        """
        cat = create_category(name="ER0")
        create_risk(cat["id"], title="DraftOnly")  # stays DRAFT
        rep = create_report(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            variant="FINAL",
        )
        assert rep["heat_score_total"] == pytest.approx(0.0, abs=0.001)
        assert rep["category_breakdown"] == []
        # band_counts tally included risks per band; with none included all are 0
        for band in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            assert rep["band_counts"].get(band, 0) == 0


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc
# ---------------------------------------------------------------------------

class TestInherentVsResidualDivergence:
    """Two tests for the same instance: same register yields divergent
    inherent and residual views (PRD §3.3)."""

    def _build_divergent_risk(self):
        """Risk with inherent 20 (L4×I5), two ACTIVE mappings contributing
        0.40 and 0.30; RESIDUAL assessed."""
        cat = create_category(name="Operational")
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
            treatment_budget_cents=100_000,
        )
        k1 = create_active_control(name="Dual sourcing", effectiveness_pct=0.8)
        k2 = create_active_control(name="Supplier audits", effectiveness_pct=0.6)
        m1 = create_active_mapping(risk["id"], k1["id"], coverage_weight=0.5)
        m2 = create_active_mapping(risk["id"], k2["id"], coverage_weight=0.5)
        residual_assessment = create_residual_assessment(risk["id"])
        return risk["id"], residual_assessment["id"]

    def test_inherent_view_and_residual_view_diverge_on_risk(self):
        """PRD §3.3: "Because each further control discounts only what earlier
        controls left, the post-control residual view diverges from the
        pre-control inherent view whenever at least one `ACTIVE` mapping
        exists."
        PRD §3.3: "Each qualifying mapping contributes the product of its
        control's `effectiveness_pct` and the mapping's `coverage_weight`."

        Design: Difficulty/dual_variant_calc/inherent_vs_residual_scoring_divergence_on_risk
        """
        risk_id, _ = self._build_divergent_risk()
        risk = get_risk(risk_id)
        # inherent: 4*5 = 20 → CRITICAL (16..25)
        assert risk["inherent_score"] == 20
        assert risk["inherent_band"] == "CRITICAL"
        # residual: contributions 0.40, 0.30 → discount 0.58 → ceil(20*0.42) = 9
        assert risk["residual_score"] == 9
        assert risk["residual_band"] == "MEDIUM"

    def test_residual_assessment_snapshots_both_scores(self):
        """PRD §3.2: "`inherent_score` is captured for both kinds, while
        `residual_score` is captured only for a `RESIDUAL` assessment."

        Design: Difficulty/dual_variant_calc/inherent_vs_residual_scoring_divergence_on_risk
        """
        risk_id, residual_assessment_id = self._build_divergent_risk()
        assessments_res = api_client.list_assessments(
            risk_id, make_risk_owner_headers(USER_RISK_OWNER),
        )
        assessments = validate_success(assessments_res, 200)
        by_id = {a["id"]: a for a in assessments}
        snap = by_id[residual_assessment_id]
        assert snap["kind"] == "RESIDUAL"
        assert snap["inherent_score"] == 20
        assert snap["residual_score"] == 9


class TestReportProvisionalVsFinalDivergence:
    """Difficulty instance: same register, PROVISIONAL uses inherent while
    FINAL uses residual; the two variants diverge."""

    def _build_register(self):
        """Categories CA (weight 1.5) and CB (weight 0.8);
        A1 in CA inherent 20 with residual 9 (two mappings);
        A2 in CA inherent 12 no mappings;
        B1 in CB inherent 10 with residual 7 (one mapping)."""
        cat_a = create_category(name="Strategic", weight_factor=1.5)
        cat_b = create_category(name="Financial", weight_factor=0.8)

        # A1: inherent 20 (L4 I5), residual 9 via contributions 0.40 + 0.30
        a1 = create_assessed_risk(
            category_id=cat_a["id"], likelihood=4, impact=5, title="A1",
        )
        ka1 = create_active_control(name="K-A1a", effectiveness_pct=0.8)
        ka2 = create_active_control(name="K-A1b", effectiveness_pct=0.6)
        create_active_mapping(a1["id"], ka1["id"], coverage_weight=0.5)
        create_active_mapping(a1["id"], ka2["id"], coverage_weight=0.5)
        create_residual_assessment(a1["id"])

        # A2: inherent 12 (L3 I4), no mappings, residual = 12
        a2 = create_assessed_risk(
            category_id=cat_a["id"], likelihood=3, impact=4, title="A2",
        )
        create_residual_assessment(a2["id"])

        # B1: inherent 10 (L2 I5), one mapping contribution 0.30 →
        # discount 0.30 → ceil(10*0.70) = 7
        b1 = create_assessed_risk(
            category_id=cat_b["id"], likelihood=2, impact=5, title="B1",
        )
        kb1 = create_active_control(name="K-B1", effectiveness_pct=0.5)
        create_active_mapping(b1["id"], kb1["id"], coverage_weight=0.6)
        create_residual_assessment(b1["id"])

        return cat_a, cat_b

    def test_provisional_total_uses_inherent_metric(self):
        """PRD §3.8: "a `PROVISIONAL` report uses each risk's `inherent_score`".
        PRD §3.8: "the metric values of the category's included risks are
        summed, the sum is multiplied by the category's `weight_factor`, and
        the product is rounded half-up to two decimal places".

        Design: Difficulty/dual_variant_calc/report_provisional_vs_final_aggregation_divergence
        """
        self._build_register()
        rep = create_report(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            variant="PROVISIONAL",
        )
        finalize_report(rep["id"])
        final = validate_success(
            api_client.get_report(
                rep["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
            ), 200,
        )
        # CA: (20+12)*1.5 = 48.0; CB: 10*0.8 = 8.0; total 56.00
        assert final["heat_score_total"] == pytest.approx(56.00, abs=0.01)

    def test_final_total_uses_residual_metric_with_fallback(self):
        """PRD §3.8: "a `FINAL` report uses each risk's `residual_score`,
        falling back to `inherent_score` when the residual is null".
        PRD §3.8: "Because the two variants read different metrics, identical
        register data yields a different `heat_score_total` for the two
        variants whenever any mapped control is discounting a risk."

        Design: Difficulty/dual_variant_calc/report_provisional_vs_final_aggregation_divergence
        """
        cat_a, cat_b = self._build_register()
        rep = create_report(
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-09-30T00:00:00Z",
            variant="FINAL",
        )
        finalize_report(rep["id"])
        final = validate_success(
            api_client.get_report(
                rep["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
            ), 200,
        )
        # CA: (9+12)*1.5 = 31.5; CB: 7*0.8 = 5.6; total 37.10
        assert final["heat_score_total"] == pytest.approx(37.10, abs=0.01)
        # Category breakdown: CA risk_count 2 heat 31.50; CB risk_count 1 heat 5.60
        breakdown = {entry["category_id"]: entry for entry in final["category_breakdown"]}
        assert breakdown[cat_a["id"]]["risk_count"] == 2
        assert breakdown[cat_a["id"]]["heat_score"] == pytest.approx(31.50, abs=0.01)
        assert breakdown[cat_b["id"]]["risk_count"] == 1
        assert breakdown[cat_b["id"]]["heat_score"] == pytest.approx(5.60, abs=0.01)


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula
# ---------------------------------------------------------------------------

class TestResidualDiminishingReturns:
    """Mode (a) non-linear multi-input formula. PRD §3.3."""

    def test_diminishing_returns_yields_residual_9(self):
        """PRD §3.3: "Starting from an accumulated discount of zero, each
        contribution in turn discounts only the still-undiscounted remainder:
        the accumulated discount grows by the contribution multiplied by one
        minus the accumulated discount so far."

        Design: Difficulty/combinatorial_formula/residual_discount_diminishing_returns_mode_a
        """
        cat = create_category(name="Technology")
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
        )
        k1 = create_active_control(name="K1", effectiveness_pct=0.8)
        k2 = create_active_control(name="K2", effectiveness_pct=0.6)
        create_active_mapping(risk["id"], k1["id"], coverage_weight=0.5)
        create_active_mapping(risk["id"], k2["id"], coverage_weight=0.5)
        create_residual_assessment(risk["id"])
        risk_after = get_risk(risk["id"])
        # contributions sorted desc: 0.40, 0.30
        # discount = 0.40 + 0.30*(1-0.40) = 0.40 + 0.18 = 0.58
        # residual = ceil(20 * 0.42) = ceil(8.4) = 9
        assert risk_after["residual_score"] == 9

    def test_residual_differs_from_naive_additive(self):
        """PRD §3.3: "Each qualifying mapping contributes the product of its
        control's `effectiveness_pct` and the mapping's `coverage_weight`. The
        contributions are applied in descending order, largest first".
        A naive additive sum 0.40+0.30=0.70 → ceil(20*0.30)=6 is NOT what the
        PRD's sequential rule produces (0.58 → 9).

        Design: Difficulty/combinatorial_formula/residual_discount_diminishing_returns_mode_a
        """
        cat = create_category(name="Technology")
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
        )
        k1 = create_active_control(name="K1", effectiveness_pct=0.8)
        k2 = create_active_control(name="K2", effectiveness_pct=0.6)
        create_active_mapping(risk["id"], k1["id"], coverage_weight=0.5)
        create_active_mapping(risk["id"], k2["id"], coverage_weight=0.5)
        create_residual_assessment(risk["id"])
        risk_after = get_risk(risk["id"])
        assert risk_after["residual_score"] == 9
        assert risk_after["residual_score"] != 6  # naive additive is wrong


class TestPerCategoryRoundingOrder:
    """Mode (b) nested rounding — per-category rounding happens BEFORE the
    total sum (PRD §3.8)."""

    def _build_two_categories(self):
        """Two categories weight 1.005, each with one ASSESSED risk with
        inherent=1, RESIDUAL assessed (residual=1, no mappings)."""
        cw1 = create_category(name="CW1", weight_factor=1.005)
        cw2 = create_category(name="CW2", weight_factor=1.005)
        r1 = create_assessed_risk(category_id=cw1["id"],
                                    likelihood=1, impact=1, title="W1")
        create_residual_assessment(r1["id"])
        r2 = create_assessed_risk(category_id=cw2["id"],
                                    likelihood=1, impact=1, title="W2")
        create_residual_assessment(r2["id"])
        return cw1, cw2

    def test_per_category_rounding_then_sum_yields_2_02(self):
        """PRD §3.8: "the product is rounded half-up to two decimal places to
        form that category's heat score — the per-category rounding happens
        first, before any summation across categories. The `heat_score_total`
        is then the sum of those already-rounded per-category heat scores,
        itself rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/report_heat_per_category_rounding_order_mode_b
        """
        self._build_two_categories()
        rep = create_report(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            variant="FINAL",
        )
        finalize_report(rep["id"])
        final = validate_success(
            api_client.get_report(
                rep["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
            ), 200,
        )
        # Per-category: 1 * 1.005 = 1.005 → round_half_up 2dp = 1.01
        # Sum: 1.01 + 1.01 = 2.02 (sum-then-round would give 2.01)
        assert final["heat_score_total"] == pytest.approx(2.02, abs=0.001)

    def test_per_category_heat_scores_and_band_counts(self):
        """PRD §3.8: "The `category_breakdown` is a list with one object per
        contributing category carrying its `category_id`, its `risk_count` of
        included risks, and its `heat_score`".
        PRD §3.8: "The `band_counts` tally the included risks per band —
        `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`".

        Design: Difficulty/combinatorial_formula/report_heat_per_category_rounding_order_mode_b
        """
        cw1, cw2 = self._build_two_categories()
        rep = create_report(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            variant="FINAL",
        )
        finalize_report(rep["id"])
        final = validate_success(
            api_client.get_report(
                rep["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
            ), 200,
        )
        breakdown = {e["category_id"]: e for e in final["category_breakdown"]}
        assert breakdown[cw1["id"]]["heat_score"] == pytest.approx(1.01, abs=0.001)
        assert breakdown[cw2["id"]]["heat_score"] == pytest.approx(1.01, abs=0.001)
        assert final["band_counts"]["LOW"] == 2
