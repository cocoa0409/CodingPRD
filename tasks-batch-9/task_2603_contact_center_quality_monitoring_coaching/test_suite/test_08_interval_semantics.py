"""The two interval conventions of this domain, deliberately opposite: evaluator
review windows are half-open, sampling-plan periods are closed."""
from test_helpers import (
    ApiErrorId,
    assert_evaluator_load,
    assert_instant,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReviewWindowsAreHalfOpen:
    """The boundary instant belongs to the later window, so touching windows
    coexist on one evaluator."""

    @staticmethod
    def _three_unassigned_selections_env(api):
        """Three contacts of one agent in the pool, none of them assigned, and
        an evaluator with slack capacity."""
        env = fx.program_env(
            api,
            per_agent_target_volume=3,
            mix=dict(f.ALL_RANDOM_MIX),
            max_open_assignments=3,
        )
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            csat_score=3,
        )
        env.interaction3 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T14:00:00Z",
            ended_at="2026-08-04T14:30:00Z",
            csat_score=2,
        )
        env.selection = fx.create_selection(
            api, env.plan["id"], env.interaction["id"], "RANDOM"
        )
        env.selection2 = fx.create_selection(
            api, env.plan["id"], env.interaction2["id"], "RANDOM"
        )
        env.selection3 = fx.create_selection(
            api, env.plan["id"], env.interaction3["id"], "RANDOM"
        )
        return env

    def test_a_window_starting_where_another_ends_is_accepted(self, api):
        """Eleven o'clock belongs to the later window alone.

        PRD: "the requested window must not intersect any window that evaluator
        already holds on a selection in status `ASSIGNED`, using **half-open**
        semantics where the start is included and the end excluded — so a window
        ending at 11:00 sits legally beside one starting at 11:00, while any genuine
        overlap is rejected with `ERR_EVALUATOR_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/overlap_evaluator_review_window_half_open_adjacent_allowed
        """
        env = self._three_unassigned_selections_env(api)

        first = validate_success(
            api.assign_selection(
                env.selection["id"],
                f.assign_payload(
                    env.evaluator["id"],
                    review_window_start="2026-08-05T09:00:00Z",
                    review_window_end="2026-08-05T11:00:00Z",
                ),
                fx.make_quality_manager_headers(),
            )
        )
        second = validate_success(
            api.assign_selection(
                env.selection2["id"],
                f.assign_payload(
                    env.evaluator["id"],
                    review_window_start="2026-08-05T11:00:00Z",
                    review_window_end="2026-08-05T13:00:00Z",
                ),
                fx.make_quality_manager_headers(),
            )
        )

        assert first["status"] == "ASSIGNED"
        assert_instant(first["review_window_start"], "2026-08-05T09:00:00Z")
        assert_instant(first["review_window_end"], "2026-08-05T11:00:00Z")
        assert second["status"] == "ASSIGNED"
        assert_instant(second["review_window_start"], "2026-08-05T11:00:00Z")
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 2)

    def test_a_genuinely_overlapping_window_is_refused(self, api):
        """Half past ten sits inside a window that is already held.

        PRD: "the requested window must not intersect any window that evaluator
        already holds on a selection in status `ASSIGNED`, using **half-open**
        semantics where the start is included and the end excluded — so a window
        ending at 11:00 sits legally beside one starting at 11:00, while any genuine
        overlap is rejected with `ERR_EVALUATOR_WINDOW_CONFLICT`"
        PRD: "and the evaluator's `open_assignment_count`, measured *before* this
        assignment, must be strictly below their `max_open_assignments`, else
        `ERR_EVALUATOR_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/overlap_evaluator_review_window_half_open_adjacent_allowed
        """
        env = self._three_unassigned_selections_env(api)
        fx.assign_selection(
            api,
            env.selection["id"],
            env.evaluator["id"],
            review_window_start="2026-08-05T09:00:00Z",
            review_window_end="2026-08-05T11:00:00Z",
        )
        fx.assign_selection(
            api,
            env.selection2["id"],
            env.evaluator["id"],
            review_window_start="2026-08-05T11:00:00Z",
            review_window_end="2026-08-05T13:00:00Z",
        )
        # Capacity is deliberately slack: two open assignments against three.
        evaluator = fx.read_evaluator(api, env.evaluator["id"])
        assert evaluator["open_assignment_count"] == 2
        assert evaluator["max_open_assignments"] == 3

        response = api.assign_selection(
            env.selection3["id"],
            f.assign_payload(
                env.evaluator["id"],
                review_window_start="2026-08-05T10:30:00Z",
                review_window_end="2026-08-05T12:00:00Z",
            ),
            fx.make_quality_manager_headers(),
        )

        validate_error(response, ApiErrorId.EVALUATOR_WINDOW_CONFLICT.value, 409)
        untouched = fx.read_selection(api, env.selection3["id"])
        assert untouched["status"] == "SELECTED"
        assert untouched["assigned_evaluator_id"] is None
        assert untouched["review_window_start"] is None
        assert untouched["review_window_end"] is None
        assert untouched["version"] == env.selection3["version"]
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 2)


class TestPlanPeriodsAreClosed:
    """The opposite convention on a different resource axis: one shared instant
    is a collision, and the exclusion is scoped by scorecard."""

    @staticmethod
    def _august_period_env(api):
        """Two published scorecards, the first already carrying an OPEN August
        period."""
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        first_form = fx.create_active_form(api)
        second_form = fx.create_active_form(api)
        august = fx.create_open_plan(
            api,
            first_form["id"],
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T23:59:59Z",
            mix=f.source_mix(),
        )
        return fx.Env(form=first_form, other_form=second_form, august=august)

    def test_a_period_starting_on_the_instant_another_ends_collides(self, api):
        """Sharing a single instant is enough under closed-interval semantics.

        PRD: "Before a plan is drafted, and again when it is opened, the server
        compares its period against every other plan sharing the same `form_id` whose
        status is `DRAFT` or `OPEN`, using **closed-interval** semantics: two periods
        collide when they share even a single instant, so touching endpoints collide —
        a plan ending on 31 August collides with a plan starting on 31 August."
        PRD: "Note the deliberate asymmetry between the two interval conventions in
        this domain: plan periods are closed intervals whose endpoints collide, while
        evaluator review windows are half-open intervals whose endpoints do not."

        Design: Difficulty/resource_temporal_overlap/overlap_plan_period_closed_interval_touching_collides
        """
        env = self._august_period_env(api)

        response = api.create_plan(
            f.sample_plan_payload(
                env.form["id"],
                period_start="2026-08-31T23:59:59Z",
                period_end="2026-09-30T23:59:59Z",
                mix=f.source_mix(),
            ),
            fx.make_quality_manager_headers(),
        )

        validate_error(response, ApiErrorId.PLAN_PERIOD_OVERLAP.value, 409)
        august = fx.read_plan(api, env.august["id"])
        assert august["status"] == "OPEN"
        assert august["version"] == env.august["version"]

    def test_a_period_starting_one_second_later_is_disjoint(self, api):
        """One second past the shared instant is no longer a collision.

        PRD: "A collision is rejected with `ERR_PLAN_PERIOD_OVERLAP`."
        PRD: "A drafted plan starts in `DRAFT` with `pinned_form_guidance_version`
        null, `selections_count` and `excluded_count` at `0`, `targeted_reserved_count`
        at `0`, and both `targeted_reserve_by_agent` and `agent_volume_attainment` as
        empty objects."

        Design: Difficulty/resource_temporal_overlap/overlap_plan_period_closed_interval_touching_collides
        """
        env = self._august_period_env(api)

        september = validate_success(
            api.create_plan(
                f.sample_plan_payload(
                    env.form["id"],
                    period_start="2026-09-01T00:00:00Z",
                    period_end="2026-09-30T23:59:59Z",
                    mix=f.source_mix(),
                ),
                fx.make_quality_manager_headers(),
            ),
            201,
        )

        assert september["status"] == "DRAFT"
        assert september["pinned_form_guidance_version"] is None
        assert september["targeted_reserve_by_agent"] == {}
        assert september["agent_volume_attainment"] == {}

    def test_the_identical_period_is_accepted_on_a_different_scorecard(self, api):
        """The exclusion is scoped by `form_id`, not by calendar.

        PRD: "Periods on the same scorecard may not collide."
        PRD: "the plan collection listing accepts `form_id` and `status` filters —
        the latter matching `DRAFT`, `OPEN` or `CLOSED` — giving the reverse path from
        a scorecard to its periods."

        Design: Difficulty/resource_temporal_overlap/overlap_plan_period_closed_interval_touching_collides
        """
        env = self._august_period_env(api)
        validate_error(
            api.create_plan(
                f.sample_plan_payload(
                    env.form["id"],
                    period_start="2026-08-31T23:59:59Z",
                    period_end="2026-09-30T23:59:59Z",
                    mix=f.source_mix(),
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.PLAN_PERIOD_OVERLAP.value,
        )
        september = fx.create_plan(
            api,
            env.form["id"],
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-09-30T23:59:59Z",
            mix=f.source_mix(),
        )

        twin = validate_success(
            api.create_plan(
                f.sample_plan_payload(
                    env.other_form["id"],
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-08-31T23:59:59Z",
                    mix=f.source_mix(),
                ),
                fx.make_quality_manager_headers(),
            ),
            201,
        )

        assert twin["form_id"] == env.other_form["id"]
        assert_instant(twin["period_start"], "2026-08-01T00:00:00Z")
        rows, meta = validate_paginated(
            api.list_plans(fx.make_quality_manager_headers(), {"form_id": env.form["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {env.august["id"], september["id"]}
