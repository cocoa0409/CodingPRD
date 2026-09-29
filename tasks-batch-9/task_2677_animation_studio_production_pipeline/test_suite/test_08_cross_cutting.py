"""Cross-cutting tests: optimistic concurrency, version counters and rollup reconciliation."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_budget_position,
    assert_four_decimal,
    assert_instant,
    assert_two_decimal,
)
from test_helpers.constants import (
    CALIBRATION_CALIBRATED,
    CALIBRATION_UNCALIBRATED,
    DELIVERABLE_DRAFT,
    JOB_RESERVED,
)
from test_helpers.test_users import (
    ARTIST_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
)


class TestRenderPoolOptimisticConcurrency:
    def test_a_replayed_pool_version_is_the_only_thing_that_stops_a_second_reservation(
        self, client
    ):
        """Two reservations over the same window for the same task are legitimate, so the
        rejected middle attempt can only be the version guard, and it changes nothing.

        PRD: "Every accepted reservation, settlement, cancellation and preemption on that pool
        advances `RenderPool.version` by 1, so if any of those has happened since the client's
        read, the value no longer matches and the reservation is rejected with
        `ERR_STALE_RENDER_POOL_VERSION` (HTTP 412) without touching the pool's
        `committed_core_hours` or `reserved_job_count`."
        PRD: "A shot may legitimately hold several reservations over the same window for the
        same stage task, which is exactly why no `RenderJob` state precondition would catch the
        duplicate: only the pool version does."

        Design: Corner/cross_cutting_complexity_layers/render_job_create_rejects_stale_pool_version
        """
        pool = fx.create_pool(
            client, name="FARM_A", total_cores=100, cost_per_core_hour_cents=175
        )
        first_version = pool["version"]
        assert first_version == 1

        production = fx.active_production(
            client, title="Aurora Drift", production_code="AD01", gate_types=["SCRIPT"]
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")
        fx.assign_task(client, task["id"])

        def reservation(expected_version):
            return f.render_job_payload(
                pool["id"],
                task["id"],
                expected_version,
                requested_cores=3,
                window_start="2026-08-02T00:00:00Z",
                window_end="2026-08-02T06:00:00Z",
                frame_count=120,
                seconds_per_frame=50,
            )

        first = validate_success(
            client.create_render_job(reservation(first_version), PRODUCTION_MANAGER_HEADERS),
            201,
        )
        assert first["status"] == JOB_RESERVED

        after_first = fx.read_pool(client, pool["id"])
        assert after_first["version"] == 2
        assert_two_decimal(after_first["committed_core_hours"], 18.00, "committed_core_hours")
        assert after_first["reserved_job_count"] == 1

        validate_error(
            client.create_render_job(reservation(first_version), PRODUCTION_MANAGER_HEADERS),
            "ERR_STALE_RENDER_POOL_VERSION",
            412,
        )
        inert = fx.read_pool(client, pool["id"])
        assert inert["version"] == 2
        assert_two_decimal(inert["committed_core_hours"], 18.00, "committed_core_hours")
        assert inert["reserved_job_count"] == 1

        second = validate_success(
            client.create_render_job(reservation(2), PRODUCTION_MANAGER_HEADERS), 201
        )
        assert second["status"] == JOB_RESERVED
        assert_two_decimal(second["committed_core_hours"], 18.00, "committed_core_hours")

        after_second = fx.read_pool(client, pool["id"])
        assert after_second["version"] == 3
        assert_two_decimal(
            after_second["committed_core_hours"], 36.00, "committed_core_hours"
        )
        assert after_second["reserved_job_count"] == 2


class TestDeliverableOptimisticConcurrency:
    def test_the_stale_version_outranks_the_group_conflict(self, client):
        """Batching two creates from one read fails the second on the version echo, and even a
        request that would also collide with an in-flight version reports the 412 instead.

        PRD: "Each accepted deliverable creation advances `Production.version` by 1, so a
        create carrying an older value is rejected with `ERR_STALE_PRODUCTION_VERSION` (HTTP
        412) and no `version_index` is consumed by the rejected attempt."
        PRD: "The thirty-five checks below are evaluated **strictly in the order listed**, and
        the first one that fails is the one reported; later checks never run."

        Design: Corner/cross_cutting_complexity_layers/deliverable_create_rejects_stale_production_version_before_version_conflict
        """
        production = fx.active_production(
            client,
            title="Copper Kite",
            production_code="AD07",
            format="SHORT",
            budget_cents=20000000,
            render_allowance_cents=1000000,
            gate_types=["SCRIPT"],
            approved_color_spaces=["ACEScg", "Rec709"],
        )
        stale_version = fx.read_production(client, production["id"])["version"]

        proxy = fx.create_deliverable(
            client,
            production["id"],
            expected_version=stale_version,
            deliverable_type="PROXY_MP4",
            color_space="Rec709",
            resolution="1920x1080",
            bit_depth=8,
        )
        assert proxy["version_label"] == "v01"

        stem_payload = f.deliverable_payload(
            production["id"],
            stale_version,
            deliverable_type="AUDIO_STEM",
            color_space="Rec709",
            resolution="1920x1080",
        )
        validate_error(
            client.create_deliverable(stem_payload, PRODUCTION_MANAGER_HEADERS),
            "ERR_STALE_PRODUCTION_VERSION",
            412,
        )

        duplicate_group = f.deliverable_payload(
            production["id"],
            stale_version,
            deliverable_type="PROXY_MP4",
            color_space="Rec709",
            resolution="1920x1080",
            bit_depth=8,
        )
        validate_error(
            client.create_deliverable(duplicate_group, PRODUCTION_MANAGER_HEADERS),
            "ERR_STALE_PRODUCTION_VERSION",
            412,
        )

        fresh_version = fx.read_production(client, production["id"])["version"]
        stem_payload["expected_production_version"] = fresh_version
        stem = validate_success(
            client.create_deliverable(stem_payload, PRODUCTION_MANAGER_HEADERS), 201
        )
        assert stem["version_label"] == "v01"
        assert stem["status"] == DELIVERABLE_DRAFT

        _, meta = validate_paginated(
            client.list_deliverables(
                PRODUCTION_MANAGER_HEADERS, {"production_id": production["id"]}
            )
        )
        assert meta["total_count"] == 2


class TestVersionCounterSemantics:
    def test_version_counts_writes_and_ignores_reads(self, client):
        """Reads leave the counter alone even though each one re-derives the calibration status,
        while two calibrations at the very same instant are still two writes.

        PRD: "`version` is an integer that begins at 1 when the row is created and increases by
        exactly 1 on every accepted mutation of that row, including mutations reached through a
        cascade from another entity's operation."

        Design: Corner/cross_cutting_complexity_layers/entity_version_increments_on_every_write_and_not_on_reads
        """
        room = fx.create_room(client, name="SCREEN_1", seat_capacity=10)
        assert room["version"] == 1

        first_read = fx.read_room(client, room["id"])
        assert first_read["version"] == 1
        assert first_read["calibration_status"] == CALIBRATION_UNCALIBRATED

        first_calibration = validate_success(
            client.calibrate_screening_room(room["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert first_calibration["version"] == 2
        assert first_calibration["calibration_status"] == CALIBRATION_CALIBRATED

        assert fx.read_room(client, room["id"])["version"] == 2

        second_calibration = validate_success(
            client.calibrate_screening_room(room["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert second_calibration["version"] == 3
        assert_instant(second_calibration["last_calibrated_at"], "2026-08-01T00:00:00Z")

        assert fx.read_room(client, room["id"])["version"] == 3


class TestProductionRollupReconciliation:
    def test_the_show_recomputes_its_rollups_from_its_children(self, client):
        """Shot count, actual cost, planned value and the budget ledger are all re-derived from
        the children rather than incremented, so one logged day of work and a clock move show
        up together on the parent.

        PRD: "At the production level the same five figures are simple aggregates over the
        show's shots: `bcwp_cents`, `bcws_cents` and `acwp_cents` are the sums of the shots'
        corresponding fields — always the persisted `STAGE_WEIGHT` figures — and the
        production's `cpi` and `spi` are derived from those sums under exactly the same
        four-decimal rounding and the same null-on-zero-denominator rules."
        PRD: "All of it is reconciled synchronously: by the time a mutating request returns,
        every ancestor figure it disturbed has been recomputed, and every row that was
        recomputed has had its `version` advanced and its `updated_at` refreshed."

        Design: Corner/cross_cutting_complexity_layers/production_rollups_reconcile_after_each_shot_and_hour_is_added
        """
        production = fx.open_production(
            client,
            title="Aurora Drift",
            production_code="AD01",
            gate_types=["SCRIPT"],
            budget_cents=100000000,
        )
        assert production["shot_count"] == 0
        assert production["acwp_cents"] == 0
        assert production["direct_committed_cents"] == 0
        fx.activate_production(client, production["id"])

        first_shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            budget_cents=1000000,
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        after_one = fx.read_production(client, production["id"])
        assert after_one["shot_count"] == 1
        assert after_one["completed_shot_count"] == 0

        fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0020",
            frame_count=96,
            budget_cents=1000000,
            planned_finish_at="2026-09-30T00:00:00Z",
        )

        task = fx.task_for_stage(client, first_shot["id"], "LAYOUT")
        fx.assign_task(client, task["id"])
        logged = validate_success(
            client.log_hours(task["id"], f.log_hours_payload(10.0), ARTIST_HEADERS)
        )
        assert_two_decimal(logged["actual_hours"], 10.00, "actual_hours")

        fx.move_clock(client, "2026-08-16T00:00:00Z")
        rolled_up = fx.read_production(client, production["id"])
        assert rolled_up["shot_count"] == 2
        assert rolled_up["acwp_cents"] == 90000
        assert rolled_up["bcws_cents"] == 500000
        assert rolled_up["bcwp_cents"] == 0
        assert_four_decimal(rolled_up["spi"], 0.0000, "spi")
        assert_four_decimal(rolled_up["cpi"], 0.0000, "cpi")
        assert_budget_position(rolled_up, 90000, expected_overhead_cents=13500)
        assert rolled_up["available_cents"] == 109896500
