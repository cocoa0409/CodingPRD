"""Two gates whose deciding state lives on another entity: one sideways to an
entity the request never names, one up the reference to the parent scorecard."""
from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    assert_agent_index,
    assert_evaluator_load,
    assert_instant,
    assert_money,
    assert_plan_counters,
    assert_scores,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

#: The harsh reading that carries a twenty-point deviation and suspends.
HARSH_SUBMISSION: Dict[str, Any] = {"DISCLOSE": 4, "GREET": 3, "RESOLVE": 2, "SURVEY": 4}
#: The mildly generous reading that leaves its author calibrated.
GENEROUS_SUBMISSION: Dict[str, Any] = {"DISCLOSE": 5, "GREET": 5, "RESOLVE": 3, "SURVEY": 5}


def _two_scorers_one_suspended_env(api):
    """Two evaluators each holding a DRAFT evaluation, one of them suspended by
    a calibration session neither evaluation references."""
    env = fx.calibration_scoring_env(api, per_agent_target_volume=4, mix=f.source_mix())
    env.selection = fx.create_selection(api, env.plan["id"], env.interaction["id"], "RANDOM")
    env.selection = fx.assign_selection(
        api,
        env.selection["id"],
        env.evaluator["id"],
        review_window_start="2026-08-05T09:00:00Z",
        review_window_end="2026-08-05T11:00:00Z",
    )
    env.evaluation = fx.open_evaluation(api, env.selection["id"], env.evaluator["id"])
    env.interaction2 = fx.create_verified_interaction(
        api,
        env.agent["id"],
        started_at="2026-08-04T14:00:00Z",
        ended_at="2026-08-04T14:30:00Z",
        csat_score=2,
    )
    env.selection2 = fx.create_selection(api, env.plan["id"], env.interaction2["id"], "RANDOM")
    env.selection2 = fx.assign_selection(
        api,
        env.selection2["id"],
        env.reviewer["id"],
        review_window_start="2026-08-05T11:00:00Z",
        review_window_end="2026-08-05T13:00:00Z",
    )
    env.evaluation2 = fx.open_evaluation(api, env.selection2["id"], env.reviewer["id"])
    fx.create_submission(api, env.session["id"], env.evaluator["id"], HARSH_SUBMISSION)
    fx.create_submission(api, env.session["id"], env.reviewer["id"], GENEROUS_SUBMISSION)
    env.session = fx.close_session(api, env.session["id"])
    return env


class TestSubmitGatedByAThirdEntitysStanding:
    """The write targets an evaluation; the gate is the acting evaluator's
    calibration standing, set by a session neither row names."""

    def test_the_suspended_evaluator_may_not_submit_their_draft(self, api):
        """A state on an entity outside the request refuses the write.

        PRD: "That evaluator's `calibration_status` must not be `SUSPENDED`, else
        `ERR_EVALUATOR_NOT_CALIBRATED`."
        PRD: "an absolute deviation greater than `15.00` sets that evaluator's
        `calibration_status` to `SUSPENDED` outright"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_submit_blocked_by_suspended_evaluator
        """
        env = _two_scorers_one_suspended_env(api)
        assert fx.read_evaluator(api, env.evaluator["id"])["calibration_status"] == "SUSPENDED"

        response = api.submit_evaluation(
            env.evaluation["id"],
            f.submit_payload(f.PASSING_ITEM_SCORES),
            fx.make_evaluator_headers(env.evaluator["id"]),
        )

        validate_error(response, ApiErrorId.EVALUATOR_NOT_CALIBRATED.value, 409)
        blocked = fx.read_evaluation(api, env.evaluation["id"])
        assert blocked["review_status"] == "DRAFT"
        assert blocked["weighted_score"] is None
        assert blocked["submitted_at"] is None
        assert blocked["version"] == env.evaluation["version"]
        assert fx.read_selection(api, env.selection["id"])["status"] == "ASSIGNED"
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 1)

    def test_the_calibrated_evaluator_submits_the_identical_payload(self, api):
        """Same clock, same form, same scores — only the standing differs.

        PRD: "**Step three:** the underlying selection moves `ASSIGNED →
        EVALUATED` and the evaluator's `open_assignment_count` is recomputed
        downward, releasing capacity."
        PRD: "otherwise an `alignment` of `MAJOR_VARIANCE` on an evaluator currently
        `CALIBRATED` sets them to `PROBATION`; an `alignment` of `MAJOR_VARIANCE` on
        an evaluator already `PROBATION` sets them to `SUSPENDED`; and an `alignment`
        of `ALIGNED` on an evaluator currently `PROBATION` restores them to
        `CALIBRATED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_submit_blocked_by_suspended_evaluator
        """
        env = _two_scorers_one_suspended_env(api)
        assert fx.read_evaluator(api, env.reviewer["id"])["calibration_status"] == "CALIBRATED"

        evaluation = validate_success(
            api.submit_evaluation(
                env.evaluation2["id"],
                f.submit_payload(f.PASSING_ITEM_SCORES),
                fx.make_evaluator_headers(env.reviewer["id"]),
            )
        )

        assert evaluation["review_status"] == "SUBMITTED"
        assert_scores(evaluation, weighted_score=82.00, compliance_result="PASS")
        assert fx.read_selection(api, env.selection2["id"])["status"] == "EVALUATED"
        assert_evaluator_load(fx.read_evaluator(api, env.reviewer["id"]), 0)

    def test_only_the_permitted_submission_moves_the_agents_index(self, api):
        """The refused write contributes nothing to the population.

        PRD: "Both draw on the same population — every evaluation of that agent
        whose `review_status` is `SUBMITTED`, `FINALIZED` or `REOPENED` and whose
        `weighted_score` is not null."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_submit_blocked_by_suspended_evaluator
        """
        env = _two_scorers_one_suspended_env(api)

        validate_error(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.PASSING_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            ),
            ApiErrorId.EVALUATOR_NOT_CALIBRATED.value,
        )
        fx.submit_evaluation(
            api, env.evaluation2["id"], env.reviewer["id"], f.PASSING_ITEM_SCORES
        )

        assert_agent_index(fx.read_agent(api, env.agent["id"]), rolling=82.00)


class TestPlanOpenGatedByTheParentScorecard:
    """Retiring a scorecard forecloses new commitment without disturbing the
    period already running under it."""

    @staticmethod
    def _retired_form_env(api):
        """One plan opened before the retirement and one still in DRAFT after
        it, on the same retired scorecard."""
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        form = fx.create_active_form(api)
        agent = fx.create_agent(api)
        running = fx.create_open_plan(
            api,
            form["id"],
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-07-31T23:59:59Z",
        )
        drafted = fx.create_plan(
            api,
            form["id"],
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T23:59:59Z",
        )
        interaction = fx.create_verified_interaction(
            api,
            agent["id"],
            started_at="2026-07-15T10:00:00Z",
            ended_at="2026-07-15T10:10:00Z",
            csat_score=4,
        )
        form = fx.retire_form(api, form["id"])
        return fx.Env(
            form=form,
            agent=agent,
            running=running,
            drafted=drafted,
            interaction=interaction,
        )

    def test_the_drafted_plan_can_never_be_opened_once_the_form_retires(self, api):
        """The guard is evaluated at the open transition and refuses it.

        PRD: "A plan that is not `DRAFT` answers `ERR_PLAN_NOT_DRAFT`; a plan whose
        form is no longer `ACTIVE` answers `ERR_FORM_NOT_ACTIVE`."
        PRD: "What retirement forecloses is new commitment: a `DRAFT` plan on that
        form stays `DRAFT` but can never be opened, a new plan cannot name it, and a
        new calibration session cannot name it — all three answer
        `ERR_FORM_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_plan_open_blocked_by_retired_form
        """
        env = self._retired_form_env(api)
        assert env.form["status"] == "RETIRED"
        assert_instant(env.form["retired_at"], "2026-08-05T09:00:00Z")

        response = api.open_plan(env.drafted["id"], fx.make_quality_manager_headers())

        validate_error(response, ApiErrorId.FORM_NOT_ACTIVE.value, 409)
        blocked = fx.read_plan(api, env.drafted["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked["pinned_form_guidance_version"] is None
        assert blocked["version"] == env.drafted["version"]

    def test_the_plan_that_was_already_open_keeps_accepting_contacts(self, api):
        """The same parent state blocks one child operation and permits another.

        PRD: "Sampling plans already `OPEN` on the retired form keep running
        against the guidance revision they pinned when they opened, and evaluations
        under them continue to be scorable."
        PRD: "On success the selection is stored with `status` of `SELECTED`, with
        `agent_id` denormalised from the interaction's `agent_id` at creation and
        never updated afterwards even if the interaction is later re-attributed, with
        `assigned_evaluator_id`, `review_window_start`, `review_window_end` and
        `exclusion_reason` all null; the plan's `agent_volume_attainment` and
        `selections_count` and the interaction's `sampled_count` are recomputed, and
        the plan's `version` is incremented."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_plan_open_blocked_by_retired_form
        """
        env = self._retired_form_env(api)

        selection = validate_success(
            api.create_selection(
                f.sample_selection_payload(env.running["id"], env.interaction["id"]),
                fx.make_quality_manager_headers(),
            ),
            201,
        )

        assert selection["status"] == "SELECTED"
        assert selection["agent_id"] == env.agent["id"]
        running = fx.read_plan(api, env.running["id"])
        assert running["status"] == "OPEN"
        assert_plan_counters(running, selections_count=1, excluded_count=0)

    def test_retiring_the_form_neither_swept_nor_closed_the_running_period(self, api):
        """Retirement is gentle on work already in flight.

        PRD: "Retirement is deliberately gentle on work already in flight."
        PRD: "Retirement moves an `ACTIVE` form to `RETIRED`, stamps `retired_at`
        with the current logical-clock instant, and increments `version`; attempting
        it on a form that is not `ACTIVE` answers `ERR_FORM_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_plan_open_blocked_by_retired_form
        """
        env = self._retired_form_env(api)

        running = fx.read_plan(api, env.running["id"])
        assert running["status"] == "OPEN"
        assert running["version"] == env.running["version"]
        assert_plan_counters(running, selections_count=0, excluded_count=0)
        assert_money(env.form["behavior_weight_total"], 100.00)
