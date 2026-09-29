"""Three multi-stage formulas whose stages have to run in the stated order.

Crane feasibility looks a chart row up, derates it for wind, and only then
cross-multiplies against an integer gate. A draw amount rounds once per module,
once for the deposit rate and once for retainage. A line slot derives its
effective takt from how busy the line already is at the requested instant. Each
of the three is exercised stage by stage, so a collapsed or reordered stage is
visible in the numbers.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CRANE_CAPACITY_EXCEEDED
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_two_decimal_value,
)
from test_helpers.test_users import LENDER_DRAW_ADMINISTRATOR


@pytest.fixture
def module_awaiting_its_lift(api):
    """A module still standing at the plant, against a three-row crane chart.

    The design revision is left in DRAFT: planning a lift reads the project's
    chart and the module's own weight, nothing from the review chain.
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    world.modules["M-01"] = fx.create_module(
        api, world.project_id, world.package_id, world.factory_id, "M-01", 1
    )
    return world


def test_the_pick_radius_selects_the_smallest_chart_row_that_reaches_it(
    module_awaiting_its_lift,
):
    """PRD §3.7: "First, the server looks up the chart entry with the *smallest* `radius_ft` that is greater than or equal to the requested `pick_radius_ft`."
    PRD §3.7: "Third, the rigged weight is the module's `gross_weight_lb` plus its `rigging_weight_lb`."
    PRD §3.7: "The module's `crane_utilization_pct` is stored as the rigged weight multiplied by 100, divided by the derated capacity, rounded half up to two decimal places — but that stored figure is display only."

    Design: Difficulty/combinatorial_formula/mode_a_crane_chart_lookup_then_derate_then_cross_multiplication
    """
    world = module_awaiting_its_lift

    module = validate_success(
        world.api.schedule_pick(
            world.module_id(),
            f.pick_payload(
                "2026-09-10T09:00:00Z", "2026-09-10T09:45:00Z", 75, 5000
            ),
            world.superintendent,
        )
    )

    # A 75 foot radius reaches past the 60 foot row, so the 90 foot row at
    # 96,000 lb is the capacity in play: 81,600 rigged pounds is 85 percent.
    assert_two_decimal_value(
        module["crane_utilization_pct"], 85.00, "crane_utilization_pct"
    )


def test_a_lift_that_displays_exactly_eighty_five_percent_is_still_admitted(
    module_awaiting_its_lift,
):
    """PRD §3.7: "The feasibility gate is an exact integer comparison that never sees the rounded value: the pick is infeasible when the rigged weight multiplied by 100 is strictly greater than 85 multiplied by the derated capacity."
    PRD §3.7: "On success the module's `pick_window_start`, `pick_window_end`, `pick_radius_ft` and `rigging_weight_lb` are persisted along with the computed `crane_utilization_pct`, and the module's `version` increments."

    Design: Difficulty/combinatorial_formula/mode_a_crane_chart_lookup_then_derate_then_cross_multiplication
    """
    world = module_awaiting_its_lift

    validate_success(
        world.api.schedule_pick(
            world.module_id(),
            f.pick_payload(
                "2026-09-10T09:00:00Z", "2026-09-10T09:45:00Z", 75, 5000
            ),
            world.superintendent,
        )
    )

    # 81,600 x 100 equals 85 x 96,000 exactly, and the gate is strictly greater.
    module = world.refresh_module()
    assert module["pick_radius_ft"] == 75
    assert module["rigging_weight_lb"] == 5000
    assert_instant(module["pick_window_start"], "2026-09-10T09:00:00Z")
    assert_instant(module["pick_window_end"], "2026-09-10T09:45:00Z")


def test_a_twenty_mile_an_hour_gust_derates_the_chart_row_before_the_gate(
    module_awaiting_its_lift,
):
    """PRD §3.7: "Second, a wind derate may apply: when the project's `forecast_wind_gust_mph` is at least 20 miles per hour, the capacity is multiplied by 0.75 and truncated downwards to a whole pound, so the crane is treated as having only three quarters of its published capacity."
    PRD §3.7: "A lift that displays exactly 85.00 percent after rounding can therefore still be infeasible, and an infeasible lift is rejected with `ERR_CRANE_CAPACITY_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/mode_a_crane_chart_lookup_then_derate_then_cross_multiplication
    """
    world = module_awaiting_its_lift
    validate_success(
        world.api.record_weather_observation(
            world.project_id,
            f.weather_payload(forecast_wind_gust_mph=20),
            world.superintendent,
        )
    )

    # The 96,000 lb row derates to 72,000 lb, and 8,160,000 exceeds 6,120,000.
    validate_error(
        world.api.schedule_pick(
            world.module_id(),
            f.pick_payload(
                "2026-09-10T09:00:00Z", "2026-09-10T09:45:00Z", 75, 5000
            ),
            world.superintendent,
        ),
        ERR_CRANE_CAPACITY_EXCEEDED,
    )

    module = world.refresh_module()
    assert module["pick_window_start"] is None
    assert module["crane_utilization_pct"] is None


@pytest.fixture
def three_modules_one_station_in(api):
    """Three modules of one project, each standing at station 1 of 6.

    Each module has earned one sixth of an 8,750,000 cent unit value, which is
    1,458,333.33 cents — a third of a cent short of a whole cent apiece.
    """
    world = fx.world_with_module(api)
    fx.add_module(world, "M-02", 2)
    fx.add_module(world, "M-03", 3)
    for code, start in (
        ("M-01", "2026-09-02T14:00:00Z"),
        ("M-02", "2026-09-03T14:00:00Z"),
        ("M-03", "2026-09-04T14:00:00Z"),
    ):
        fx.schedule_slot(world, code, start)
        fx.advance_stations(world, code, 1)
    return world


def test_the_draw_basis_rounds_every_module_before_it_sums_them(
    three_modules_one_station_in,
):
    """PRD §3.9: "The qualifying modules are enumerated in `created_at` ascending order — ordering by `id` is forbidden, because the rounding remainder must be assigned deterministically — and each module's contribution is rounded half up to a whole cent *before* anything is summed."
    PRD §3.9: "Rounding each module before summing is observably different from summing exact fractions and rounding once, and this specification requires the former."
    PRD §3.9: "Under `WIP_DEPOSIT`, `requested_cents` is `basis_earned_cents` multiplied by the project's `deposit_pct` — 20 percent of work in progress by default — rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/mode_b_draw_amount_three_stage_rounding_order
    """
    world = three_modules_one_station_in

    draw = validate_success(
        world.api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 1),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        201,
    )

    assert draw["basis_module_count"] == 3
    # Three terms of 1,458,333 sum to 4,374,999; summing the exact fractions
    # first would have rounded to 4,375,000.
    assert_cents(draw["basis_earned_cents"], 4374999, "basis_earned_cents")
    assert_cents(draw["requested_cents"], 875000, "requested_cents")


def test_certification_reruns_the_basis_then_takes_the_deposit_then_the_retainage(
    three_modules_one_station_in,
):
    """PRD §3.9: "`certified_cents` is `certified_basis_cents` multiplied by the project's `deposit_pct` and rounded half up to a whole cent under `WIP_DEPOSIT`, and is equal to `certified_basis_cents` under `MILESTONE_SET`."
    PRD §3.9: "`retainage_held_cents` is `certified_cents` multiplied by the project's `retainage_pct` — 5 percent by default — rounded half up to a whole cent."
    PRD §3.9: "`net_funded_cents` is `certified_cents` minus `retainage_held_cents`."
    PRD §3.9: "That is the three-rounding sequence promised in §2.8: once per module, once when the deposit rate meets the summed basis, once when retainage meets the certified amount."

    Design: Difficulty/combinatorial_formula/mode_b_draw_amount_three_stage_rounding_order
    """
    world = three_modules_one_station_in
    draw = fx.create_draw(
        world.api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1
    )

    certified = validate_success(
        world.api.certify_draw(draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR)
    )

    assert_cents(certified["certified_basis_cents"], 4374999, "certified_basis_cents")
    assert_cents(certified["certified_cents"], 875000, "certified_cents")
    assert_cents(certified["retainage_held_cents"], 43750, "retainage_held_cents")
    assert_cents(certified["net_funded_cents"], 831250, "net_funded_cents")


def test_the_project_work_in_progress_ledger_takes_the_certified_amount(
    three_modules_one_station_in,
):
    """PRD §3.9: "A successful certification moves `status` from `DRAFT` to `CERTIFIED`, stamps `certified_at` with the current clock instant, adds `certified_cents` to the project's `wip_certified_cents`, and increments both the draw's and the project's `version`."

    Design: Difficulty/combinatorial_formula/mode_b_draw_amount_three_stage_rounding_order
    """
    world = three_modules_one_station_in
    draw = fx.create_draw(
        world.api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1
    )
    validate_success(
        world.api.certify_draw(draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR)
    )

    assert_cents(
        world.refresh_project()["wip_certified_cents"], 875000, "wip_certified_cents"
    )


@pytest.fixture
def two_modules_waiting_for_the_line(api):
    """A released plant with two PLANNED modules and a parallel capacity of 2."""
    world = fx.world_with_module(api)
    fx.add_module(world, "M-02", 2)
    return world


def test_the_first_module_on_an_empty_line_runs_at_the_published_takt(
    two_modules_waiting_for_the_line,
):
    """PRD §3.4: "The effective takt in minutes is the plant's `takt_minutes` plus 5 minutes for each concurrent module — a five-minute congestion penalty per module already on the line at that instant."
    PRD §3.4: "The module's `line_slot_minutes` is then the plant's `station_count` multiplied by that effective takt, in whole minutes."
    PRD §3.4: "Its `line_slot_start` is the requested instant and its `line_slot_end` is that instant plus `line_slot_minutes` minutes."

    Design: Difficulty/combinatorial_formula/mode_c_line_slot_effective_takt_from_current_line_occupancy
    """
    world = two_modules_waiting_for_the_line

    module = validate_success(
        world.api.schedule_line_slot(
            world.module_id("M-01"),
            f.line_slot_payload("2026-09-02T14:00:00Z"),
            world.factory_manager,
        )
    )

    # Nothing else is on the line, so six stations at the published 90 minutes.
    assert module["line_slot_minutes"] == 540
    assert_instant(module["line_slot_end"], "2026-09-02T23:00:00Z")


def test_a_second_module_inside_the_first_slot_pays_the_congestion_penalty(
    two_modules_waiting_for_the_line,
):
    """PRD §3.4: "**The takt actually achieved degrades with congestion**, and the same count feeds the schedule."
    PRD §3.4: "The server counts every *other* persisted module of the same plant — same plant meaning the module's project carries the same `factory_id` — whose `production_status` is `SLOTTED` or `IN_LINE` and whose own occupancy interval contains the requested start, where containment means the other module's `line_slot_start` is at or before the requested start and its `line_slot_end` is strictly after it."

    Design: Difficulty/combinatorial_formula/mode_c_line_slot_effective_takt_from_current_line_occupancy
    """
    world = two_modules_waiting_for_the_line
    fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")

    module = validate_success(
        world.api.schedule_line_slot(
            world.module_id("M-02"),
            f.line_slot_payload("2026-09-02T16:00:00Z"),
            world.factory_manager,
        )
    )

    # 16:00 falls inside M-01's occupancy, so the takt is 95 minutes, not 90.
    assert module["line_slot_minutes"] == 570
    assert_instant(module["line_slot_end"], "2026-09-03T01:30:00Z")


def test_the_plant_capacity_ledger_carries_the_sum_of_the_two_slots(
    two_modules_waiting_for_the_line,
):
    """PRD §3.4: "On success the plant's `committed_line_minutes` increases by the module's `line_slot_minutes` and the plant's `version` increments; the module's `wip_earned_cents` is recomputed under the station-progress rule, which at `station_index` 0 yields 0; and the module's `version` increments."

    Design: Difficulty/combinatorial_formula/mode_c_line_slot_effective_takt_from_current_line_occupancy
    """
    world = two_modules_waiting_for_the_line
    fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")
    fx.schedule_slot(world, "M-02", "2026-09-02T16:00:00Z")

    assert world.refresh_factory()["committed_line_minutes"] == 1110
