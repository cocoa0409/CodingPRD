"""Writes that are gated on the state of an entity the request never names.

Each scenario fires one call, watches it fail because of a row two hops away,
then moves only that distant row and replays the identical call.
"""

from test_helpers import (
    ChamberSpec,
    ChartSpec,
    LotSpec,
    USER_QUALITY_MANAGER,
    build_line,
    complete_step,
    fab_planner_headers,
    make_operator_headers,
    open_run,
    two_recipe_line_spec,
)
from test_helpers.api_errors import (
    ERR_PLAN_NOT_COMMITTED,
    ERR_RECIPE_RESTRICTED,
    ERR_SPC_CHART_SUSPENDED,
    ERR_STALE_PLAN_VERSION,
)
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_ratio,
    assert_timestamp_equals,
)
from test_helpers.factories import (
    measurement_payload,
    release_lot_payload,
    step_run_payload,
)
from prd_bench_local_runner.testing.validators import validate_error


# --------------------------------------------------------------------------
# A step run gated on the status of its step's recipe
# --------------------------------------------------------------------------


def _line_whose_litho_recipe_is_restricted(fab):
    """An approved minor notice has parked LITHO-100 in RESTRICTED."""
    env = build_line(fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 3, "STANDARD")]))
    litho = env.recipes[0]
    env.notice = fab.change_request(
        litho["id"], "MINOR", 50.5, "Half-unit dose trim"
    )
    env.approved = fab.approve_change_request(
        env.notice["id"], litho["version"], approver_user_id=USER_QUALITY_MANAGER
    )
    return env


class TestTrackInGatedOnRecipeStatus:
    def test_a_restricted_recipe_blocks_a_run_on_every_step_that_uses_it(self, fab):
        """The track-in names a lot, a step and an operator, and fails on the recipe.

        PRD: "A `RESTRICTED` recipe blocks two things while it waits: no chamber
        may be qualified against it, and no production run may be opened on a
        step that uses it, both rejected with `ERR_RECIPE_RESTRICTED`."

        Design: Difficulty/cross_entity_state_dependency/track_in_blocked_while_the_steps_recipe_is_restricted
        """
        env = _line_whose_litho_recipe_is_restricted(fab)
        operator_id = env.operators[0]["id"]

        # 10.0 class + 25.0 * (0.01 / 0.10) + 15.0 * (1/20).
        assert env.notice["impact_lot_count"] == 1
        assert_hours(env.notice["risk_score"], 13.25, "risk_score")
        assert env.notice["requires_full_requal"] is False
        assert_fields(
            fab.read_recipe(env.recipes[0]["id"]),
            status="RESTRICTED",
            restricted_reason="ECN_PENDING_IMPLEMENTATION",
        )

        response = fab.client.create_step_run(
            step_run_payload(env.lots[0]["id"], env.steps[0]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        validate_error(response, ERR_RECIPE_RESTRICTED, 409)
        assert fab.count(
            fab.client.list_step_runs(
                make_operator_headers(operator_id), {"lot_id": env.lots[0]["id"]}
            )
        ) == 0
        assert_lot_state(
            fab.read_lot(env.lots[0]["id"]), flow_state="RELEASED", current_step_seq=0
        )

    def test_implementing_the_notice_unblocks_the_identical_call(self, fab):
        """Returning the recipe to QUALIFIED is all it takes; the lot never changed.

        PRD: "On success the notice is driven `APPROVED → IMPLEMENTED` — terminal
        — with its `version` incremented by 1, and the recipe is driven
        `RESTRICTED → QUALIFIED`: its `target_value` becomes the notice's
        `proposed_target`, its `revision` increments by 1, its
        `restricted_reason` returns to `NONE`, and its `version` increments by
        1."

        Design: Difficulty/cross_entity_state_dependency/track_in_blocked_while_the_steps_recipe_is_restricted
        """
        env = _line_whose_litho_recipe_is_restricted(fab)
        operator_id = env.operators[0]["id"]
        fab.client.create_step_run(
            step_run_payload(env.lots[0]["id"], env.steps[0]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        implemented = fab.implement_change_request(env.notice["id"])

        assert implemented["status"] == "IMPLEMENTED"
        recipe = fab.read_recipe(env.recipes[0]["id"])
        assert_fields(recipe, status="QUALIFIED", revision=2, restricted_reason="NONE")
        assert_hours(recipe["target_value"], 50.50, "target_value")
        # A 13.25 score means no requalification cascade, so the chamber stands.
        assert fab.read_chamber(env.chambers[0]["id"])["qual_state"] == "QUALIFIED"

        run = fab.track_in(env.lots[0]["id"], env.steps[0]["id"], operator_id)

        assert_fields(run, status="OPEN", chamber_id=env.chambers[0]["id"])
        assert_hours(run["reserved_hours"], 2.00, "reserved_hours")
        tool = fab.read_equipment(env.equipments[0]["id"])
        assert tool["state"] == "PRODUCTIVE"
        assert_hours(tool["available_capacity_hours"], 718.00, "available_capacity_hours")
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="IN_PROCESS")


# --------------------------------------------------------------------------
# A lot release gated on the status of its plan
# --------------------------------------------------------------------------


def _planned_lot_under_a_draft_plan(fab):
    """A PLANNED lot whose plan has never been priced."""
    return build_line(
        fab,
        two_recipe_line_spec(
            commit_plan=False,
            lots=[LotSpec("LOT-001", 3, "STANDARD", release=False)],
        ),
    )


class TestLotReleaseGatedOnPlanStatus:
    def test_a_draft_plan_refuses_the_release_even_on_a_current_version(self, fab):
        """The optimistic-concurrency token is right, so only the plan status can fail.

        PRD: "Release requires the lot to be `PLANNED` — any other `flow_state`
        is `ERR_LOT_INVALID_STATE` — requires the plan to be `COMMITTED`, so a
        `DRAFT` or `CLOSED` plan is rejected with `ERR_PLAN_NOT_COMMITTED`, and
        requires the `expected_plan_version` agreement of §2.6."

        Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_while_its_plan_is_still_draft
        """
        env = _planned_lot_under_a_draft_plan(fab)
        assert_fields(env.plan, status="DRAFT", released_wafer_starts=0)
        assert env.plan["commitment_tier"] == "TIER_0"
        assert_lot_state(env.lots[0], flow_state="PLANNED")

        response = fab.client.release_lot(
            env.lots[0]["id"],
            release_lot_payload(env.plan["version"]),
            fab_planner_headers(),
        )

        body = validate_error(response, ERR_PLAN_NOT_COMMITTED, 409)
        assert body["error_id"] != ERR_STALE_PLAN_VERSION

        plan = fab.read_plan(env.plan["id"])
        assert plan["released_wafer_starts"] == 0
        assert plan["version"] == env.plan["version"]
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="PLANNED")
        assert_nulls(fab.read_lot(env.lots[0]["id"]), "released_at")

    def test_committing_the_plan_lets_the_same_release_through(self, fab):
        """Pricing the plan is the only change, and the start ledger then moves by 3.

        PRD: "On success the lot's `flow_state` becomes `RELEASED`,
        `released_at` is set to the current logical instant, the lot's `version`
        increments by 1, the plan's `released_wafer_starts` is set to the
        candidate total, and the plan's `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_while_its_plan_is_still_draft
        """
        env = _planned_lot_under_a_draft_plan(fab)
        fab.client.release_lot(
            env.lots[0]["id"],
            release_lot_payload(env.plan["version"]),
            fab_planner_headers(),
        )

        committed = fab.commit_plan(env.plan["id"])
        assert_fields(committed, status="COMMITTED", commitment_tier="TIER_2")
        assert_hours(committed["committed_hours"], 392.00, "committed_hours")

        released = fab.release_lot(env.lots[0]["id"], env.plan["id"])

        assert_lot_state(released, flow_state="RELEASED")
        assert_timestamp_equals(
            released["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )
        assert fab.read_plan(env.plan["id"])["released_wafer_starts"] == 3


# --------------------------------------------------------------------------
# A measurement gated on the status of the chart it targets
# --------------------------------------------------------------------------


def _one_suspended_chart_beside_a_healthy_one(fab):
    """Two charts watch the same step; containment has frozen only the first."""
    spec = two_recipe_line_spec(
        charts=[
            ChartSpec(step_ix=1, param_name="ETCH_DEPTH"),
            ChartSpec(step_ix=1, param_name="ETCH_CD"),
        ],
        chambers=[
            ChamberSpec("CH_L1", equipment_ix=0, recipe_ix=0),
            ChamberSpec("CH_E1", equipment_ix=1, recipe_ix=1),
            ChamberSpec("CH_E2", equipment_ix=1, recipe_ix=1),
        ],
    )
    env = build_line(fab, spec)
    operator_id = env.operators[0]["id"]

    complete_step(fab, env, step_ix=0, lot_ix=0)
    complete_step(fab, env, step_ix=0, lot_ix=1)

    # LOT-001 breaks the upper specification limit on the first chart.
    env.first_run = open_run(fab, env, step_ix=1, lot_ix=0)
    env.first_measurement = fab.measure(
        env.first_run["id"], env.charts[0]["id"], 112.0, operator_id
    )
    env.excursion = fab.contain(
        env.first_measurement["excursion_id"], "SPC_CHART", user_id=USER_QUALITY_MANAGER
    )

    # LOT-002 only now arrives at the step, so no hold ever reached it.
    env.second_run = open_run(fab, env, step_ix=1, lot_ix=1)
    return env


class TestMeasurementGatedOnChartStatus:
    def test_the_suspended_chart_refuses_a_perfectly_healthy_reading(self, fab):
        """A dead-on-target reading from an untouched lot is refused by the chart alone.

        PRD: "And the chart's `status` must be `MONITORING`; a chart frozen by
        containment rejects the reading outright with `ERR_SPC_CHART_SUSPENDED`
        and therefore contributes no state to the run rule."

        Design: Difficulty/cross_entity_state_dependency/measurement_blocked_while_that_chart_is_suspended
        """
        env = _one_suspended_chart_beside_a_healthy_one(fab)
        operator_id = env.operators[0]["id"]

        assert env.first_measurement["classification"] == "OUT_OF_SPEC"
        assert env.first_run["chamber_id"] == env.chambers[1]["id"]
        assert env.second_run["chamber_id"] == env.chambers[2]["id"]
        assert_lot_state(fab.read_lot(env.lots[1]["id"]), hold_state="NONE")

        response = fab.client.create_measurement(
            measurement_payload(env.second_run["id"], env.charts[0]["id"], 100.0),
            make_operator_headers(operator_id),
        )

        validate_error(response, ERR_SPC_CHART_SUSPENDED, 409)
        suspended = fab.read_chart(env.charts[0]["id"])
        assert_fields(suspended, status="SUSPENDED", violation_count=1)
        # The refused reading left no row and no run-rule state behind.
        assert fab.count(
            fab.client.list_measurements(
                make_operator_headers(operator_id),
                {"spc_chart_id": env.charts[0]["id"]},
            )
        ) == 1
        assert fab.read_step_run(env.second_run["id"])["status"] == "OPEN"

    def test_the_sibling_chart_on_the_same_step_still_accepts_it(self, fab):
        """Suspension is per chart, not per step, so the very next call is classified.

        PRD: "Classification runs synchronously, before the measurement row is
        persisted. Let the deviation be the reading minus the chart's `target`.
        `deviation_sigma` is the absolute deviation divided by `sigma`, rounded
        to 4 decimal places."

        Design: Difficulty/cross_entity_state_dependency/measurement_blocked_while_that_chart_is_suspended
        """
        env = _one_suspended_chart_beside_a_healthy_one(fab)
        operator_id = env.operators[0]["id"]
        fab.client.create_measurement(
            measurement_payload(env.second_run["id"], env.charts[0]["id"], 100.0),
            make_operator_headers(operator_id),
        )

        accepted = fab.measure(
            env.second_run["id"], env.charts[1]["id"], 100.0, operator_id
        )

        assert accepted["classification"] == "IN_CONTROL"
        assert_ratio(accepted["deviation_sigma"], 0.0000, "deviation_sigma")
        assert_nulls(accepted, "excursion_id")

        healthy = fab.read_chart(env.charts[1]["id"])
        assert_fields(
            healthy,
            status="MONITORING",
            violation_count=0,
            consecutive_same_side_count=0,
            last_side="NONE",
        )
        assert fab.count(
            fab.client.list_measurements(
                make_operator_headers(operator_id),
                {"spc_chart_id": env.charts[1]["id"]},
            )
        ) == 1
        assert_lot_state(fab.read_lot(env.lots[1]["id"]), hold_state="NONE")
