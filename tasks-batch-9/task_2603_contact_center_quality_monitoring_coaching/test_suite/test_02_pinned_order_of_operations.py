"""Pinned order of operations: where the rounding happens inside a weighted
score, and where the tier is fixed inside a coaching requirement."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_agent_index,
    assert_instant,
    assert_money,
    assert_scores,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPerBehaviourRoundingBeforeSummation:
    """A scorecard of fifths-of-three contributions makes the pinned rounding
    placement visible in the second decimal."""

    def test_five_thirds_contributions_round_per_behaviour_then_sum(self, api):
        """Each 6.666... contribution rounds to 6.67 before the sum is taken.

        PRD: "First, the weighted score of an evaluation rounds **per behaviour
        before summation** and then rounds **again after renormalisation** — never
        a single rounding on an unrounded sum."
        PRD: "**Step one, per-behaviour contribution, rounded once per behaviour
        before any summation.**"

        Design: Difficulty/combinatorial_formula/combinatorial_rounding_order_per_item_then_sum_thirds_form
        """
        env = fx.thirds_form_env(api)

        evaluation = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.THIRDS_ALL_ONE),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        # 20.00 * 1/3 = 6.666... rounds to 6.67 five times over: 33.35.
        assert_scores(
            evaluation,
            weighted_score=33.35,
            raw_weighted_score=33.35,
            auto_fail_triggered=False,
            compliance_result="PASS",
        )
        # A single rounding of the unrounded sum would have produced 33.33.
        assert evaluation["weighted_score"] != pytest.approx(33.33, abs=0.001)

    def test_two_thirds_contributions_also_round_down_per_behaviour(self, api):
        """Two points out of three rounds each contribution down to 13.33.

        PRD: "For a behaviour carrying a number, the achievement fraction is that
        behaviour's points divided by its `max_points`, kept as an exact ratio and
        never rounded at this stage; the renormalised contribution is the
        behaviour's `weight_pct` multiplied by that fraction and rounded half up to
        two decimals, and the fixed-denominator contribution is identical to it."
        PRD: "Rounding is not applied once at the end; the specification pins
        *where* each rounding happens, because the pinned order changes the answer."

        Design: Difficulty/combinatorial_formula/combinatorial_rounding_order_per_item_then_sum_thirds_form
        """
        env = fx.thirds_form_env(api)
        two_out_of_three = {code: 2 for code in f.THIRDS_ALL_ONE}

        evaluation = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(two_out_of_three),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        # 20.00 * 2/3 = 13.333... rounds to 13.33 five times over: 66.65.
        assert_scores(evaluation, weighted_score=66.65, raw_weighted_score=66.65)
        assert evaluation["weighted_score"] != pytest.approx(66.67, abs=0.001)


class TestTierFixedBeforeMultiplier:
    """The coaching tier is chosen on the raw deficit and never re-chosen."""

    def test_raw_deficit_tier_survives_a_multiplier_that_crosses_the_band(self, api):
        """An adjusted deficit of 13.75 is still sized on the T2 gain of 2.00.

        PRD: "Second, a coaching tier is selected **on the raw deficit**, and that
        selection is never revisited: tier `T1` when `deficit_pct` is at most
        `5.00`, tier `T2` when it is greater than `5.00` and at most `12.00`, and
        tier `T3` when it is greater than `12.00`."
        PRD: "The evaluation order here is load-bearing: the multiplier is applied
        only *after* the tier is fixed, and even when the adjusted deficit crosses
        into the next tier's raw-deficit band, the tier is not re-selected and the
        per-session gain is not swapped."
        PRD: "Sixth and last, a compliance bump decides `escalation_tier`, and it
        is applied only after `required_session_count` is already final."

        Design: Difficulty/combinatorial_formula/combinatorial_pinned_tier_before_multiplier_coaching_sizing
        """
        env = fx.indexed_agent_env(api)
        assert_agent_index(env.agent, rolling=65.41, open_compliance_findings=1)

        plan = validate_success(
            api.create_coaching_plan(
                f.coaching_plan_payload(
                    env.agent["id"],
                    env.evaluation2["id"],
                    env.agent["version"],
                    assigned_supervisor_id="SUP-77",
                    target_score=76.41,
                ),
                fx.make_supervisor_headers(),
            ),
            201,
        )

        # 76.41 - 65.41 = 11.00 -> T2 -> 11.00 * 1.25 = 13.75 -> ceil(13.75 / 2.00) = 7.
        assert_money(plan["deficit_pct"], 11.00)
        assert plan["required_session_count"] == 7
        assert plan["escalation_tier"] == "T3"
        assert_instant(plan["due_at"], "2026-09-19T09:00:00Z")
        assert plan["status"] == "ASSIGNED"
        assert plan["completed_session_count"] == 0
        assert fx.read_agent(api, env.agent["id"])["coaching_state"] == "ACTIVE"

    def test_a_clean_agent_keeps_the_unbumped_tier_and_its_own_allowance(self, api):
        """With no standing finding the escalation tier equals the selected tier.

        PRD: "When the agent's `open_compliance_findings` is at least one,
        `escalation_tier` is the selected tier bumped one level — `T1` becomes
        `T2`, `T2` becomes `T3`, and `T3` stays `T3`; otherwise `escalation_tier`
        is the selected tier unchanged."
        PRD: "Fifth, `due_at` is the current logical-clock instant plus the tier's
        allowance: thirty days for `T1`, forty-five days for `T2`, sixty days for
        `T3`."

        Design: Difficulty/combinatorial_formula/combinatorial_pinned_tier_before_multiplier_coaching_sizing
        """
        env = fx.submitted_evaluation_env(api)
        agent = fx.read_agent(api, env.agent["id"])
        assert_agent_index(agent, rolling=82.00, open_compliance_findings=0)

        plan = validate_success(
            api.create_coaching_plan(
                f.coaching_plan_payload(
                    agent["id"], env.evaluation["id"], agent["version"], target_score=85.00
                ),
                fx.make_supervisor_headers(),
            ),
            201,
        )

        # 85.00 - 82.00 = 3.00 -> T1 -> 3.00 * 1.00 = 3.00 -> ceil(3.00 / 2.50) = 2.
        assert_money(plan["deficit_pct"], 3.00)
        assert plan["required_session_count"] == 2
        assert plan["escalation_tier"] == "T1"
        assert_instant(plan["due_at"], "2026-09-04T09:00:00Z")

    def test_a_non_positive_deficit_is_rejected_before_any_tier_is_selected(self, api):
        """The deficit is the first step of the sizing, so a zero gap stops there.

        PRD: "First, `deficit_pct` is the `target_score` minus the agent's current
        `quality_index_rolling`, rounded half up to two decimals. A `deficit_pct`
        of zero or less means there is no real gap to close, and the request is
        rejected as malformed with `ERR_INVALID_REQUEST`."

        Design: Difficulty/combinatorial_formula/combinatorial_pinned_tier_before_multiplier_coaching_sizing
        """
        env = fx.submitted_evaluation_env(api)
        agent = fx.read_agent(api, env.agent["id"])

        response = api.create_coaching_plan(
            f.coaching_plan_payload(
                agent["id"], env.evaluation["id"], agent["version"], target_score=82.00
            ),
            fx.make_supervisor_headers(),
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST.value)
        rows, meta = validate_paginated(
            api.list_coaching_plans(
                fx.make_quality_manager_headers(), {"agent_id": agent["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
