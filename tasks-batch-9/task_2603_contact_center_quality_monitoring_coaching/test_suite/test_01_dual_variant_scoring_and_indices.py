"""Two-variant arithmetic: the two weighted-score readings of one evaluation,
and the two quality indices of one agent."""
import pytest

from test_helpers import (
    assert_agent_index,
    assert_money,
    assert_parallel_state,
    assert_scores,
    assert_summary_figures,
    factories as f,
    fixtures as fx,
    validate_success,
)


class TestEvaluationScoreVariants:
    """The renormalised and fixed-denominator readings of one submit."""

    def test_not_applicable_behaviour_splits_the_two_score_variants(self, api):
        """A single submit produces two divergent figures when one behaviour is "NA".

        PRD: "For a behaviour marked `"NA"`, the renormalised contribution is
        *excluded* from the calculation entirely, while the fixed-denominator
        contribution is that behaviour's whole `weight_pct` rounded half up to two
        decimals — under the fixed-denominator reading a not-applicable behaviour
        earns full credit."
        PRD: "`weighted_score` is the sum of the non-excluded renormalised
        contributions, multiplied by one hundred, divided by that applicable
        weight, and rounded half up to two decimals."
        PRD: "`raw_weighted_score` is the sum of the fixed-denominator
        contributions across **all** behaviours, rounded half up to two decimals —
        its denominator is always `100.00`."

        Design: Difficulty/dual_variant_calc/dual_variant_evaluation_na_renormalized_vs_fixed_denominator
        """
        env = fx.draft_evaluation_env(api, mix=f.source_mix(50, 25, 25))

        response = api.submit_evaluation(
            env.evaluation["id"],
            f.submit_payload(f.NA_ITEM_SCORES),
            fx.make_evaluator_headers(env.evaluator["id"]),
        )
        evaluation = validate_success(response)

        # DISCLOSE 30.00 + GREET 16.00 + RESOLVE 21.00 = 67.00 over an applicable
        # weight of 85.00; SURVEY is excluded from the renormalised reading.
        assert_scores(
            evaluation,
            weighted_score=78.82,
            raw_weighted_score=82.00,
            auto_fail_triggered=False,
            compliance_result="PASS",
        )
        assert evaluation["weighted_score"] != evaluation["raw_weighted_score"]
        assert_money(
            round(evaluation["raw_weighted_score"] - evaluation["weighted_score"], 2), 3.18
        )
        assert_parallel_state(evaluation, "SUBMITTED", "PENDING")
        assert fx.read_selection(api, env.selection["id"])["status"] == "EVALUATED"

    def test_scoring_every_behaviour_numerically_collapses_the_two_variants(self, api):
        """With no behaviour marked "NA" the two readings agree exactly.

        PRD: "For the same submitted `item_scores`, the two figures diverge
        whenever at least one behaviour was marked not applicable, because the
        renormalised figure scales the surviving weight back up to one hundred
        while the fixed-denominator figure hands the absent behaviour full
        credit."
        PRD: "For a behaviour carrying a number, the achievement fraction is that
        behaviour's points divided by its `max_points`, kept as an exact ratio and
        never rounded at this stage; the renormalised contribution is the
        behaviour's `weight_pct` multiplied by that fraction and rounded half up to
        two decimals, and the fixed-denominator contribution is identical to it."

        Design: Difficulty/dual_variant_calc/dual_variant_evaluation_na_renormalized_vs_fixed_denominator
        """
        env = fx.draft_evaluation_env(api, mix=f.source_mix(50, 25, 25))

        response = api.submit_evaluation(
            env.evaluation["id"],
            f.submit_payload(f.PASSING_ITEM_SCORES),
            fx.make_evaluator_headers(env.evaluator["id"]),
        )
        evaluation = validate_success(response)

        # 30.00 + 16.00 + 21.00 + 15.00 = 82.00 with the full 100.00 applicable.
        assert_scores(
            evaluation,
            weighted_score=82.00,
            raw_weighted_score=82.00,
            auto_fail_triggered=False,
            compliance_result="PASS",
        )
        assert evaluation["weighted_score"] == evaluation["raw_weighted_score"]
        assert_parallel_state(evaluation, "SUBMITTED", "PENDING")

    def test_submitting_releases_the_selection_and_the_evaluator_capacity(self, api):
        """The ordered side effects of a submit reach the selection and the ledger.

        PRD: "**Step three:** the underlying selection moves `ASSIGNED →
        EVALUATED` and the evaluator's `open_assignment_count` is recomputed
        downward, releasing capacity."
        PRD: "**Step two:** `review_status` becomes `SUBMITTED` and `submitted_at`
        takes the current logical-clock instant; `feedback_status` is untouched and
        stays `PENDING`."

        Design: Difficulty/dual_variant_calc/dual_variant_evaluation_na_renormalized_vs_fixed_denominator
        """
        env = fx.draft_evaluation_env(api, mix=f.source_mix(50, 25, 25))
        assert fx.read_evaluator(api, env.evaluator["id"])["open_assignment_count"] == 1

        evaluation = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.NA_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        assert evaluation["submitted_at"] is not None
        assert_parallel_state(evaluation, "SUBMITTED", "PENDING")
        assert fx.read_selection(api, env.selection["id"])["status"] == "EVALUATED"
        assert fx.read_evaluator(api, env.evaluator["id"])["open_assignment_count"] == 0


class TestAgentIndexVariants:
    """The rolling and duration-weighted readings of the same population."""

    @staticmethod
    def _second_long_poor_contact(api, env):
        """A half-hour contact of the same agent, scored 52.00 by auto-fail."""
        interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T14:00:00Z",
            ended_at="2026-08-04T14:30:00Z",
            csat_score=2,
            repeat_contact_within_72h=True,
        )
        selection2 = fx.create_selection(api, env.plan["id"], interaction2["id"], "RANDOM")
        selection2 = fx.assign_selection(
            api,
            selection2["id"],
            env.evaluator["id"],
            review_window_start="2026-08-05T11:00:00Z",
            review_window_end="2026-08-05T13:00:00Z",
        )
        evaluation2 = fx.open_evaluation(api, selection2["id"], env.evaluator["id"])
        return interaction2, selection2, evaluation2

    def test_rolling_and_period_indices_disagree_on_the_same_two_evaluations(self, api):
        """Duration weighting drags the period index below the rolling mean.

        PRD: "`quality_index_rolling` is the unweighted mean of the four most
        recent effective scores."
        PRD: "`quality_index_period` is the duration-weighted mean over the open
        monitoring period, so long contacts dominate it."
        PRD: "Because of the weighting the two indices legitimately disagree: two
        evaluations scoring `78.82` over a ten-minute contact and `52.00` over a
        half-hour contact read `58.71` on the duration-weighted index while reading
        `65.41` on the rolling one."

        Design: Difficulty/dual_variant_calc/dual_variant_agent_index_rolling_vs_duration_weighted
        """
        env = fx.submitted_evaluation_env(
            api, item_scores=f.NA_ITEM_SCORES, mix=f.source_mix(50, 25, 25)
        )
        _, _, evaluation2 = self._second_long_poor_contact(api, env)

        second = validate_success(
            api.submit_evaluation(
                evaluation2["id"],
                f.submit_payload(f.AUTO_FAIL_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )
        assert_scores(second, weighted_score=52.00, auto_fail_triggered=True)

        agent = fx.read_agent(api, env.agent["id"])
        assert_agent_index(agent, rolling=65.41, period=58.71)
        assert agent["quality_index_rolling"] != agent["quality_index_period"]

    def test_quality_summary_reports_both_index_variants_and_the_population_size(self, api):
        """The computed read republishes both indices over the same population.

        PRD: "It reports `quality_index_rolling` and `quality_index_period` as
        defined above, alongside five correlation figures computed over the same
        evaluation population, each evaluation paired with the interaction reached
        through its selection."
        PRD: "`evaluations_considered` is the size of that population."

        Design: Difficulty/dual_variant_calc/dual_variant_agent_index_rolling_vs_duration_weighted
        """
        env = fx.submitted_evaluation_env(
            api, item_scores=f.NA_ITEM_SCORES, mix=f.source_mix(50, 25, 25)
        )
        _, _, evaluation2 = self._second_long_poor_contact(api, env)
        fx.submit_evaluation(
            api, evaluation2["id"], env.evaluator["id"], f.AUTO_FAIL_ITEM_SCORES
        )

        summary = validate_success(
            api.get_quality_summary(env.agent["id"], fx.make_quality_manager_headers())
        )

        assert_summary_figures(
            summary, rolling=65.41, period=58.71, evaluations_considered=2
        )

    def test_a_single_contact_leaves_the_two_index_variants_equal(self, api):
        """With one contact in the period the weighting has nothing to bite on.

        PRD: "the window is the first four rows, or every row when there are fewer
        than four; and the index is the sum of the window's effective scores divided
        by the number of rows in the window, rounded half up to two decimals."
        PRD: "Otherwise it is the sum, over the subset, of each evaluation's
        effective score multiplied by its interaction's `duration_seconds`, divided
        by the total `duration_seconds` of the subset, rounded half up to two
        decimals."

        Design: Difficulty/dual_variant_calc/dual_variant_agent_index_rolling_vs_duration_weighted
        """
        env = fx.submitted_evaluation_env(
            api, item_scores=f.NA_ITEM_SCORES, mix=f.source_mix(50, 25, 25)
        )

        agent = fx.read_agent(api, env.agent["id"])

        assert_agent_index(agent, rolling=78.82, period=78.82)
        assert agent["quality_index_rolling"] == agent["quality_index_period"]
