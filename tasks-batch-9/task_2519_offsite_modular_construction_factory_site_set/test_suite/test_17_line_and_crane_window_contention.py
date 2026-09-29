"""Two scarce resources booked over intervals whose endpoints matter.

The plant's line admits two modules at once and its occupancy intervals are
half-open, so a claim starting exactly where another ends is free. The site's
crane admits one lift at a time and its windows are closed and widened by a
rigging buffer at both ends, so windows that merely touch after buffering
collide. The two conventions are asserted against each other's edge cases.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CRANE_WINDOW_CONFLICT,
    ERR_LINE_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import assert_instant, assert_two_decimal_value
from test_helpers.test_users import PROGRAM_ADMIN


@pytest.fixture
def three_modules_and_two_line_positions(api):
    """A plant running two modules at a time, with three modules waiting.

    M-01 occupies 14:00 to 23:00 and M-02 occupies 16:00 to 01:30 the next day.
    """
    world = fx.world_with_module(api)
    fx.add_module(world, "M-02", 2)
    fx.add_module(world, "M-03", 3)
    fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")
    fx.schedule_slot(world, "M-02", "2026-09-02T16:00:00Z")
    return world


def test_a_third_module_inside_both_live_slots_exceeds_the_aggregate_capacity(
    three_modules_and_two_line_positions,
):
    """PRD §3.4: "That count must be strictly less than the plant's `parallel_station_capacity`."
    PRD §3.4: "And the aggregate line capacity must not be exceeded, as described next, or the request is `ERR_LINE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/factory_line_half_open_slot_windows_with_aggregate_capacity_two
    """
    world = three_modules_and_two_line_positions
    assert world.module("M-01")["line_slot_minutes"] == 540
    assert_instant(world.module("M-01")["line_slot_end"], "2026-09-02T23:00:00Z")
    assert world.module("M-02")["line_slot_minutes"] == 570
    assert_instant(world.module("M-02")["line_slot_end"], "2026-09-03T01:30:00Z")

    # 18:00 sits inside both live intervals, so the count reaches the capacity.
    validate_error(
        world.api.schedule_line_slot(
            world.module_id("M-03"),
            f.line_slot_payload("2026-09-02T18:00:00Z"),
            world.factory_manager,
        ),
        ERR_LINE_CAPACITY_EXCEEDED,
    )


def test_a_slot_starting_exactly_at_another_slot_end_neither_collides_nor_counts(
    three_modules_and_two_line_positions,
):
    """PRD §3.4: "The server counts every *other* persisted module of the same plant — same plant meaning the module's project carries the same `factory_id` — whose `production_status` is `SLOTTED` or `IN_LINE` and whose own occupancy interval contains the requested start, where containment means the other module's `line_slot_start` is at or before the requested start and its `line_slot_end` is strictly after it."
    PRD §3.4: "Because the interval is half-open, a slot beginning exactly at another slot's `line_slot_end` neither collides with it nor counts it as concurrent."

    Design: Difficulty/resource_temporal_overlap/factory_line_half_open_slot_windows_with_aggregate_capacity_two
    """
    world = three_modules_and_two_line_positions

    slotted = validate_success(
        world.api.schedule_line_slot(
            world.module_id("M-03"),
            f.line_slot_payload("2026-09-02T23:00:00Z"),
            world.factory_manager,
        )
    )

    # M-01's interval ends exactly at 23:00 and is therefore not counted, while
    # M-02 is still on the line, so one concurrent module is charged.
    assert slotted["line_slot_minutes"] == 570


def test_the_plant_ledger_carries_all_three_claims_at_once(
    three_modules_and_two_line_positions,
):
    """PRD §3.4: "On success the plant's `committed_line_minutes` increases by the module's `line_slot_minutes` and the plant's `version` increments; the module's `wip_earned_cents` is recomputed under the station-progress rule, which at `station_index` 0 yields 0; and the module's `version` increments."
    PRD §2.2: "Modules may be listed filtered by `project_id`, `design_package_id`, `shipment_id`, `production_status`, `qc_status`, `site_status` or `envelope_class`."

    Design: Difficulty/resource_temporal_overlap/factory_line_half_open_slot_windows_with_aggregate_capacity_two
    """
    world = three_modules_and_two_line_positions
    fx.schedule_slot(world, "M-03", "2026-09-02T23:00:00Z")

    assert world.refresh_factory()["committed_line_minutes"] == 1680

    slotted = validate_success(
        world.api.list_modules({"production_status": "SLOTTED"}, PROGRAM_ADMIN)
    )
    assert sorted(row["module_code"] for row in slotted) == ["M-01", "M-02", "M-03"]


@pytest.fixture
def two_modules_sharing_one_crane(api):
    """Two identical modules on a site whose crane needs 45 minutes either side."""
    world = fx.world_plant_and_project(
        api,
        project_overrides={
            "crane_rigging_buffer_minutes": 45,
            "forecast_wind_gust_mph": 0,
        },
    )
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    fx.add_module(world, "M-01", 1)
    fx.add_module(world, "M-02", 2)
    validate_success(
        world.api.schedule_pick(
            world.module_id("M-01"),
            f.pick_payload("2026-09-10T09:00:00Z", "2026-09-10T09:45:00Z", 90, 5000),
            world.superintendent,
        )
    )
    return world


def test_a_second_lift_inside_the_buffered_window_is_refused(two_modules_sharing_one_crane):
    """PRD §3.7: "The requested window is expanded by that buffer on both ends — subtracted from `pick_window_start` and added to `pick_window_end` — and compared against the identically expanded window of every *other* module of the same project that already has a pick window planned and whose `site_status` is not yet `CONNECTED`."
    PRD §3.7: "Any overlap is rejected with `ERR_CRANE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/project_crane_window_closed_interval_with_rigging_buffer_and_exclusive_capacity
    """
    world = two_modules_sharing_one_crane
    assert_instant(
        world.refresh_module("M-01")["pick_window_end"], "2026-09-10T09:45:00Z"
    )

    # M-01 buffers out to 08:15 through 10:30; a 10:15 start is inside that.
    validate_error(
        world.api.schedule_pick(
            world.module_id("M-02"),
            f.pick_payload("2026-09-10T10:15:00Z", "2026-09-10T11:00:00Z", 90, 5000),
            world.superintendent,
        ),
        ERR_CRANE_WINDOW_CONFLICT,
    )


def test_buffered_windows_that_merely_touch_at_their_endpoints_still_conflict(
    two_modules_sharing_one_crane,
):
    """PRD §3.7: "Both intervals are closed, so touching endpoints count as an overlap."

    Design: Difficulty/resource_temporal_overlap/project_crane_window_closed_interval_with_rigging_buffer_and_exclusive_capacity
    """
    world = two_modules_sharing_one_crane

    # An 11:15 start buffers back to exactly 10:30, where M-01's buffer ends.
    validate_error(
        world.api.schedule_pick(
            world.module_id("M-02"),
            f.pick_payload("2026-09-10T11:15:00Z", "2026-09-10T12:00:00Z", 90, 5000),
            world.superintendent,
        ),
        ERR_CRANE_WINDOW_CONFLICT,
    )

    assert world.refresh_module("M-02")["pick_window_start"] is None


def test_a_lift_clear_of_the_buffer_at_both_ends_is_planned(two_modules_sharing_one_crane):
    """PRD §3.7: "**Crane exclusivity** is the last constraint on planning, and it is where the project's `crane_rigging_buffer_minutes` earns its place."
    PRD §3.7: "On success the module's `pick_window_start`, `pick_window_end`, `pick_radius_ft` and `rigging_weight_lb` are persisted along with the computed `crane_utilization_pct`, and the module's `version` increments."

    Design: Difficulty/resource_temporal_overlap/project_crane_window_closed_interval_with_rigging_buffer_and_exclusive_capacity
    """
    world = two_modules_sharing_one_crane

    # 11:30 buffers back to 10:45, a quarter of an hour clear of 10:30.
    planned = validate_success(
        world.api.schedule_pick(
            world.module_id("M-02"),
            f.pick_payload("2026-09-10T11:30:00Z", "2026-09-10T12:15:00Z", 90, 5000),
            world.superintendent,
        )
    )

    assert_instant(planned["pick_window_start"], "2026-09-10T11:30:00Z")
    assert_two_decimal_value(
        planned["crane_utilization_pct"], 85.00, "crane_utilization_pct"
    )
