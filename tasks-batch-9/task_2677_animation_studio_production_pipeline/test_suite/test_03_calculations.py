"""Calculation tests: reuse credit, schedule-driven planned value and render cost."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_earned_value_report,
    assert_instant,
    assert_two_decimal,
)
from test_helpers.constants import (
    CLOCK_START,
    JOB_COMPLETED,
    JOB_RESERVED,
    VARIANT_STAGE_WEIGHT,
)
from test_helpers.test_users import PRODUCTION_MANAGER_HEADERS


def _single_gate_active_production(client, **overrides):
    overrides.setdefault("gate_types", ["SCRIPT"])
    return fx.active_production(client, **overrides)


def _shot_with_layout_in_progress(client, production_id):
    shot = fx.create_shot(
        client,
        production_id,
        shot_code="AD01_010_0010",
        budget_cents=1000000,
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    layout = fx.task_for_stage(client, shot["id"], "LAYOUT")
    fx.assign_task(client, layout["id"])
    return shot, layout


class TestAssetReuseCredit:
    def test_discount_shrinks_as_the_reuse_chain_deepens(self, client):
        """Depth is counted in edges along the reuse chain, the root discounts nothing, and
        a deeper asset keeps more of its own points than a shallower one.

        PRD: "Otherwise the discount depends on depth alone: 0.40 at depth 1, 0.25 at depth
        2, and 0.10 at depth 3 or deeper."
        PRD: "The discount therefore shrinks as reuse gets more distant: a base of 200.00
        yields 120.00 at depth 1, 150.00 at depth 2 and 180.00 at depth 3, and depth is
        never averaged over the chain."

        Design: Corner/calculations/asset_reuse_discount_decreases_with_chain_depth
        """
        production = fx.open_production(client, title="Aurora Drift", production_code="AD01")

        root = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_ENV_CITY",
            asset_type="ENVIRONMENT",
            base_complexity_points=300.00,
        )
        assert root["reuse_depth"] == 0
        assert_two_decimal(root["reuse_discount_pct"], 0.00, "reuse_discount_pct")
        assert_two_decimal(
            root["effective_complexity_points"], 300.00, "effective_complexity_points"
        )
        fx.publish_asset(client, root["id"])
        fx.library_approve_asset(client, root["id"])

        middle = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_ENV_ALLEY",
            asset_type="ENVIRONMENT",
            base_complexity_points=200.00,
            derived_from_asset_id=root["id"],
        )
        assert middle["reuse_depth"] == 1
        assert_two_decimal(middle["reuse_discount_pct"], 0.40, "reuse_discount_pct")
        assert_two_decimal(
            middle["effective_complexity_points"], 120.00, "effective_complexity_points"
        )
        fx.publish_asset(client, middle["id"])
        fx.library_approve_asset(client, middle["id"])

        leaf = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_ENV_DOORWAY",
            asset_type="ENVIRONMENT",
            base_complexity_points=200.00,
            derived_from_asset_id=middle["id"],
        )
        assert leaf["reuse_depth"] == 2
        assert_two_decimal(leaf["reuse_discount_pct"], 0.25, "reuse_discount_pct")
        assert_two_decimal(
            leaf["effective_complexity_points"], 150.00, "effective_complexity_points"
        )
        assert leaf["reuse_source_stale"] is False
        assert (
            leaf["effective_complexity_points"] > middle["effective_complexity_points"]
        ), "the deeper asset keeps more points, so the discount is not accumulated"

        middle_again = fx.read_asset(client, middle["id"])
        assert middle_again["reuse_depth"] == 1
        assert_two_decimal(
            middle_again["effective_complexity_points"],
            120.00,
            "effective_complexity_points",
        )


class TestShotPlannedValue:
    def test_planned_value_accrues_against_the_logical_clock_alone(self, client):
        """The planned value is a pure function of the clock against the planned span, so a
        quarter of the way through the window a shot with no work has earned nothing but
        planned a quarter of its budget.

        PRD: "`bcws_cents` is the shot's `budget_cents` multiplied by that clamped fraction,
        rounded half-up to a whole cent."
        PRD: "The schedule performance index `spi` is `bcwp_cents` divided by `bcws_cents`,
        rounded half-up to four decimal places, and is **null** when `bcws_cents` is 0."

        Design: Corner/calculations/shot_bcws_accrues_linearly_against_the_clock
        """
        production = _single_gate_active_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            budget_cents=1000000,
            planned_start_at=CLOCK_START,
            planned_finish_at="2026-09-30T00:00:00Z",
        )

        at_start = validate_success(
            client.get_shot_earned_value(shot["id"], PRODUCTION_MANAGER_HEADERS)
        )
        assert_cents(at_start["bcws_cents"], 0, "bcws_cents")
        assert at_start["spi"] is None

        clock = fx.move_clock(client, "2026-08-16T00:00:00Z")
        assert_instant(clock["current_utc"], "2026-08-16T00:00:00Z", "current_utc")

        report = validate_success(
            client.get_shot_earned_value(shot["id"], PRODUCTION_MANAGER_HEADERS)
        )
        assert_earned_value_report(
            report,
            VARIANT_STAGE_WEIGHT,
            bcws_cents=250000,
            bcwp_cents=0,
            acwp_cents=0,
            cpi=None,
            spi=0.0000,
        )
        assert_instant(report["computed_at"], "2026-08-16T00:00:00Z", "computed_at")


class TestRenderCostConstants:
    def test_priority_multiplier_is_applied_before_the_cent_rounding(self, client):
        """Identical render geometry priced at three priorities produces three different
        per-frame cents, because the multiplier lands before the rounding step.

        PRD: "The raw per-frame cost in cents is the pool's `cost_per_core_hour_cents`,
        multiplied by those core-seconds per frame, divided by the 3,600 seconds in an
        hour, and then multiplied by the priority multiplier — 0.80 for `LOW`, 1.00 for
        `NORMAL`, 1.35 for `HIGH` and 1.75 for `CRITICAL`."
        PRD: "**Step one** rounds that raw per-frame value half-up to a whole cent and
        stores it as `cost_per_frame_cents`."

        Design: Corner/calculations/render_priority_multiplier_constants_applied
        """
        pool = fx.create_pool(
            client, name="FARM_A", total_cores=100, cost_per_core_hour_cents=175
        )
        production = _single_gate_active_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        _, layout = _shot_with_layout_in_progress(client, production["id"])

        def reserve(priority, day):
            version = fx.read_pool(client, pool["id"])["version"]
            return validate_success(
                client.create_render_job(
                    {
                        "render_pool_id": pool["id"],
                        "shot_stage_task_id": layout["id"],
                        "priority": priority,
                        "requested_cores": 3,
                        "window_start": f"2026-08-{day}T00:00:00Z",
                        "window_end": f"2026-08-{day}T06:00:00Z",
                        "frame_count": 120,
                        "seconds_per_frame": 50,
                        "expected_render_pool_version": version,
                    },
                    PRODUCTION_MANAGER_HEADERS,
                ),
                201,
            )

        low = reserve("LOW", "02")
        assert_cents(low["cost_per_frame_cents"], 6, "cost_per_frame_cents")
        assert_cents(low["estimated_cost_cents"], 720, "estimated_cost_cents")
        assert_two_decimal(low["committed_core_hours"], 18.00, "committed_core_hours")

        normal = reserve("NORMAL", "03")
        assert_cents(normal["cost_per_frame_cents"], 7, "cost_per_frame_cents")
        assert_cents(normal["estimated_cost_cents"], 840, "estimated_cost_cents")

        critical = reserve("CRITICAL", "04")
        assert_cents(critical["cost_per_frame_cents"], 13, "cost_per_frame_cents")
        assert_cents(critical["estimated_cost_cents"], 1560, "estimated_cost_cents")
        assert critical["status"] == JOB_RESERVED
        assert critical["preempted_by_render_job_id"] is None

        _, meta = validate_paginated(
            client.list_render_jobs(
                PRODUCTION_MANAGER_HEADERS,
                {"render_pool_id": pool["id"], "status": "PREEMPTED"},
            )
        )
        assert meta["total_count"] == 0


class TestRenderCostLedgerTransition:
    def test_a_reservation_is_committed_cost_until_it_settles(self, client):
        """A reserved job's estimate sits in committed cost and contributes nothing to
        actual cost until settlement moves the same amount across.

        PRD: "Only `COMPLETED` and `FAILED` jobs contribute to `render_cost_actual_cents`;
        `RESERVED` jobs sit in `render_cost_committed_cents` and never touch actual cost."
        PRD: "Settlement stores `actual_seconds_per_frame`, recomputes
        `cost_per_frame_cents` from the actual seconds under exactly the same two-step
        rounding rule, and sets `final_cost_cents` to that per-frame figure multiplied by
        `frames_completed` — so a failed job is billed for the frames it actually produced,
        a partial settlement rather than a write-off."

        Design: Corner/calculations/reserved_render_job_excluded_from_acwp_until_settled
        """
        pool = fx.create_pool(
            client, name="FARM_A", total_cores=100, cost_per_core_hour_cents=175
        )
        production = _single_gate_active_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        shot, layout = _shot_with_layout_in_progress(client, production["id"])

        job = validate_success(
            client.create_render_job(
                {
                    "render_pool_id": pool["id"],
                    "shot_stage_task_id": layout["id"],
                    "priority": "NORMAL",
                    "requested_cores": 3,
                    "window_start": "2026-08-02T00:00:00Z",
                    "window_end": "2026-08-02T06:00:00Z",
                    "frame_count": 120,
                    "seconds_per_frame": 50,
                    "expected_render_pool_version": pool["version"],
                },
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        assert_cents(job["estimated_cost_cents"], 840, "estimated_cost_cents")
        assert job["final_cost_cents"] is None

        before = fx.read_shot(client, shot["id"])
        assert_cents(before["render_cost_committed_cents"], 840, "render_cost_committed_cents")
        assert_cents(before["render_cost_actual_cents"], 0, "render_cost_actual_cents")
        report_before = validate_success(
            client.get_shot_earned_value(shot["id"], PRODUCTION_MANAGER_HEADERS)
        )
        assert_cents(report_before["acwp_cents"], 0, "acwp_cents")

        settled = validate_success(
            client.complete_render_job(
                job["id"],
                {
                    "outcome": "COMPLETED",
                    "actual_seconds_per_frame": 50,
                    "frames_completed": 120,
                },
                PRODUCTION_MANAGER_HEADERS,
            )
        )
        assert settled["status"] == JOB_COMPLETED
        assert_cents(settled["final_cost_cents"], 840, "final_cost_cents")

        after = fx.read_shot(client, shot["id"])
        assert_cents(after["render_cost_committed_cents"], 0, "render_cost_committed_cents")
        assert_cents(after["render_cost_actual_cents"], 840, "render_cost_actual_cents")
        report_after = validate_success(
            client.get_shot_earned_value(shot["id"], PRODUCTION_MANAGER_HEADERS)
        )
        assert_cents(report_after["acwp_cents"], 840, "acwp_cents")
