"""Objective.progress aggregation and roll-up (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success,
    setup_objective_with_two_active_krs,
    setup_three_level_hierarchy,
    setup_dual_variant_objective,
    post_value_change,
    self_submit_payload, manager_submit_payload, calibrate_payload,
)


# ---------------------------------------------------------------------------
# Difficulty-design: combinatorial_formula/objective_progress_round_per_kr_then_sum
# ---------------------------------------------------------------------------

class TestObjectiveProgressRoundOrder:
    """# difficulty: combinatorial_formula/objective_progress_round_per_kr_then_sum"""

    def test_round_per_kr_first_then_weighted_sum(self, api):
        """PRD §3.4: "first rounds its `score` to 4 decimal places**, multiplies that rounded score by the key result's `weight`, sums those products, and **then rounds the sum to 4 decimal places** half up".

        Claim: KR1 raw=1/3≈0.333333, KR2 raw=2/7≈0.285714, weights 0.4 and 0.6.
        - Per-KR-first: round(1/3,4)=0.3333; round(2/7,4)=0.2857; weighted sum
          = 0.3333*0.4 + 0.2857*0.6 = 0.13332 + 0.17142 = 0.30474; round(0.30474,4)=0.3047.
        - Sum-then-round (WRONG): (1/3*0.4 + 2/7*0.6) = 0.13333... + 0.17142... ≈ 0.30476...,
          round(0.30476,4)=0.3048.
        - PRD-faithful answer is 0.3047.
        # difficulty: combinatorial_formula/objective_progress_round_per_kr_then_sum
        """
        s = setup_objective_with_two_active_krs(weights=(0.4, 0.6), targets=(3, 7))
        # Update KR1 to current=1 (raw 1/3)
        post_value_change(s["kr1"]["id"], s["org"]["employee_user"]["id"], 1)
        # Update KR2 to current=2 (raw 2/7)
        post_value_change(s["kr2"]["id"], s["org"]["employee_user"]["id"], 2)
        # Read KRs and Objective
        kr1 = validate_success(api.get_key_result(s["kr1"]["id"], s["org"]["admin_headers"]))
        kr2 = validate_success(api.get_key_result(s["kr2"]["id"], s["org"]["admin_headers"]))
        obj = validate_success(api.get_objective(s["objective"]["id"], s["org"]["admin_headers"]))
        assert float(kr1["score"]) == pytest.approx(0.3333, abs=1e-6)
        assert float(kr2["score"]) == pytest.approx(0.2857, abs=1e-6)
        assert float(obj["progress"]) == pytest.approx(0.3047, abs=1e-6), \
            f"per-KR-first rounding required: expected 0.3047, got {obj['progress']}"
        # Negative — the wrong (sum-then-round) path would yield 0.3048
        assert float(obj["progress"]) != pytest.approx(0.3048, abs=1e-6)


# ---------------------------------------------------------------------------
# Difficulty-design: transitive_cascade/progress_rollup_three_levels
# ---------------------------------------------------------------------------

class TestTransitiveProgressRollup:
    """# difficulty: transitive_cascade/progress_rollup_three_levels"""

    def test_progress_update_cascades_through_three_levels(self, api):
        """PRD §3.4: "When a `ProgressUpdate` is appended to a key result, the key result's score is recomputed, the parent objective's progress is recomputed, and any objective above that one (via `parent_objective_id`) is recomputed in turn until the root is reached."

        Claim: 3-level hierarchy COMPANY > DEPARTMENT > TEAM, leaf has KR start=0 target=100 weight=1.0.
        Update leaf KR to current=50 → KR.score=0.5; leaf, parent, grandparent all roll up to 0.5000.
        # difficulty: transitive_cascade/progress_rollup_three_levels
        """
        s = setup_three_level_hierarchy()
        # Update leaf KR
        post_value_change(s["kr_l"]["id"], s["team_user"]["id"], 50)
        # Verify cascades all the way up
        admin = s["org"]["admin_headers"]
        leaf = validate_success(api.get_objective(s["leaf"]["id"], admin))
        parent = validate_success(api.get_objective(s["parent"]["id"], admin))
        grandparent = validate_success(api.get_objective(s["grandparent"]["id"], admin))
        kr = validate_success(api.get_key_result(s["kr_l"]["id"], admin))
        assert float(kr["score"]) == pytest.approx(0.5000, abs=1e-6)
        assert float(leaf["progress"]) == pytest.approx(0.5000, abs=1e-6)
        assert float(parent["progress"]) == pytest.approx(0.5000, abs=1e-6)
        assert float(grandparent["progress"]) == pytest.approx(0.5000, abs=1e-6)


# ---------------------------------------------------------------------------
# Difficulty-design: dual_variant_calc/objective_progress_provisional_vs_locked
# ---------------------------------------------------------------------------

class TestProvisionalVsLockedProgress:
    """# difficulty: dual_variant_calc/objective_progress_provisional_vs_locked"""

    def test_objective_progress_provisional_before_lock(self, api):
        """PRD §3.4: "The provisional `Objective.progress` should not be confused with the locked `Objective.final_score`. While the associated `ReviewScore` is anything other than `LOCKED`, `Objective.progress` is the live roll-up and `Objective.final_score` is null."

        Claim: KR1 score=0.5 weight=0.5; KR2 score=0.8 weight=0.5 →
        Objective.progress = 0.5*0.5 + 0.8*0.5 = 0.6500. Before lock: final_score is null.
        # difficulty: dual_variant_calc/objective_progress_provisional_vs_locked
        """
        s = setup_dual_variant_objective(self_score=0.7000, manager_score=0.6000,
                                         calibration_score=0.4500)
        # Read provisional progress (cycle is now IN_REVIEW, but progress is still live).
        obj = validate_success(api.get_objective(s["objective"]["id"], s["org"]["admin_headers"]))
        assert float(obj["progress"]) == pytest.approx(0.6500, abs=1e-6)
        assert obj.get("final_score") in (None,)

    def test_objective_final_score_locked_at_calibration(self, api):
        """PRD §3.4: "Once the review locks (per §3.7), `Objective.final_score` is snapshotted from the review's final score and **does not change** when key results are subsequently updated".
        PRD §3.7: "if `calibration_score` is non-null, `final_score` equals `calibration_score`; otherwise it equals `manager_score`".

        Claim: after self/manager/calibrate(0.45)/lock, Objective.final_score == 0.4500
        and remains DIFFERENT from Objective.progress (still 0.6500).
        # difficulty: dual_variant_calc/objective_progress_provisional_vs_locked
        """
        s = setup_dual_variant_objective(self_score=0.7000, manager_score=0.6000,
                                         calibration_score=0.4500)
        # Walk review to LOCKED
        api.self_submit_review(s["review"]["id"], self_submit_payload(0.7000),
                               s["org"]["employee_headers"])
        api.manager_submit_review(s["review"]["id"], manager_submit_payload(0.6000),
                                  s["org"]["manager_headers"])
        # Calibrate with 0.45 (delta |0.45-0.6|=0.15 > 0.05 → ok)
        api.calibrate_review(s["review"]["id"], calibrate_payload(0.4500),
                             s["org"]["hrbp_headers"])
        api.lock_review(s["review"]["id"], s["org"]["hrbp_headers"])

        obj = validate_success(api.get_objective(s["objective"]["id"], s["org"]["admin_headers"]))
        assert float(obj["progress"]) == pytest.approx(0.6500, abs=1e-6)
        assert float(obj["final_score"]) == pytest.approx(0.4500, abs=1e-6)
        # The two diverge
        assert float(obj["progress"]) != pytest.approx(float(obj["final_score"]), abs=1e-6)
