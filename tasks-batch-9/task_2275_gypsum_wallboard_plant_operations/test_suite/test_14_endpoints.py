"""Endpoint shapes: the disposition that fans out to three transitions from one action
field, the run read that exposes the whole computed capacity chain, the load order as a
body-supplied join, the clock as the only source of temporal movement, and one board
line reachable three ways.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    BoardLineStatus,
    DispositionAction,
    LoadOrderStatus,
    OutageStatus,
    ProductionPosture,
    QualityState,
    RunStatus,
    SaleableGrade,
    assert_board_line,
    assert_load_order,
    assert_production_run,
    factories,
    fixtures,
    is_iso8601_timestamp,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestQualityDispositionFanOut:
    """One endpoint, three declared transitions selected by `action`; only SCRAP moves
    volume into `scrapped_msf` and cancels the freight."""

    def test_the_scrap_action_zeroes_the_volume_and_cancels_the_staged_load(
        self, api: ApiClient
    ) -> None:
        """290.000 MSF moves into `scrapped_msf` and the trailer is cancelled by rule.

        PRD: "A `SCRAP` disposition moves the run `HELD → SCRAPPED`, which is terminal. It writes the run's current `net_good_msf` into `scrapped_msf`, then sets `net_good_msf` to `0.000` and `available_msf` to `0.000`, sets `saleable_grade` to `SCRAP`, and cancels every load order of the run whose `status` is `STAGED`, `HELD` or `LOADED`, writing the literal text `RUN_SCRAPPED` into each one's `cancel_reason`."

        Design: Corner/endpoints/quality_disposition_endpoint_selects_its_transition_from_the_action_payload
        """
        world = fixtures.held_run(api)
        world.load = fixtures.stage_load(api, world, bundles_count=5)
        assert world.load["status"] == LoadOrderStatus.STAGED.value
        assert world.read_run()["net_good_msf"] == pytest.approx(290.000, abs=0.0005)

        scrapped = validate_success(
            api.disposition_quality(
                world.run_id,
                factories.disposition_payload(
                    action=DispositionAction.SCRAP.value,
                    disposition_note="core delamination across the lot",
                ),
                test_users.QUALITY_MANAGER,
            ),
            200,
        )

        assert_production_run(scrapped)
        assert scrapped["quality_state"] == QualityState.SCRAPPED.value
        assert scrapped["saleable_grade"] == SaleableGrade.SCRAP.value
        assert scrapped["scrapped_msf"] == pytest.approx(290.000, abs=0.0005)
        assert scrapped["net_good_msf"] == pytest.approx(0.000, abs=0.0005)
        assert scrapped["available_msf"] == pytest.approx(0.000, abs=0.0005)
        assert scrapped["status"] == RunStatus.COMPLETED.value, (
            "the lifecycle dimension is untouched by a disposition"
        )

        load = world.read_load()
        assert load["status"] == LoadOrderStatus.CANCELLED.value
        assert load["cancel_reason"] == "RUN_SCRAPPED"

        assert world.read_plant()["held_run_count"] == 0


class TestProductionRunProjection:
    """The run read is a computed projection: the whole six-step chain is auditable in
    one body."""

    def test_the_run_read_exposes_every_step_of_the_capacity_chain(
        self, api: ApiClient
    ) -> None:
        """A cold start clamps 300.000 requested MSF against 312.000 of capacity.

        PRD: "The apparent circularity — how much board a window can hold depends on how many minutes changeover eats, which depends on which run precedes this one — is resolved exactly by following these steps in sequence, each step reading only the outputs of earlier steps."

        Design: Corner/endpoints/get_production_run_exposes_the_whole_computed_capacity_chain
        """
        world = fixtures.scheduled_run(api)

        run = validate_success(api.get_production_run(world.run_id, test_users.PLANT_MANAGER), 200)

        assert_production_run(run)
        assert run["prior_run_id"] is None
        assert run["changeover_minutes"] == 45
        assert run["gap_minutes"] is None, "a cold start has no predecessor to measure from"
        assert run["in_window_changeover_minutes"] == 45
        assert run["available_minutes"] == 195, "240 window minutes less the 45 absorbed"
        assert run["capacity_msf"] == pytest.approx(312.000, abs=0.0005)
        assert run["effective_planned_msf"] == pytest.approx(300.000, abs=0.0005)
        assert run["stucco_reserved_tons"] == pytest.approx(202.500, abs=0.0005)
        assert run["kiln_energy_mmbtu"] == pytest.approx(518.018, abs=0.0005)
        assert run["kiln_energy_cost_usd"] == pytest.approx(2175.68, abs=0.005)
        assert run["status"] == RunStatus.SCHEDULED.value
        assert run["quality_state"] == QualityState.UNTESTED.value


class TestLoadOrderJoin:
    """Both of the load order's foreign keys arrive in the body, so both misses are
    reference errors rather than path errors."""

    def test_unknown_body_references_are_reference_errors_and_the_valid_pair_joins(
        self, api: ApiClient
    ) -> None:
        """Geometry comes from the run's SKU and pricing from the market.

        PRD: "Body-supplied reference resolution.** Foreign keys named in the body — `plant_id`, `line_id`, `product_spec_id`, `calciner_batch_id`, `lot_id`, `run_id`, `market_id` — must resolve, else `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/endpoints/load_order_links_a_run_to_a_market_and_unknown_ids_return_reference_not_found
        """
        world = fixtures.released_run(api)

        unknown_market = validate_error(
            api.create_load_order(
                factories.load_order_payload(world.run_id, NON_EXISTENT_UUID, 5, 48),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.REFERENCE_NOT_FOUND.value,
            404,
        )
        unknown_run = validate_error(
            api.create_load_order(
                factories.load_order_payload(NON_EXISTENT_UUID, world.market_id, 5, 48),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.REFERENCE_NOT_FOUND.value,
            404,
        )
        assert unknown_market["error_id"] != ApiErrorId.LOAD_ORDER_NOT_FOUND.value
        assert unknown_run["error_id"] != ApiErrorId.RUN_NOT_FOUND.value, (
            "a body-supplied run reference is not a path identifier"
        )

        load = validate_success(
            api.create_load_order(
                factories.load_order_payload(world.run_id, world.market_id, 5, 48),
                test_users.PRODUCTION_SCHEDULER,
            ),
            201,
        )
        assert_load_order(load)
        assert load["run_id"] == world.run_id
        assert load["market_id"] == world.market_id
        assert load["board_msf_each"] == pytest.approx(0.048000, abs=0.0000005)
        assert load["bundle_weight_lb"] == pytest.approx(3686.40, abs=0.005)
        assert load["quoted_freight_usd"] == pytest.approx(425.00, abs=0.005), (
            "the five-bundle charge is raised to the market's minimum"
        )

        _, meta = validate_paginated(
            api.list_load_orders(test_users.PRODUCTION_SCHEDULER, params={"run_id": world.run_id})
        )
        assert meta["total_count"] == 1


class TestClockEndpoint:
    """Nothing but this endpoint moves time, so one write flips a window gate from
    refusal to success."""

    def test_one_clock_write_turns_the_refused_outage_start_into_a_success(
        self, api: ApiClient
    ) -> None:
        """The same call, with no other state change, succeeds once the clock reaches the window.

        PRD: "A `PlantAdmin` may advance or reset it by supplying a `to_iso8601` instant; the response reports the new value as `current_utc`."

        Design: Corner/endpoints/clock_endpoint_moves_logical_time_forward_for_window_gates
        """
        world = fixtures.baseline(api)
        world.outage = fixtures.approved_outage(api, world)
        assert world.outage["seasonality_index"] == pytest.approx(0.90, abs=0.005)

        validate_error(
            api.start_outage(world.outage_id, {}, test_users.MAINTENANCE_PLANNER),
            ApiErrorId.OUTAGE_WINDOW_NOT_STARTED.value,
            409,
        )

        clock = validate_success(
            api.set_clock("2026-10-05T06:00:00Z", test_users.PLANT_ADMIN), 200
        )
        assert is_iso8601_timestamp(clock["current_utc"])
        assert clock["current_utc"].startswith("2026-10-05T06:00:00")

        started = validate_success(
            api.start_outage(world.outage_id, {}, test_users.MAINTENANCE_PLANNER), 200
        )
        assert started["status"] == OutageStatus.IN_PROGRESS.value

        line = validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))
        assert line["status"] == BoardLineStatus.UNDER_MAINTENANCE.value
        assert world.read_plant()["production_posture"] == ProductionPosture.RESTRICTED.value, (
            "a PLANNED outage does not freeze the plant, and the silo is empty"
        )


class TestBoardLineReadsAgree:
    """The flat list, the detail read and the plant sub-collection are three addresses
    for one row."""

    def test_all_three_addresses_return_the_same_line_and_the_filter_excludes_the_other_plant(
        self, api: ApiClient
    ) -> None:
        """The plant filter narrows to one line while the status filter sees both.

        PRD: "Board lines accept `plant_id` and `status`."

        Design: Corner/endpoints/board_line_list_and_detail_reads_agree
        """
        plant_one = fixtures.create_plant(api)
        line_one = fixtures.create_line(api, plant_one["id"])
        plant_two = fixtures.create_plant(api, code="GYP-2", name="Platte Valley Wallboard")
        line_two = fixtures.create_line(api, plant_two["id"])

        filtered, filtered_meta = validate_paginated(
            api.list_board_lines(
                test_users.MAINTENANCE_PLANNER, params={"plant_id": plant_one["id"]}
            )
        )
        assert filtered_meta["total_count"] == 1
        assert [row["id"] for row in filtered] == [line_one["id"]]

        detail = validate_success(
            api.get_board_line(line_one["id"], test_users.MAINTENANCE_PLANNER), 200
        )
        assert_board_line(detail)
        assert detail["designation"] == "LINE-1"
        assert detail["max_speed_fpm"] == 500
        assert detail["web_width_in"] == pytest.approx(54.0, abs=0.005)
        assert detail["status"] == BoardLineStatus.AVAILABLE.value
        assert detail["version"] == 1

        sub_collection, sub_meta = validate_paginated(
            api.list_plant_board_lines(plant_one["id"], test_users.MAINTENANCE_PLANNER)
        )
        assert sub_meta["total_count"] == 1
        assert sub_collection[0] == detail, "the sub-collection row is the same projection"

        _, all_meta = validate_paginated(
            api.list_board_lines(
                test_users.MAINTENANCE_PLANNER,
                params={"status": BoardLineStatus.AVAILABLE.value},
            )
        )
        assert all_meta["total_count"] == 2, f"both lines are available: {line_two['id']}"
