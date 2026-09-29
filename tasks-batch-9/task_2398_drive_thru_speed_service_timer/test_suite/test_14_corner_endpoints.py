"""Endpoint shapes: an update, an action with a side effect, a computed read, a link.

These check what each endpoint kind is contractually obliged to return, not just
that it returned something.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COACH_HEADERS,
    make_operator_headers,
)


class TestRestaurantAdjustment:
    """The store update writes two fields and re-derives everything downstream."""

    def test_switching_the_basis_and_the_budget_rederives_the_ledger(
        self, api: DriveThruApiClient
    ):
        """PRD §3.1: "Later, an `Operator` may adjust two store settings:
        `staffing_basis` (switching between `OBSERVED` and `FORECAST_ADJUSTED`) and
        `labor_minutes_budget`. Both fields are optional on that adjustment, and it
        re-runs the rollup chain end to end — the effective car rate, the volume tier,
        the outside order-taker requirement and the posture — and increments the store's
        `version` by 1."
        PRD §3.4: "Across all four states the invariant that must hold after every
        request is that `labor_minutes_budget` equals `labor_minutes_committed` plus
        `labor_minutes_available`; deployments in `PLANNED` and `ABORTED` contribute zero
        to the committed side."
        PRD §3.7: "When there are no candidates at all, there is no override in force,
        and both the relief contribution and the delta contribution are 0.00."

        Design: Corner/endpoints/ep_restaurant_patch_updates_staffing_basis_and_budget
        """
        fx.setup_single_unbounded_band(api)
        original = fx.register_restaurant(api, "C-2398-46", name="Corner Patch Store")
        assert original["staffing_basis"] == "OBSERVED", original
        a.assert_labor_ledger(original, committed=0, available=300)
        version_before = original["version"]

        updated = validate_success(
            api.patch_restaurant(
                original["id"],
                f.restaurant_patch_body(
                    staffing_basis="FORECAST_ADJUSTED", labor_minutes_budget=500
                ),
                make_operator_headers(original["id"]),
            )
        )

        assert updated["staffing_basis"] == "FORECAST_ADJUSTED", updated
        assert updated["labor_minutes_budget"] == 500, updated
        # Available is re-derived from the new budget, not carried over from 300.
        a.assert_labor_ledger(updated, committed=0, available=500)
        assert updated["version"] == version_before + 1, updated
        a.assert_rollup(
            updated,
            cars_per_hour_effective=0.0,
            volume_tier="TIER_1",
            service_posture="OPEN",
        )

        reread = fx.get_restaurant(api, original["id"])
        assert reread["staffing_basis"] == "FORECAST_ADJUSTED", reread
        assert reread["labor_minutes_budget"] == 500, reread
        assert reread["version"] == updated["version"], reread


class TestDeploymentRelease:
    """Release swaps the planned commitment for the actual charge."""

    def test_releasing_after_twenty_five_and_a_half_minutes_charges_twenty_six(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "It stamps `released_at` from the logical clock and sets
        `labor_minutes_charged` to the lesser of `planned_minutes` and the elapsed
        activation time in seconds divided by 60 rounded up to the next whole minute."
        And: "The member returns to `AVAILABLE`, `labor_minutes_charged` is added to
        their `deployed_minutes_today`, and because the deployment has left `ACTIVE` it
        stops contributing `planned_minutes` to the store ledger and starts contributing
        `labor_minutes_charged` instead."

        Design: Corner/endpoints/ep_deployment_release_charges_actual_not_planned_minutes
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-47",
            staff_name="Corner Lowell",
            name="Corner Release Store",
        )
        fx.set_clock(api, fx.at(11, 0, 0))
        planned = fx.plan_deployment(api, ctx, fx.at(11, 0, 0), fx.at(12, 0, 0))
        a.assert_deployment_charge(planned, planned_minutes=60)
        fx.activate_deployment(api, ctx, planned["id"])
        active_store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(active_store, committed=60)
        a.assert_rollup(active_store, deployed_oot_count=1)

        fx.set_clock(api, fx.at(11, 25, 30))
        released = validate_success(
            api.release_deployment(planned["id"], ctx.leader_headers)
        )

        assert released["deployment_state"] == "RELEASED", released
        assert released["released_at"] == fx.at(11, 25, 30), released
        # 1530 elapsed seconds is 25.5 minutes, which rounds up to 26.
        a.assert_deployment_charge(released, labor_minutes_charged=26)

        member = validate_success(api.get_staff_member(ctx.staff_id, ADMIN_HEADERS))
        assert member["staff_state"] == "AVAILABLE", member
        assert member["deployed_minutes_today"] == 26, member

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store, committed=26, available=274)
        a.assert_rollup(store, deployed_oot_count=0, service_posture="OPEN")


class TestTimerLoopComputedRead:
    """The loop read hands back numbers no client ever supplied."""

    def test_the_single_read_carries_every_derived_segment_and_flag(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "It stamps `depart_at`, computes `window_seconds` as `depart_at`
        minus `window_arrive_at`, computes `total_seconds` as `depart_at` minus
        `arrive_at`, and computes `adjusted_total_seconds`."
        And: "`breach_flags` is the subset of `[GREET, ORDER, PULL_FORWARD, WINDOW]` —
        always reported in exactly that order — whose measured seconds are *strictly
        greater* than the corresponding pinned target: `GREET` when `greet_seconds`
        exceeds `greet_target_pinned`, `ORDER` when `order_seconds` exceeds
        `order_target_pinned`, `PULL_FORWARD` when `pull_forward_seconds` exceeds
        `pull_forward_target_pinned`, `WINDOW` when `window_seconds` exceeds
        `window_target_pinned`."

        Design: Corner/endpoints/ep_timer_loop_get_returns_computed_segments_and_flags
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-48",
            staff_name="Corner Sena",
            name="Corner Computed Read Store",
        )
        driven = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=fx.at(11, 2, 0),
            depart_at=fx.at(11, 4, 10),
            order_items_count=3,
        )
        a.assert_pinned_targets(driven, 25, 95, 40, 75, total=235)

        loop = validate_success(api.get_timer_loop(driven["id"], ADMIN_HEADERS))

        a.assert_loop_states(loop, timing_state="CLOSED", accuracy_state="VERIFIED")
        a.assert_loop_segments(
            loop,
            greet_seconds=20,
            order_seconds=40,
            pull_forward_seconds=60,
            window_seconds=130,
            total_seconds=250,
            adjusted_total_seconds=250,
            merge_wait_seconds=None,
        )
        a.assert_breach_flags(loop, ["PULL_FORWARD", "WINDOW"])

        rows, meta = validate_paginated(
            api.list_timer_loops(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "timing_state": "CLOSED"},
            )
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == loop["id"], rows
        a.assert_loop_segments(rows[0], total_seconds=250, window_seconds=130)
        a.assert_breach_flags(rows[0], ["PULL_FORWARD", "WINDOW"])


class TestCoachingCreationLinks:
    """The intervention hangs off a published report and a rostered coachee."""

    def test_the_two_links_supply_the_store_and_the_window_gap(
        self, api: DriveThruApiClient
    ):
        """PRD §3.9: "The server copies the report's `restaurant_id` onto the
        intervention, sets `ci_state` to `DRAFT`, sets `revision_count` to 0, and leaves
        `issued_by_user_id`, `contest_reason` and `closure_note` null."
        And: "For the four timing segments it is the mean of the matching measured
        duration across the input set (`greet_seconds` for `GREET`, `order_seconds` for
        `ORDER`, `pull_forward_seconds` for `PULL_FORWARD`, `window_seconds` for
        `WINDOW`) minus the mean of the matching pinned target across the same input set
        (`greet_target_pinned`, `order_target_pinned`, `pull_forward_target_pinned` and
        `window_target_pinned` respectively), floored at 0 so a segment that beat its
        target contributes no gap."
        And: "The intervention's `tier` follows from the score: `TIER_C_RETRAIN` when
        `priority_score` is at least 70, otherwise `TIER_B_COACH` when it is at least
        40, otherwise `TIER_A_OBSERVE`."

        Design: Corner/endpoints/ep_coaching_create_links_report_and_staff_member
        """
        fx.setup_four_tier_bands(api)
        ctx = fx.setup_store(
            api,
            "C-2398-49",
            staff_name="Corner Mira",
            name="Corner Coaching Link Store",
        )
        fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=fx.at(11, 2, 0),
            depart_at=fx.at(11, 4, 10),
            order_items_count=3,
        )
        fx.set_clock(api, fx.at(11, 5, 0))
        report = fx.create_published_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
        assert report["report_state"] == "PUBLISHED", report
        a.assert_report_metrics(
            report,
            cars_served=1,
            avg_metric_seconds=250.0,
            target_total_seconds_effective=251,
            attainment_pct=100.40,
            attainment_band="GREEN",
        )

        coaching = validate_success(
            api.create_coaching_intervention(
                f.coaching_body(report["id"], ctx.staff_id, "WINDOW"), COACH_HEADERS
            ),
            expected_status=201,
        )

        assert coaching["ci_state"] == "DRAFT", coaching
        assert coaching["revision_count"] == 0, coaching
        assert coaching["throughput_report_id"] == report["id"], coaching
        assert coaching["staff_member_id"] == ctx.staff_id, coaching
        # The store came through the report, not from the request body.
        assert coaching["restaurant_id"] == ctx.restaurant_id, coaching
        # A 130-second window against a 75-second pinned target saturates the gap
        # component at 60, and the GREEN band adds 3.
        a.assert_coaching_scoring(
            coaching,
            segment_gap_seconds=55,
            priority_score=63.00,
            tier="TIER_B_COACH",
        )

        rows, meta = validate_paginated(
            api.list_coaching_interventions(
                ADMIN_HEADERS,
                {
                    "throughput_report_id": report["id"],
                    "staff_member_id": ctx.staff_id,
                },
            )
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == coaching["id"], rows
