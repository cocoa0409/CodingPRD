"""Three resources with three different overlap conventions: the half-open board
line, the summed-rate calciner where overlap is legal, and the closed-interval
outage window that conflicts on a single touching instant.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BatchStatus,
    OutageStatus,
    RunStatus,
    assert_calciner_batch,
    assert_no_run_side_effects,
    assert_production_run,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
)


class TestRunWindowsOnOneLine:
    """Runs occupy `[window_start, window_end)`, so touching windows coexist and a
    straddling window does not."""

    @staticmethod
    def _line_with_two_touching_runs(api: ApiClient):
        """R1 on 06:00-10:00 and R2 on 10:00-14:00, both scheduled at 100.000 MSF."""
        world = fixtures.scheduled_run(api, requested_planned_msf=100.0)
        second = fixtures.draft_run(
            api,
            world,
            window_start="2026-08-03T10:00:00Z",
            window_end="2026-08-03T14:00:00Z",
            requested_planned_msf=100.0,
        )
        world.run_2 = fixtures.schedule(api, second["id"], world.plant_id)
        return world

    def test_a_run_starting_when_the_previous_one_ends_is_accepted(
        self, api: ApiClient
    ) -> None:
        """The touching run schedules and becomes the successor with a zero gap.

        PRD: "Consequently two runs on the same line whose windows merely touch, where one ends at exactly the instant the other begins, do **not** overlap and both may be scheduled."

        Design: Difficulty/resource_temporal_overlap/run_windows_half_open_touch_allowed_overlap_rejected
        """
        world = self._line_with_two_touching_runs(api)
        second = world.run_2

        assert_production_run(second)
        assert second["status"] == RunStatus.SCHEDULED.value
        assert second["prior_run_id"] == world.run_id, "R1 is its changeover predecessor"
        assert second["changeover_minutes"] == 0, "the same product specification needs no changeover"
        assert second["gap_minutes"] == 0, "the windows touch, so the gap is zero minutes"
        assert second["in_window_changeover_minutes"] == 0
        assert second["available_minutes"] == 240, "a warm start keeps its whole window"
        assert second["capacity_msf"] == pytest.approx(384.000, abs=0.0005), (
            "240 minutes at 1.600000 MSF a minute is 384.000"
        )
        assert second["effective_planned_msf"] == pytest.approx(100.000, abs=0.0005)
        assert second["stucco_reserved_tons"] == pytest.approx(67.500, abs=0.0005)

    def test_a_run_straddling_the_boundary_is_rejected(self, api: ApiClient) -> None:
        """A 09:00-13:00 window overlaps both scheduled runs and cannot be scheduled.

        PRD: "and it must not overlap any other run on the same line whose `status` is `SCHEDULED` or `RUNNING`, judged under the half-open convention, or the request fails with `ERR_LINE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/run_windows_half_open_touch_allowed_overlap_rejected
        """
        world = self._line_with_two_touching_runs(api)

        straddling = fixtures.draft_run(
            api,
            world,
            window_start="2026-08-03T09:00:00Z",
            window_end="2026-08-03T13:00:00Z",
            requested_planned_msf=100.0,
        )

        validate_error(
            api.schedule_run(
                straddling["id"],
                factories.schedule_payload(world.plant_version()),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.LINE_WINDOW_CONFLICT.value,
            409,
        )

        assert_no_run_side_effects(world.read_run(straddling["id"]), RunStatus.DRAFT.value)

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(135.000, abs=0.0005), (
            "only the two accepted runs hold reservations, 67.500 tons each"
        )
        assert plant["stucco_available_tons"] == pytest.approx(69.530, abs=0.0005)


class TestCalcinerAggregateRate:
    """Calciner windows may overlap; what is bounded is the summed feed rate over
    every boundary-delimited sub-interval."""

    @staticmethod
    def _plant_with_two_overlapping_batches(api: ApiClient) -> tuple[str, dict, dict]:
        plant = fixtures.create_plant(api)
        first = fixtures.create_batch(api, plant["id"])
        second = fixtures.create_batch(
            api,
            plant["id"],
            target_stucco_tons=100.0,
            feed_rate_tph=20.0,
            feed_window_start="2026-08-02T12:00:00Z",
            feed_window_end="2026-08-02T16:00:00Z",
        )
        return plant["id"], first, second

    def test_a_sub_interval_summing_to_exactly_capacity_is_accepted_and_more_is_not(
        self, api: ApiClient
    ) -> None:
        """40 plus 20 tph is exactly 60; adding 5 tph over the shared hours is refused.

        PRD: "If any sub-interval's total is strictly greater than the plant's `calciner_capacity_tph`, the plan is refused with `ERR_CALCINER_CAPACITY_EXCEEDED`; a total exactly equal to capacity is accepted."

        Design: Difficulty/resource_temporal_overlap/calciner_aggregate_rate_over_overlapping_subinterval
        """
        plant_id, first, second = self._plant_with_two_overlapping_batches(api)

        assert_calciner_batch(second)
        assert second["status"] == BatchStatus.PLANNED.value, (
            "the 12:00-14:00 overlap carries 60.0 tph, exactly the plant's capacity"
        )

        validate_error(
            api.create_calciner_batch(
                factories.calciner_batch_payload(
                    plant_id,
                    target_stucco_tons=20.0,
                    feed_rate_tph=5.0,
                    feed_window_start="2026-08-02T13:00:00Z",
                    feed_window_end="2026-08-02T14:00:00Z",
                ),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.CALCINER_CAPACITY_EXCEEDED.value,
            409,
        )

        assert fixtures.read_batch(api, first["id"])["feed_rate_tph"] == pytest.approx(
            40.0, abs=0.005
        ), "the refused plan changed nothing on its siblings"
        assert fixtures.read_batch(api, second["id"])["feed_rate_tph"] == pytest.approx(
            20.0, abs=0.005
        )

    def test_a_batch_starting_when_another_ends_carries_no_shared_load(
        self, api: ApiClient
    ) -> None:
        """Half-open calciner windows mean a 16:00 start shares nothing with a 16:00 end.

        PRD: "It then breaks the union of the new half-open window with each of those siblings' windows into sub-intervals at every boundary instant, and for each sub-interval sums the new batch's `feed_rate_tph` together with the `feed_rate_tph` of every sibling overlapping that sub-interval."

        Design: Difficulty/resource_temporal_overlap/calciner_aggregate_rate_over_overlapping_subinterval
        """
        plant_id, _, _ = self._plant_with_two_overlapping_batches(api)

        touching = fixtures.create_batch(
            api,
            plant_id,
            target_stucco_tons=150.0,
            feed_rate_tph=40.0,
            feed_window_start="2026-08-02T16:00:00Z",
            feed_window_end="2026-08-02T20:00:00Z",
        )

        assert touching["status"] == BatchStatus.PLANNED.value, (
            "its own 40.0 tph is the only load on its window"
        )
        assert touching["feed_tons_total"] == pytest.approx(0.000, abs=0.0005)

        _, meta = validate_paginated(
            api.list_calciner_batches(
                test_users.MATERIALS_CONTROLLER, params={"plant_id": plant_id}
            )
        )
        assert meta["total_count"] == 3, "three batches were planned on this calciner"


class TestOutageWindowIsClosedOnBothEnds:
    """An outage occupies `[window_start, window_end]`, so a run beginning on the
    outage's final instant conflicts, and one an hour later does not."""

    @staticmethod
    def _line_with_an_approved_october_outage(api: ApiClient):
        world = fixtures.baseline_with_stucco(api)
        fixtures.approved_outage(api, world)
        return world

    def test_a_run_starting_on_the_outage_end_instant_is_rejected(
        self, api: ApiClient
    ) -> None:
        """The single shared instant is enough to raise the outage window conflict.

        PRD: "A run whose window begins at exactly the instant an approved outage ends therefore *does* conflict with that outage, and two outages on one line that touch at an endpoint conflict with each other."

        Design: Difficulty/resource_temporal_overlap/outage_closed_interval_touch_blocks_run_schedule
        """
        world = self._line_with_an_approved_october_outage(api)
        assert world.read_outage()["status"] == OutageStatus.APPROVED.value

        touching = fixtures.draft_run(
            api,
            world,
            window_start="2026-10-07T06:00:00Z",
            window_end="2026-10-07T10:00:00Z",
            requested_planned_msf=100.0,
        )

        validate_error(
            api.schedule_run(
                touching["id"],
                factories.schedule_payload(world.plant_version()),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.OUTAGE_WINDOW_CONFLICT.value,
            409,
        )

        assert_no_run_side_effects(world.read_run(touching["id"]), RunStatus.DRAFT.value)
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)

    def test_a_run_an_hour_after_the_outage_schedules_normally(self, api: ApiClient) -> None:
        """Clear of the closed interval, the run takes the whole cold-start chain.

        PRD: "A maintenance outage, by contrast, occupies the closed interval `[window_start, window_end]`: both endpoints are inside the window."

        Design: Difficulty/resource_temporal_overlap/outage_closed_interval_touch_blocks_run_schedule
        """
        world = self._line_with_an_approved_october_outage(api)

        clear = fixtures.draft_run(
            api,
            world,
            window_start="2026-10-07T07:00:00Z",
            window_end="2026-10-07T11:00:00Z",
            requested_planned_msf=100.0,
        )
        scheduled = fixtures.schedule(api, clear["id"], world.plant_id)

        assert scheduled["status"] == RunStatus.SCHEDULED.value
        assert scheduled["prior_run_id"] is None, "no earlier run has occupied this line"
        assert scheduled["changeover_minutes"] == 45
        assert scheduled["in_window_changeover_minutes"] == 45
        assert scheduled["available_minutes"] == 195
        assert scheduled["capacity_msf"] == pytest.approx(312.000, abs=0.0005)
        assert scheduled["effective_planned_msf"] == pytest.approx(100.000, abs=0.0005)
        assert scheduled["stucco_reserved_tons"] == pytest.approx(67.500, abs=0.0005)

        assert world.read_plant()["stucco_available_tons"] == pytest.approx(137.030, abs=0.0005), (
            "204.530 on hand less the 67.500 this run reserved"
        )
