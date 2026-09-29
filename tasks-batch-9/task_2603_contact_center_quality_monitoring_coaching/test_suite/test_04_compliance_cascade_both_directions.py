"""The compliance chain in both directions: a failing submission builds it
across four entities, and an upheld dispute unwinds it into a fifth."""
from typing import Any, Dict

from test_helpers import (
    assert_agent_index,
    assert_attainment,
    assert_evaluator_load,
    assert_instant,
    assert_money,
    assert_parallel_state,
    assert_plan_counters,
    assert_quota_identity,
    assert_scores,
    factories as f,
    fixtures as fx,
    validate_success,
)

#: The plan shape the cascade reserves against: four contacts per agent split
#: fifty / twenty-five / twenty-five across the three sources.
PLAN_KWARGS: Dict[str, Any] = {"per_agent_target_volume": 4, "mix": f.source_mix()}


def _failing_submission_env(api):
    """A DRAFT evaluation about to be scored into a compliance failure."""
    return fx.draft_evaluation_env(api, **PLAN_KWARGS)


class TestFailingSubmitBuildsTheChain:
    """One scoring request moves an evaluation, an interaction, an agent, a
    selection and a sampling plan."""

    def test_the_failing_score_runs_all_four_hops_in_one_request(self, api):
        """Verdict, hold, finding and reservation all land on the same submit.

        PRD: "**Step five, hop one:** when `compliance_result` is `FAIL`, the
        interaction's `compliance_hold` is set to `true`."
        PRD: "**Step six, hop two:** precisely because `compliance_hold` moved from
        `false` to `true`, the agent's `open_compliance_findings` is recomputed one
        higher — it is always the count of that agent's interactions carrying
        `compliance_hold` — and the agent's `coaching_state` becomes `REQUIRED`
        when it had been `NONE` or `CLEARED`."
        PRD: "**Step seven, hop three:** precisely because `coaching_state` moved to
        `REQUIRED`, the reservation-target plan grants that agent one extra targeted
        follow-up slot: the agent's entry in `targeted_reserve_by_agent` is
        increased by one, and `targeted_reserved_count` and
        `agent_volume_attainment` are recomputed."

        Design: Difficulty/transitive_cascade/cascade_submit_autofail_reserves_targeted_sampling_slot
        """
        env = _failing_submission_env(api)

        evaluation = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.AUTO_FAIL_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        # Hop zero: the compliance-critical contribution is zeroed, leaving
        # 16.00 + 21.00 + 15.00 over an unreduced denominator of 100.00.
        assert_scores(
            evaluation,
            weighted_score=52.00,
            raw_weighted_score=52.00,
            auto_fail_triggered=True,
            compliance_result="FAIL",
        )
        # Hop one.
        assert fx.read_interaction(api, env.interaction["id"])["compliance_hold"] is True
        # Hop two.
        agent = fx.read_agent(api, env.agent["id"])
        assert_agent_index(
            agent,
            rolling=52.00,
            open_compliance_findings=1,
            consecutive_passing_evaluations=0,
        )
        assert agent["coaching_state"] == "REQUIRED"
        # Hop three.
        plan = fx.read_plan(api, env.plan["id"])
        assert plan["targeted_reserve_by_agent"] == {env.agent["id"]: 1}
        assert_plan_counters(
            plan, selections_count=1, excluded_count=0, targeted_reserved_count=1
        )
        assert_attainment(
            plan,
            env.agent["id"],
            consumed=1,
            remaining=4,
            by_source={"RANDOM": 1, "TARGETED": 0, "CUSTOMER_FLAGGED": 0},
        )
        assert_quota_identity(plan, env.agent["id"])
        assert fx.read_selection(api, env.selection["id"])["status"] == "EVALUATED"
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 0)

    def test_every_entity_on_the_chain_takes_exactly_one_version_bump(self, api):
        """Five rows move, and none of them moves twice.

        PRD: "A successful submit increments the `version` of the evaluation, the
        selection, the agent and the interaction, and — when hop three fired — of
        the reservation-target plan as well."

        Design: Difficulty/transitive_cascade/cascade_submit_autofail_reserves_targeted_sampling_slot
        """
        env = _failing_submission_env(api)
        before = {
            "evaluation": env.evaluation["version"],
            "selection": fx.read_selection(api, env.selection["id"])["version"],
            "agent": fx.read_agent(api, env.agent["id"])["version"],
            "interaction": fx.read_interaction(api, env.interaction["id"])["version"],
            "plan": fx.read_plan(api, env.plan["id"])["version"],
        }

        evaluation = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.AUTO_FAIL_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        assert evaluation["version"] == before["evaluation"] + 1
        assert fx.read_selection(api, env.selection["id"])["version"] == before["selection"] + 1
        assert fx.read_agent(api, env.agent["id"])["version"] == before["agent"] + 1
        assert (
            fx.read_interaction(api, env.interaction["id"])["version"]
            == before["interaction"] + 1
        )
        assert fx.read_plan(api, env.plan["id"])["version"] == before["plan"] + 1

    def test_a_passing_score_leaves_the_whole_chain_dark(self, api):
        """Each hop fires only because its predecessor flipped a value.

        PRD: "If `compliance_result` is `PASS`, none of the three hops fires."

        Design: Difficulty/transitive_cascade/cascade_submit_autofail_reserves_targeted_sampling_slot
        """
        env = _failing_submission_env(api)
        plan_version_before = fx.read_plan(api, env.plan["id"])["version"]

        evaluation = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.PASSING_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        assert_scores(evaluation, weighted_score=82.00, auto_fail_triggered=False, compliance_result="PASS")
        assert fx.read_interaction(api, env.interaction["id"])["compliance_hold"] is False
        agent = fx.read_agent(api, env.agent["id"])
        assert agent["open_compliance_findings"] == 0
        assert agent["coaching_state"] == "NONE"
        plan = fx.read_plan(api, env.plan["id"])
        assert plan["targeted_reserve_by_agent"] == {}
        assert plan["targeted_reserved_count"] == 0
        assert plan["version"] == plan_version_before
        assert_attainment(plan, env.agent["id"], consumed=1, remaining=3)


#: The replacement scorecard an upheld dispute installs: the disclosure earns
#: four of five points, which clears both the automatic fail and the floor.
ADJUSTED_SCORES: Dict[str, Any] = {"DISCLOSE": 4, "GREET": 4, "RESOLVE": 3, "SURVEY": 5}


def _coached_and_disputed_env(api):
    """The forward cascade, plus a coaching plan sized off it and a dispute
    already under review by a second evaluator."""
    env = _failing_submission_env(api)
    env.evaluation = fx.submit_evaluation(
        api, env.evaluation["id"], env.evaluator["id"], f.AUTO_FAIL_ITEM_SCORES
    )
    env.evaluation = fx.deliver_evaluation(api, env.evaluation["id"], env.evaluator["id"])
    agent = fx.read_agent(api, env.agent["id"])
    env.coaching_plan = fx.create_coaching_plan(
        api,
        agent["id"],
        env.evaluation["id"],
        agent["version"],
        assigned_supervisor_id="SUP-7",
        target_score=70.00,
    )
    env.reviewer = fx.create_evaluator(api, full_name="Ravi Reviewer")
    env.dispute = fx.file_dispute(
        api,
        env.evaluation["id"],
        env.agent["id"],
        fx.read_evaluation(api, env.evaluation["id"])["version"],
        disputed_behavior_codes=["DISCLOSE"],
        rationale="The disclosure is audible at 00:09 of the recording.",
    )
    env.dispute = fx.review_dispute(api, env.dispute["id"], env.reviewer["id"])
    return env


class TestUpheldDisputeUnwindsTheChain:
    """The adjudication reverses the chain and reaches a fifth entity that did
    not exist when the forward cascade ran."""

    def test_the_coaching_plan_is_sized_off_the_failed_score_before_the_unwind(self, api):
        """The plan the unwind will retire is a fully sized T3 plan.

        PRD: "Third, an adjusted deficit is formed by multiplying `deficit_pct` by
        the tier's severity multiplier — one for `T1`, one and twenty-five
        hundredths for `T2`, one and a half for `T3` — and rounding half up to two
        decimals."
        PRD: "Fourth, `required_session_count` is the adjusted deficit divided by
        the tier's expected gain per session — two and a half points for `T1`, two
        points for `T2`, one and a half points for `T3` — rounded **up** to the next
        whole number, then clamped to no fewer than one and no more than eight
        sessions."

        Design: Difficulty/transitive_cascade/cascade_dispute_upheld_unwinds_finding_and_voids_coaching_plan
        """
        env = _coached_and_disputed_env(api)

        plan = env.coaching_plan
        # 70.00 - 52.00 = 18.00 -> T3 -> 27.00 / 1.50 = 18 sessions, clamped to 8.
        assert_money(plan["deficit_pct"], 18.00)
        assert plan["escalation_tier"] == "T3"
        assert plan["required_session_count"] == 8
        assert_instant(plan["due_at"], "2026-10-04T09:00:00Z")
        assert plan["status"] == "ASSIGNED"
        assert fx.read_agent(api, env.agent["id"])["coaching_state"] == "ACTIVE"

    def test_upholding_the_dispute_clears_the_hold_the_finding_and_the_plan(self, api):
        """Four hops, in the opposite direction, on one adjudication.

        PRD: "**Hop two:** precisely because `compliance_result` moved from `FAIL`
        to `PASS`, the interaction's `compliance_hold` is cleared to `false`."
        PRD: "**Hop three:** precisely because `compliance_hold` moved from `true`
        to `false`, the agent's `open_compliance_findings` is recomputed one lower,
        and `quality_index_rolling` and `quality_index_period` are recomputed — the
        adjusted score now takes precedence over the original `weighted_score` in
        every aggregate."
        PRD: "**Hop four:** precisely because `open_compliance_findings` reached
        `0`, every coaching plan of that agent whose `status` is `ASSIGNED` or
        `IN_PROGRESS` and whose `source_evaluation_id` is this evaluation moves to
        `VOIDED`, and the agent's `coaching_state` becomes `CLEARED` when it had
        been `REQUIRED` or `ACTIVE`."

        Design: Difficulty/transitive_cascade/cascade_dispute_upheld_unwinds_finding_and_voids_coaching_plan
        """
        env = _coached_and_disputed_env(api)

        dispute = fx.resolve_dispute(
            api,
            env.dispute["id"],
            env.reviewer["id"],
            "UPHELD",
            adjusted_item_scores=ADJUSTED_SCORES,
            outcome_note="Disclosure verified in the recording.",
        )

        assert dispute["status"] == "UPHELD"
        # Hop one: 24.00 + 16.00 + 21.00 + 15.00 = 76.00 with the fail undone.
        evaluation = fx.read_evaluation(api, env.evaluation["id"])
        assert_scores(
            evaluation,
            weighted_score=52.00,
            adjusted_weighted_score=76.00,
            compliance_result="PASS",
        )
        assert_parallel_state(evaluation, "REOPENED", "PENDING")
        assert evaluation["feedback_delivered_at"] is None
        # Hop two.
        assert fx.read_interaction(api, env.interaction["id"])["compliance_hold"] is False
        # Hop three: the adjusted figure now drives the index.
        agent = fx.read_agent(api, env.agent["id"])
        assert_agent_index(agent, rolling=76.00, open_compliance_findings=0)
        # Hop four.
        coaching_plan = fx.read_coaching_plan(api, env.coaching_plan["id"])
        assert coaching_plan["status"] == "VOIDED"
        assert agent["coaching_state"] == "CLEARED"
        # A voided plan is retired, not resized.
        assert coaching_plan["required_session_count"] == 8

    def test_the_unwind_stops_at_the_fourth_hop_and_keeps_the_reservation(self, api):
        """No fifth hop hands the reserved sampling slot back.

        PRD: "**Hop four:** precisely because `open_compliance_findings` reached
        `0`, every coaching plan of that agent whose `status` is `ASSIGNED` or
        `IN_PROGRESS` and whose `source_evaluation_id` is this evaluation moves to
        `VOIDED`, and the agent's `coaching_state` becomes `CLEARED` when it had
        been `REQUIRED` or `ACTIVE`."
        PRD: "The effective `TARGETED` cap is its base cap plus that agent's entry
        in `targeted_reserve_by_agent`, treating an absent key as zero."

        Design: Difficulty/transitive_cascade/cascade_dispute_upheld_unwinds_finding_and_voids_coaching_plan
        """
        env = _coached_and_disputed_env(api)

        fx.resolve_dispute(
            api,
            env.dispute["id"],
            env.reviewer["id"],
            "UPHELD",
            adjusted_item_scores=ADJUSTED_SCORES,
            outcome_note="Disclosure verified in the recording.",
        )

        plan = fx.read_plan(api, env.plan["id"])
        assert plan["targeted_reserve_by_agent"] == {env.agent["id"]: 1}
        assert plan["targeted_reserved_count"] == 1
        assert_attainment(plan, env.agent["id"], consumed=1, remaining=4)
        assert_quota_identity(plan, env.agent["id"])
