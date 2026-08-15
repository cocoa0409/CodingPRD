"""Risk rubric scoring: dual variants, weighted formula, tier thresholds, ratchet.

PRD §3.2 specifies the two-stage computation (base, INITIAL vs REASSESSMENT
blend), the tier thresholds, and the IMMINENT ratchet.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    setup_case_in_intake,
    setup_case_triaged,
    setup_staff_group,
    score_case,
    validate_success,
)


class TestInitialVsReassessmentVariants:
    def test_initial_scoring_is_pure_weighted_base(self, api):
        """PRD §3.2: "An `INITIAL` scoring records `score` as exactly that base,
        rounded half-up to one decimal place."

        Design: Difficulty/dual_variant_calc/risk_scoring_initial_vs_reassessment_variants
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S1001", category="ACADEMIC_DISTRESS")
        scoring = score_case(
            ctx, ctx["case_id"], mode="INITIAL",
            harm_to_self=25, harm_to_others=17, academic_disruption=2,
            substance_involvement=0, rationale="initial",
        )
        # 4 * (0.35*25 + 0.35*17 + 0.15*2 + 0.15*0) = 4 * 15.0 = 60.0
        assert scoring["score"] == pytest.approx(60.0, abs=1e-9)
        assert scoring["tier"] == "HIGH"

    def test_reassessment_blends_previous_score(self, api):
        """PRD §3.2: "A `REASSESSMENT` blends the new base with the case's
        immediately preceding scoring: six-tenths of the new base plus
        four-tenths of the previous scoring's `score`, rounded half-up to one
        decimal place — so identical dimension inputs produce a different
        reassessment score whenever the previous score differs from the new base."

        Design: Difficulty/dual_variant_calc/risk_scoring_initial_vs_reassessment_variants
        """
        ctx = setup_staff_group()
        setup_case_triaged(ctx, external_ref="S1002", dims=(15, 0, 15, 0))
        # INITIAL: 4*(0.35*15 + 0.15*15) = 30.0 MODERATE
        assert ctx["scoring1"]["score"] == pytest.approx(30.0, abs=1e-9)
        scoring2 = score_case(
            ctx, ctx["case_id"], mode="REASSESSMENT",
            harm_to_self=25, harm_to_others=17, academic_disruption=2,
            substance_involvement=0, rationale="reassess",
        )
        # 0.6*60.0 + 0.4*30.0 = 48.0 — same dimensions as a 60.0 INITIAL.
        assert scoring2["score"] == pytest.approx(48.0, abs=1e-9)
        assert scoring2["tier"] == "MODERATE"


class TestWeightedThresholdRatchet:
    def test_imminent_initial_scoring_records_imminent_tier(self, api):
        """PRD §3.2: "The recorded `tier` derives from the score by threshold:
        a score of 80 or higher is `IMMINENT`, 60 or higher is `HIGH`, 30 or
        higher is `MODERATE`, and anything below 30 is `LOW`."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_threshold_ratchet
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S3001", category="BEHAVIORAL_THREAT")
        scoring = score_case(
            ctx, ctx["case_id"], mode="INITIAL",
            harm_to_self=25, harm_to_others=25, academic_disruption=17,
            substance_involvement=0, rationale="severe",
        )
        # 4 * (0.35*25 + 0.35*25 + 0.15*17) = 4 * 20.05 = 80.2
        assert scoring["score"] == pytest.approx(80.2, abs=1e-9)
        assert scoring["tier"] == "IMMINENT"

    def test_imminent_ratchet_floors_reassessment_at_high(self, api):
        """PRD §3.2: "One ratchet overrides the thresholds: if the case's
        `current_risk_tier` immediately before this scoring was `IMMINENT` and
        the threshold-derived tier from the new score would be `MODERATE` or
        `LOW`, the recorded tier is floored at `HIGH` — a case at the most
        severe tier cannot de-escalate below `HIGH` in a single reassessment."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_threshold_ratchet
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S3002", category="BEHAVIORAL_THREAT")
        score_case(
            ctx, ctx["case_id"], mode="INITIAL",
            harm_to_self=25, harm_to_others=25, academic_disruption=17,
            substance_involvement=0, rationale="severe",
        )
        scoring2 = score_case(
            ctx, ctx["case_id"], mode="REASSESSMENT",
            harm_to_self=0, harm_to_others=0, academic_disruption=0,
            substance_involvement=0, rationale="calmer",
        )
        # 0.6*0 + 0.4*80.2 = 32.08 -> round_half_up 32.1; threshold says
        # MODERATE (>= 30, < 60) but the ratchet floors at HIGH.
        assert scoring2["score"] == pytest.approx(32.1, abs=1e-9)
        assert scoring2["tier"] == "HIGH"
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["current_risk_score"] == pytest.approx(32.1, abs=1e-9)
        assert case["current_risk_tier"] == "HIGH"


class TestTierThresholdAt60:
    def test_score_exactly_60_maps_to_high(self, api):
        """PRD §3.2: "The recorded `tier` derives from the score by threshold:
        a score of 80 or higher is `IMMINENT`, 60 or higher is `HIGH`, 30 or
        higher is `MODERATE`, and anything below 30 is `LOW`."

        Design: Difficulty/boundary_precision_check/risk_tier_threshold_at_60
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S8001", category="ACADEMIC_DISTRESS")
        scoring = score_case(
            ctx, ctx["case_id"], mode="INITIAL",
            harm_to_self=25, harm_to_others=17, academic_disruption=2,
            substance_involvement=0, rationale="edge",
        )
        # 4 * (8.75 + 5.95 + 0.30) = 60.0 exactly — >= 60 is inclusive HIGH.
        assert scoring["score"] == pytest.approx(60.0, abs=1e-9)
        assert scoring["tier"] == "HIGH"

    def test_score_just_below_60_maps_to_moderate(self, api):
        """PRD §3.2: "The recorded `tier` derives from the score by threshold:
        a score of 80 or higher is `IMMINENT`, 60 or higher is `HIGH`, 30 or
        higher is `MODERATE`, and anything below 30 is `LOW`."

        Design: Difficulty/boundary_precision_check/risk_tier_threshold_at_60
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S8002", category="ACADEMIC_DISTRESS")
        scoring = score_case(
            ctx, ctx["case_id"], mode="INITIAL",
            harm_to_self=25, harm_to_others=16, academic_disruption=4,
            substance_involvement=0, rationale="just below",
        )
        # 4 * (8.75 + 5.60 + 0.60) = 59.8 — just below the HIGH boundary.
        assert scoring["score"] == pytest.approx(59.8, abs=1e-9)
        assert scoring["tier"] == "MODERATE"


class TestModerateBandResult:
    def test_uniform_tens_score_40_moderate(self, api):
        """PRD §3.2: "First, a raw base is formed as four times the weighted sum
        of the dimensions: `harm_to_self` contributes 35 percent of the weight,
        `harm_to_others` contributes 35 percent, `academic_disruption`
        contributes 15 percent, and `substance_involvement` contributes 15
        percent; because each dimension tops out at 25, the base runs from 0 to
        100."

        Design: Corner/calculations/risk_score_moderate_band_correct_result
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S0012", category="ACADEMIC_DISTRESS")
        scoring = score_case(
            ctx, ctx["case_id"], mode="INITIAL",
            harm_to_self=10, harm_to_others=10, academic_disruption=10,
            substance_involvement=10, rationale="uniform",
        )
        # 4 * (3.5 + 3.5 + 1.5 + 1.5) = 40.0
        assert scoring["score"] == pytest.approx(40.0, abs=1e-9)
        assert scoring["tier"] == "MODERATE"


class TestComputedCaseFieldsAfterScoring:
    def test_scoring_writes_score_tier_and_triaged_onto_case(self, api):
        """PRD §3.2: "Every completed scoring writes the computed `score` and
        `tier` back onto the case as `current_risk_score` and
        `current_risk_tier` — both null until this first write — and increments
        the case's `version`."
        PRD §3.2: "The first scoring also advances the case from `INTAKE` to
        `TRIAGED`; reassessments are a self-loop that leave the case in
        `TRIAGED`."

        Design: Corner/entities/care_case_computed_fields_after_scoring
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S0003", category="SELF_HARM_RISK")
        case_before = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case_before["status"] == "INTAKE"
        assert case_before["current_risk_score"] is None
        assert case_before["current_risk_tier"] is None
        score_case(
            ctx, ctx["case_id"], mode="INITIAL",
            harm_to_self=20, harm_to_others=20, academic_disruption=5,
            substance_involvement=5, rationale="high",
        )
        case_after = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        # 4 * (7.0 + 7.0 + 0.75 + 0.75) = 62.0
        assert case_after["current_risk_score"] == pytest.approx(62.0, abs=1e-9)
        assert case_after["current_risk_tier"] == "HIGH"
        assert case_after["status"] == "TRIAGED"
