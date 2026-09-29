"""Two requests that violate two rules at once, and the published order that
decides which rejection the caller sees."""
from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    assert_evaluator_load,
    assert_money,
    assert_plan_counters,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)


class TestPlanStateOutranksTheAgentQuota:
    """A closed plan whose single slot is also spent: the state rejection is the
    one that must surface."""

    @staticmethod
    def _spent_and_closed_plan_env(api):
        """A plan of one contact per agent, its slot consumed by an evaluated
        selection, then closed."""
        env = fx.assigned_env(api, per_agent_target_volume=1, mix=dict(f.ALL_RANDOM_MIX))
        env.evaluation = fx.open_evaluation(api, env.selection["id"], env.evaluator["id"])
        env.evaluation = fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"], f.PASSING_ITEM_SCORES
        )
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T14:00:00Z",
            ended_at="2026-08-04T14:30:00Z",
            csat_score=2,
            repeat_contact_within_72h=True,
        )
        env.plan = fx.close_plan(api, env.plan["id"])
        return env

    def test_the_closed_plan_answers_before_the_exhausted_quota(self, api):
        """Both rules are true; the plan-state rule is checked first.

        PRD: "The plan must be `OPEN`, else `ERR_PLAN_NOT_OPEN`, and the
        interaction must satisfy the consent gate of §2.8."
        PRD: "Finally the two quota gates fire in order: the agent's `consumed`
        count for this plan must be strictly below `per_agent_target_volume` plus
        their targeted reserve, else `ERR_AGENT_QUOTA_EXCEEDED`; and the consumed
        count for the requested source must be strictly below that source's
        effective cap, else `ERR_SOURCE_MIX_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_plan_state_beats_agent_quota_on_selection_create
        """
        env = self._spent_and_closed_plan_env(api)
        # The quota rule is genuinely violated too: the one slot is spent.
        plan_before = fx.read_plan(api, env.plan["id"])
        assert plan_before["status"] == "CLOSED"
        assert plan_before["agent_volume_attainment"][env.agent["id"]]["consumed"] == 1
        assert plan_before["agent_volume_attainment"][env.agent["id"]]["remaining"] == 0

        response = api.create_selection(
            f.sample_selection_payload(env.plan["id"], env.interaction2["id"]),
            fx.make_quality_manager_headers(),
        )

        validate_error(response, ApiErrorId.PLAN_NOT_OPEN.value, 409)

    def test_the_rejected_pull_leaves_the_plan_and_its_pool_untouched(self, api):
        """No row is written and no counter moves on the refused create.

        PRD: "At plan level, `selections_count` is the number of selections of the
        plan in status `SELECTED`, `ASSIGNED` or `EVALUATED`; `excluded_count` is
        the number in status `EXCLUDED`; and `targeted_reserved_count` is the sum of
        all values in `targeted_reserve_by_agent`."
        PRD: "In the first hop, every selection of the plan whose status is
        `SELECTED` or `ASSIGNED` is processed in `created_at` ascending order and
        moved to `EXCLUDED` with `exclusion_reason` set to `PLAN_CLOSED_SWEEP`;
        selections already `EVALUATED` keep their status, since the sweep is
        conditional over non-terminal children only."

        Design: Difficulty/priority_pair_validation_conflict/priority_plan_state_beats_agent_quota_on_selection_create
        """
        env = self._spent_and_closed_plan_env(api)
        version_before = fx.read_plan(api, env.plan["id"])["version"]

        validate_error(
            api.create_selection(
                f.sample_selection_payload(env.plan["id"], env.interaction2["id"]),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.PLAN_NOT_OPEN.value,
        )

        plan = fx.read_plan(api, env.plan["id"])
        assert plan["version"] == version_before
        assert_plan_counters(plan, selections_count=1, excluded_count=0)
        assert fx.read_selection(api, env.selection["id"])["status"] == "EVALUATED"
        rows, meta = validate_paginated(
            api.list_selections(fx.make_quality_manager_headers(), {"plan_id": env.plan["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [env.selection["id"]]


#: Eve's harsh reading of the calibration contact: 24.00 + 12.00 + 14.00 +
#: 12.00 = 62.00, twenty points below the 82.00 benchmark.
HARSH_SUBMISSION: Dict[str, Any] = {"DISCLOSE": 4, "GREET": 3, "RESOLVE": 2, "SURVEY": 4}
#: Ravi's slightly generous reading: 30.00 + 20.00 + 21.00 + 15.00 = 86.00.
GENEROUS_SUBMISSION: Dict[str, Any] = {"DISCLOSE": 5, "GREET": 5, "RESOLVE": 3, "SURVEY": 5}


class TestSuspensionOutranksTheWindowConflict:
    """A suspended evaluator whose live window also collides: the standing
    rejection is the one that must surface."""

    @staticmethod
    def _suspended_evaluator_env(api):
        """A variant close suspends the evaluator while leaving their in-flight
        window in place, so both assign rules are violated at once."""
        env = fx.calibration_scoring_env(api, per_agent_target_volume=4, mix=f.source_mix())
        env.selection = fx.create_selection(
            api, env.plan["id"], env.interaction["id"], "RANDOM"
        )
        env.selection = fx.assign_selection(
            api,
            env.selection["id"],
            env.evaluator["id"],
            review_window_start="2026-08-05T09:00:00Z",
            review_window_end="2026-08-05T11:00:00Z",
        )
        # A DRAFT evaluation row is what exempts the selection from release.
        env.evaluation = fx.open_evaluation(api, env.selection["id"], env.evaluator["id"])
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T14:00:00Z",
            ended_at="2026-08-04T14:30:00Z",
            csat_score=2,
            repeat_contact_within_72h=True,
        )
        env.selection2 = fx.create_selection(
            api, env.plan["id"], env.interaction2["id"], "RANDOM"
        )
        env.submission = fx.create_submission(
            api, env.session["id"], env.evaluator["id"], HARSH_SUBMISSION
        )
        env.submission2 = fx.create_submission(
            api, env.session["id"], env.reviewer["id"], GENEROUS_SUBMISSION
        )
        env.session = fx.close_session(api, env.session["id"])
        return env

    def test_the_variant_close_suspends_the_harsh_reader_and_bands_both_readings(self, api):
        """The setup baseline: one severe deviation, one minor one.

        PRD: "Each submission's `alignment` is then banded on the absolute value
        of that rounded deviation: `ALIGNED` when the absolute deviation is at most
        `3.00`, `MINOR_VARIANCE` when it is greater than `3.00` and at most `7.00`,
        and `MAJOR_VARIANCE` when it is greater than `7.00`."
        PRD: "**Step three:** evaluator standing is moved, one submission at a
        time, in `created_at` ascending order, under four rules applied in this
        order — an absolute deviation greater than `15.00` sets that evaluator's
        `calibration_status` to `SUSPENDED` outright; otherwise an `alignment` of
        `MAJOR_VARIANCE` on an evaluator currently `CALIBRATED` sets them to
        `PROBATION`; an `alignment` of `MAJOR_VARIANCE` on an evaluator already
        `PROBATION` sets them to `SUSPENDED`; and an `alignment` of `ALIGNED` on an
        evaluator currently `PROBATION` restores them to `CALIBRATED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_evaluator_suspension_beats_review_window_conflict
        """
        env = self._suspended_evaluator_env(api)

        assert env.session["status"] == "CLOSED_VARIANT"
        assert_money(env.session["benchmark_weighted_score"], 82.00)
        assert_money(env.session["variance_pct"], 20.00)
        assert_money(env.session["mean_abs_deviation"], 12.00)
        assert env.session["participant_count"] == 2

        harsh = fx.read_submission(api, env.submission["id"])
        assert_money(harsh["weighted_score"], 62.00)
        assert_money(harsh["deviation_pct"], -20.00)
        assert harsh["alignment"] == "MAJOR_VARIANCE"
        generous = fx.read_submission(api, env.submission2["id"])
        assert_money(generous["weighted_score"], 86.00)
        assert_money(generous["deviation_pct"], 4.00)
        assert generous["alignment"] == "MINOR_VARIANCE"

        suspended = fx.read_evaluator(api, env.evaluator["id"])
        assert suspended["calibration_status"] == "SUSPENDED"
        assert_money(suspended["last_deviation_pct"], -20.00)
        assert fx.read_evaluator(api, env.reviewer["id"])["calibration_status"] == "CALIBRATED"

    def test_the_in_flight_window_survives_the_release_hop(self, api):
        """The colliding window is still held, which is what makes the pair real.

        PRD: "**Hop one:** precisely because those evaluators became `SUSPENDED`,
        each of their selections whose status is `ASSIGNED` and which carries no
        evaluation row moves `ASSIGNED → SELECTED` with `assigned_evaluator_id`,
        `review_window_start` and `review_window_end` all cleared; a selection that
        already carries an evaluation row, even a `DRAFT` one, is left `ASSIGNED` so
        the in-flight scoring is not orphaned."

        Design: Difficulty/priority_pair_validation_conflict/priority_evaluator_suspension_beats_review_window_conflict
        """
        env = self._suspended_evaluator_env(api)

        held = fx.read_selection(api, env.selection["id"])
        assert held["status"] == "ASSIGNED"
        assert held["assigned_evaluator_id"] == env.evaluator["id"]
        assert held["review_window_start"] is not None
        assert held["review_window_end"] is not None
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 1)

    def test_the_suspension_answers_before_the_overlapping_window(self, api):
        """Both rules are true; the standing rule is checked first.

        PRD: "the named evaluator's `calibration_status` must not be `SUSPENDED`,
        else `ERR_EVALUATOR_NOT_CALIBRATED`; `review_window_end` must be strictly
        after `review_window_start`, else `ERR_INVALID_TIME_RANGE`; the requested
        window must not intersect any window that evaluator already holds on a
        selection in status `ASSIGNED`, using **half-open** semantics where the
        start is included and the end excluded — so a window ending at 11:00 sits
        legally beside one starting at 11:00, while any genuine overlap is rejected
        with `ERR_EVALUATOR_WINDOW_CONFLICT`"

        Design: Difficulty/priority_pair_validation_conflict/priority_evaluator_suspension_beats_review_window_conflict
        """
        env = self._suspended_evaluator_env(api)
        version_before = fx.read_selection(api, env.selection2["id"])["version"]

        # [10:00, 12:00) genuinely intersects the still-live [09:00, 11:00).
        response = api.assign_selection(
            env.selection2["id"],
            f.assign_payload(
                env.evaluator["id"],
                review_window_start="2026-08-05T10:00:00Z",
                review_window_end="2026-08-05T12:00:00Z",
            ),
            fx.make_quality_manager_headers(),
        )

        validate_error(response, ApiErrorId.EVALUATOR_NOT_CALIBRATED.value, 409)
        untouched = fx.read_selection(api, env.selection2["id"])
        assert untouched["status"] == "SELECTED"
        assert untouched["version"] == version_before
        assert untouched["assigned_evaluator_id"] is None
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 1)
