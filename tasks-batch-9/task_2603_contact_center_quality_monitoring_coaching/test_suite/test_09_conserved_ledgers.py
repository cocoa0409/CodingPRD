"""Two derived ledgers that must return to their exact prior values when the
event that moved them is reversed."""
from test_helpers import (
    assert_attainment,
    assert_evaluator_load,
    assert_excluded_selection,
    assert_plan_counters,
    assert_quota_identity,
    factories as f,
    fixtures as fx,
    validate_success,
)


class TestSamplingSlotLedgerIsConserved:
    """Creating a selection and then excluding it returns both sides of the
    quota identity to their pre-create values."""

    @staticmethod
    def _pool_env(api):
        """An OPEN plan of four contacts per agent and two consent-cleared
        contacts ready to be pulled."""
        env = fx.program_env(api, per_agent_target_volume=4, mix=f.source_mix())
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            csat_score=3,
        )
        return env

    def test_the_ledger_holds_at_every_step_of_pull_pull_then_drop(self, api):
        """Four readings of the identity, none of them drifting.

        PRD: "The identity that must always hold is that for every plan and agent,
        `consumed` plus `remaining` equals `per_agent_target_volume` plus that agent's
        reserve — which is exactly why creating a selection and then excluding it
        returns both sides to their pre-create values."
        PRD: "The agent's total `consumed` is the sum across the three sources, and
        `remaining` is the `per_agent_target_volume` plus that agent's targeted reserve,
        minus `consumed`."

        Design: Difficulty/compensating_invariant/invariant_sampling_slots_conserved_across_create_then_exclude
        """
        env = self._pool_env(api)
        baseline = fx.read_plan(api, env.plan["id"])
        assert baseline["agent_volume_attainment"] == {}
        assert_plan_counters(
            baseline, selections_count=0, excluded_count=0, targeted_reserved_count=0
        )

        first = fx.create_selection(api, env.plan["id"], env.interaction["id"], "RANDOM")
        after_first = fx.read_plan(api, env.plan["id"])
        assert_attainment(
            after_first,
            env.agent["id"],
            consumed=1,
            remaining=3,
            by_source={"RANDOM": 1, "TARGETED": 0, "CUSTOMER_FLAGGED": 0},
        )
        assert_quota_identity(after_first, env.agent["id"])

        second = fx.create_selection(api, env.plan["id"], env.interaction2["id"], "RANDOM")
        after_second = fx.read_plan(api, env.plan["id"])
        assert_attainment(
            after_second,
            env.agent["id"],
            consumed=2,
            remaining=2,
            by_source={"RANDOM": 2, "TARGETED": 0, "CUSTOMER_FLAGGED": 0},
        )
        assert_quota_identity(after_second, env.agent["id"])
        assert_plan_counters(after_second, selections_count=2, excluded_count=0)

        fx.exclude_selection(api, second["id"], "EVALUATOR_UNAVAILABLE")

        after_exclude = fx.read_plan(api, env.plan["id"])
        assert_quota_identity(after_exclude, env.agent["id"])
        # Byte-identical to the reading taken right after the first create.
        assert (
            after_exclude["agent_volume_attainment"][env.agent["id"]]
            == after_first["agent_volume_attainment"][env.agent["id"]]
        )
        assert fx.read_selection(api, first["id"])["status"] == "SELECTED"

    def test_the_slot_returns_while_the_history_row_survives(self, api):
        """The consumed count falls but the excluded count rises.

        PRD: "On success the selection moves to `EXCLUDED` with the supplied reason
        recorded, `assigned_evaluator_id` and both window bounds cleared, the plan's
        `agent_volume_attainment`, `selections_count` and `excluded_count` and the
        interaction's `sampled_count` recomputed so that the slot returns to the agent's
        `remaining` volume, and the selection's `version` incremented."
        PRD: "`sampled_count` is always the number of selections referencing this
        interaction whose status is `SELECTED`, `ASSIGNED` or `EVALUATED`."

        Design: Difficulty/compensating_invariant/invariant_sampling_slots_conserved_across_create_then_exclude
        """
        env = self._pool_env(api)
        first = fx.create_selection(api, env.plan["id"], env.interaction["id"], "RANDOM")
        second = fx.create_selection(api, env.plan["id"], env.interaction2["id"], "RANDOM")
        assert fx.read_interaction(api, env.interaction["id"])["sampled_count"] == 1
        assert fx.read_interaction(api, env.interaction2["id"])["sampled_count"] == 1

        dropped = fx.exclude_selection(api, second["id"], "EVALUATOR_UNAVAILABLE")

        assert_excluded_selection(dropped, "EVALUATOR_UNAVAILABLE")
        plan = fx.read_plan(api, env.plan["id"])
        assert_plan_counters(plan, selections_count=1, excluded_count=1)
        assert_attainment(
            plan,
            env.agent["id"],
            consumed=1,
            remaining=3,
            by_source={"RANDOM": 1, "TARGETED": 0, "CUSTOMER_FLAGGED": 0},
        )
        assert fx.read_interaction(api, env.interaction2["id"])["sampled_count"] == 0
        assert fx.read_interaction(api, env.interaction["id"])["sampled_count"] == 1
        assert fx.read_selection(api, first["id"])["status"] == "SELECTED"


class TestEvaluatorLoadLedgerReconcilesAfterASweep:
    """A two-row automatic sweep must land the evaluator's open-assignment count
    exactly on zero and free both windows."""

    @staticmethod
    def _two_assignments_env(api):
        """Two adjacent windows on one evaluator, neither carrying an
        evaluation row, inside a plan about to be closed."""
        env = fx.two_selection_env(
            api, per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX), max_open_assignments=3
        )
        return env

    def test_the_sweep_releases_both_rows_and_the_count_lands_on_zero(self, api):
        """Not one row and not the last row: both.

        PRD: "In the second hop, precisely because each swept selection left the
        pool, its `assigned_evaluator_id` and both window bounds are cleared and the
        affected evaluator's `open_assignment_count` is recomputed, freeing the window
        for later assignments."
        PRD: "`open_assignment_count` is always the number of selections whose
        `assigned_evaluator_id` names this evaluator and whose status is `ASSIGNED` —
        selections that are merely `SELECTED`, or that have reached `EVALUATED` or
        `EXCLUDED`, cost the evaluator nothing."

        Design: Difficulty/compensating_invariant/invariant_evaluator_load_ledger_reconciles_after_plan_close_sweep
        """
        env = self._two_assignments_env(api)
        baseline = fx.read_evaluator(api, env.evaluator["id"])
        assert_evaluator_load(baseline, 2)
        assert baseline["max_open_assignments"] == 3

        validate_success(api.close_plan(env.plan["id"], fx.make_quality_manager_headers()))

        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 0)
        for selection_id in (env.selection["id"], env.selection2["id"]):
            swept = fx.read_selection(api, selection_id)
            assert_excluded_selection(swept, "PLAN_CLOSED_SWEEP")
            assert swept["review_window_start"] is None
            assert swept["review_window_end"] is None

    def test_the_swept_plan_returns_every_slot_to_the_agent(self, api):
        """The slot ledger reconciles at zero consumed against a full quota.

        PRD: "In the third hop, precisely because the swept selections no longer
        consume slots, `agent_volume_attainment`, `selections_count` and `excluded_count`
        are recomputed on the plan and `sampled_count` is recomputed on each swept
        interaction."
        PRD: "In the first hop, every selection of the plan whose status is
        `SELECTED` or `ASSIGNED` is processed in `created_at` ascending order and moved
        to `EXCLUDED` with `exclusion_reason` set to `PLAN_CLOSED_SWEEP`; selections
        already `EVALUATED` keep their status, since the sweep is conditional over
        non-terminal children only."

        Design: Difficulty/compensating_invariant/invariant_evaluator_load_ledger_reconciles_after_plan_close_sweep
        """
        env = self._two_assignments_env(api)

        plan = validate_success(
            api.close_plan(env.plan["id"], fx.make_quality_manager_headers())
        )

        assert plan["status"] == "CLOSED"
        assert_plan_counters(plan, selections_count=0, excluded_count=2)
        assert_attainment(
            plan,
            env.agent["id"],
            consumed=0,
            remaining=4,
            by_source={"RANDOM": 0, "TARGETED": 0, "CUSTOMER_FLAGGED": 0},
        )
        assert_quota_identity(plan, env.agent["id"])
        assert fx.read_interaction(api, env.interaction["id"])["sampled_count"] == 0
        assert fx.read_interaction(api, env.interaction2["id"])["sampled_count"] == 0

    def test_each_swept_row_and_the_plan_take_exactly_one_version_bump(self, api):
        """The sweep is one event, not one event per re-read.

        PRD: "The plan's `version` is incremented, as is the `version` of every
        selection the sweep touched."

        Design: Difficulty/compensating_invariant/invariant_evaluator_load_ledger_reconciles_after_plan_close_sweep
        """
        env = self._two_assignments_env(api)
        before = {
            "plan": fx.read_plan(api, env.plan["id"])["version"],
            "first": fx.read_selection(api, env.selection["id"])["version"],
            "second": fx.read_selection(api, env.selection2["id"])["version"],
        }

        plan = validate_success(
            api.close_plan(env.plan["id"], fx.make_quality_manager_headers())
        )

        assert plan["version"] == before["plan"] + 1
        assert fx.read_selection(api, env.selection["id"])["version"] == before["first"] + 1
        assert fx.read_selection(api, env.selection2["id"])["version"] == before["second"] + 1
