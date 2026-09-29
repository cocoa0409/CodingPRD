"""Corner-case calculation tests for the Package Sortation Peak Staffing API.

Every test below drives one pinned calculation to an edge the PRD names
explicitly — a tier boundary, a rounding constant that only moves under round
half up, an input set that must exclude a retired row, or a selector whose
fallback is a success rather than an error.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    expected_batch_cube,
    expected_cube_after_scan,
    expected_cube_utilization_pct,
    expected_final_cost_per_package,
    expected_planned_labor_cents,
    expected_provisional_cost_per_package,
    expected_required_headcount,
    round_cents,
)
from test_helpers.constants import RATE_CENTS_PER_HOUR
from test_helpers.test_users import (
    INBOUND_COORDINATOR_HEADERS,
    LABOR_PLANNER_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
)


# ─── local setup helpers ──────────────────────────────

def _sorting_building(world, clock, lane_window_end="2026-08-03T14:00:00Z"):
    """A center with one inbound door, one outbound door, one 1,200 pph chute and
    one lane mapped onto it for the working day at `clock`."""
    world.set_clock(clock)
    center = world.create_center(code="SC1", flex_pool_total=20)
    inbound_door = world.create_door(center["id"], door_number=1, kind="INBOUND")
    outbound_door = world.create_door(center["id"], door_number=2, kind="OUTBOUND")
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    lane = world.create_lane(
        center["id"], lane_code="L-WEST", forecast_hourly_volume=3000
    )
    world.map_lane_to_chute(
        chute["id"],
        lane["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end=lane_window_end,
    )
    return {
        "center": center,
        "inbound_door": inbound_door,
        "outbound_door": outbound_door,
        "chute": chute,
        "lane": lane,
    }


def _tier_center_with_plan(world, code, automation_utilization_pct):
    """One center on the named automation tier, one chute, one drafted plan."""
    center = world.create_center(
        code=code,
        automation_utilization_pct=automation_utilization_pct,
        flex_pool_total=20,
    )
    world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    plan = world.create_draft_plan(
        center["id"],
        shift_date="2026-08-03",
        shift_window_start="2026-08-03T06:00:00Z",
        shift_window_end="2026-08-03T14:00:00Z",
        forecast_volume=40000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=500000,
    )
    return center, plan


# ─── tests ────────────────────────────────────────────

def test_unload_rank_recomputed_after_out_of_order_arrivals(world, api):
    """PRD §3.3: "Ranking considers only the appointments of that same center whose `status` is currently `ARRIVED` — scheduled, unloading, jam-held and unloaded appointments are excluded and hold a null rank — and orders them by four keys in order: first by priority band, where `CRITICAL` sorts ahead of `EXPRESS`, `EXPRESS` ahead of `STANDARD`, and `STANDARD` ahead of `DEFERRED`; then by `window_start` earliest first; then by `manifest_package_count` largest first, so the heavier trailer wins a tie between two equally urgent trailers booked for the same window; and finally by `created_at` earliest first as the last tie-break."

    PRD §3.3 also pins the re-rank on the way out: "Because the appointment leaves
    the ranked population when it starts unloading, the remaining `ARRIVED`
    appointments of that center are re-ranked within the same request — a rank is
    only ever a snapshot of the current queue."

    Design: Corner/calculations/unload_rank_recomputed_after_out_of_order_arrivals
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(code="SC1", flex_pool_total=20)
    door_one = world.create_door(center["id"], door_number=1, kind="INBOUND")
    door_two = world.create_door(center["id"], door_number=2, kind="INBOUND")
    door_three = world.create_door(center["id"], door_number=3, kind="INBOUND")

    standard = world.schedule_appointment(
        center["id"],
        door_one["id"],
        trailer_code="T-STD",
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T07:00:00Z",
        priority_class="STANDARD",
        manifest_package_count=900,
    )
    critical = world.schedule_appointment(
        center["id"],
        door_two["id"],
        trailer_code="T-CRIT",
        window_start="2026-08-03T08:00:00Z",
        window_end="2026-08-03T09:00:00Z",
        priority_class="CRITICAL",
        manifest_package_count=300,
    )
    express = world.schedule_appointment(
        center["id"],
        door_three["id"],
        trailer_code="T-EXP",
        window_start="2026-08-03T07:00:00Z",
        window_end="2026-08-03T08:00:00Z",
        priority_class="EXPRESS",
        manifest_package_count=600,
    )

    # The STANDARD trailer arrives first and is alone in the ARRIVED set.
    first_arrival = validate_success(
        api.arrive_trailer_appointment(standard["id"], INBOUND_COORDINATOR_HEADERS)
    )
    assert first_arrival["status"] == "ARRIVED"
    assert first_arrival["unload_sequence_rank"] == 1

    # The CRITICAL trailer arrives second and takes rank 1 anyway.
    validate_success(
        api.arrive_trailer_appointment(critical["id"], INBOUND_COORDINATOR_HEADERS)
    )
    assert world.appointment(critical["id"])["unload_sequence_rank"] == 1
    assert world.appointment(standard["id"])["unload_sequence_rank"] == 2

    # With all three arrived, the priority band dominates window_start entirely.
    validate_success(
        api.arrive_trailer_appointment(express["id"], INBOUND_COORDINATOR_HEADERS)
    )
    assert world.appointment(critical["id"])["unload_sequence_rank"] == 1
    assert world.appointment(express["id"])["unload_sequence_rank"] == 2
    assert world.appointment(standard["id"])["unload_sequence_rank"] == 3

    # Starting the unload drops the trailer out of the ranked population and
    # re-ranks the survivors inside the very same request.
    unloading = validate_success(
        api.start_unload(critical["id"], INBOUND_COORDINATOR_HEADERS)
    )
    assert unloading["status"] == "UNLOADING"
    assert unloading["unload_sequence_rank"] is None
    assert world.appointment(express["id"])["unload_sequence_rank"] == 1
    assert world.appointment(standard["id"])["unload_sequence_rank"] == 2
    assert world.center(center["id"])["packages_inducted_count"] == 0


def test_scan_outside_every_plan_window_attributes_no_plan(world, api):
    """PRD §3.8: "When no plan qualifies, nothing is attributed: no plan counter moves, the request still succeeds, and the lane and center counters are updated exactly as they would have been."

    PRD §3.8 defines the qualifying pool: "The eligible plans are those of the same
    sort center whose `status` is `APPROVED` or `AT_RISK` and whose shift window
    contains the logical clock, where containment is half-open —
    `shift_window_start` at or before the clock and `shift_window_end` strictly
    after it."

    Design: Corner/calculations/scan_outside_every_plan_window_attributes_no_plan
    """
    building = _sorting_building(
        world, "2026-08-03T09:00:00Z", lane_window_end="2026-08-04T14:00:00Z"
    )
    center, lane = building["center"], building["lane"]

    world.induct_packages(center["id"], building["inbound_door"]["id"], 500)
    load = world.stage_load(
        center["id"],
        building["outbound_door"]["id"],
        lane["id"],
        trailer_code="T-OUT-1",
        trailer_cube_cuft=1000.00,
        dispatch_cut_time="2026-08-04T13:00:00Z",
    )

    plan = world.create_submitted_plan(
        center["id"],
        shift_date="2026-08-04",
        shift_window_start="2026-08-04T06:00:00Z",
        shift_window_end="2026-08-04T14:00:00Z",
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    approved = world.approve_plan(plan["id"], center["id"])
    assert approved["status"] == "APPROVED"

    # The clock sits before shift_window_start, so the selector pool is empty.
    first_scan = world.scan(load["id"], small_count=100)
    assert first_scan["package_count"] == 100
    assert float(first_scan["cube_used_cuft"]) == expected_batch_cube(small=100)
    assert world.plan(plan["id"])["sorted_package_count"] == 0
    assert world.center(center["id"])["wip_package_count"] == 400
    assert world.lane(lane["id"])["sorted_package_count"] == 100
    world.assert_ledgers(center["id"])

    # Move the clock inside the window and the very same load is attributed.
    world.set_clock("2026-08-04T07:00:00Z")
    second_scan = world.scan(load["id"], small_count=50)
    assert second_scan["package_count"] == 150
    assert float(second_scan["cube_used_cuft"]) == expected_cube_after_scan(
        expected_batch_cube(small=100), small=50
    )

    settled_plan = world.plan(plan["id"])
    assert settled_plan["sorted_package_count"] == 50
    assert settled_plan["status"] == "APPROVED"
    assert world.center(center["id"])["wip_package_count"] == 350
    assert world.lane(lane["id"])["sorted_package_count"] == 150
    world.assert_ledgers(center["id"])


def test_reroute_picks_highest_throughput_eligible_chute(world, api):
    """PRD §3.8: "Among the qualifying assignments the winner is the one on the chute with the highest `throughput_pph`, with the earliest `created_at` of the assignment breaking a tie and the row's `id` never used, and `resolved_via_chute_id` records the winning chute."

    Design: Corner/calculations/reroute_picks_highest_throughput_eligible_chute
    """
    world.set_clock("2026-08-03T09:00:00Z")
    center = world.create_center(code="SC1", flex_pool_total=20)
    inbound_door = world.create_door(center["id"], door_number=1, kind="INBOUND")
    outbound_door = world.create_door(center["id"], door_number=2, kind="OUTBOUND")
    slow_chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    fast_chute = world.create_chute(center["id"], chute_number=2, throughput_pph=1800)
    lane_west = world.create_lane(
        center["id"], lane_code="L-WEST", region="WEST", forecast_hourly_volume=3000
    )
    lane_east = world.create_lane(
        center["id"], lane_code="L-EAST", region="EAST", forecast_hourly_volume=2000
    )

    # The 1,200 pph chute is mapped to the target lane FIRST, so a created_at
    # tie-break would pick it; the throughput key must beat that.
    world.map_lane_to_chute(
        slow_chute["id"],
        lane_west["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )
    world.map_lane_to_chute(
        slow_chute["id"],
        lane_east["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )
    world.map_lane_to_chute(
        fast_chute["id"],
        lane_east["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )

    world.induct_packages(center["id"], inbound_door["id"], 500)
    load = world.stage_load(
        center["id"],
        outbound_door["id"],
        lane_west["id"],
        trailer_code="T-OUT-1",
        trailer_cube_cuft=1000.00,
        dispatch_cut_time="2026-08-03T13:00:00Z",
    )
    world.scan(load["id"], small_count=300)
    assert world.lane(lane_west["id"])["sorted_package_count"] == 300

    exception = world.create_exception(
        center["id"],
        exception_type="MISSORT",
        package_count=200,
        from_destination_lane_id=lane_west["id"],
    )

    resolved = validate_success(
        api.resolve_package_exception(
            exception["id"],
            f.resolve_exception_payload("REROUTE", to_destination_lane_id=lane_east["id"]),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "REROUTE"
    assert resolved["resolved_at"].startswith("2026-08-03T09:00:00")
    assert resolved["resolved_via_chute_id"] == fast_chute["id"]
    assert resolved["resolved_via_chute_id"] != slow_chute["id"]

    assert world.lane(lane_east["id"])["sorted_package_count"] == 200
    assert world.lane(lane_west["id"])["sorted_package_count"] == 100
    center_row = world.center(center["id"])
    assert center_row["exception_hold_count"] == 0
    assert center_row["missort_corrected_count"] == 200
    assert world.lane(lane_east["id"])["assigned_capacity_pph"] == 3000
    world.assert_ledgers(center["id"])


def test_required_headcount_at_high_automation_tier_boundary(world, api):
    """PRD §3.4: "The throughput of one associate is selected from the **center's** current `automation_utilization_pct`, evaluated top-down: an automation utilization of at least 85 gives 1,200 packages per associate per hour; otherwise an automation utilization of at least 60 gives 950 packages per associate per hour; otherwise 700 packages per associate per hour."

    Design: Corner/calculations/required_headcount_at_high_automation_tier_boundary
    """
    world.set_clock("2026-08-03T05:00:00Z")
    center_above, plan_above = _tier_center_with_plan(world, "SC-86", 86)
    center_at, plan_at = _tier_center_with_plan(world, "SC-85", 85)
    center_below, plan_below = _tier_center_with_plan(world, "SC-84", 84)

    for center in (center_above, center_at, center_below):
        assert world.center(center["id"])["ops_posture"] == "OPEN"

    submitted_above = validate_success(
        api.submit_shift_plan(plan_above["id"], LABOR_PLANNER_HEADERS)
    )
    submitted_at = validate_success(
        api.submit_shift_plan(plan_at["id"], LABOR_PLANNER_HEADERS)
    )
    submitted_below = validate_success(
        api.submit_shift_plan(plan_below["id"], LABOR_PLANNER_HEADERS)
    )

    for submitted in (submitted_above, submitted_at, submitted_below):
        assert submitted["status"] == "SUBMITTED"
        assert float(submitted["shift_hours"]) == 8.00

    # 40000 / (1200 x 8) == 4.1667, whose ceiling is 5 and clears the floor of 4.
    assert submitted_above["required_headcount"] == expected_required_headcount(
        40000, 8.00, 86, "OPEN", 1
    )
    assert submitted_above["required_headcount"] == 5

    # The threshold value itself takes the high tier.
    assert submitted_at["required_headcount"] == expected_required_headcount(
        40000, 8.00, 85, "OPEN", 1
    )
    assert submitted_at["required_headcount"] == 5

    # One point below the threshold drops to 950 pph: 5.2632 ceils to 6.
    assert submitted_below["required_headcount"] == expected_required_headcount(
        40000, 8.00, 84, "OPEN", 1
    )
    assert submitted_below["required_headcount"] == 6


def test_superseded_assignment_contributes_no_lane_capacity(world, api):
    """PRD §3.2: "A lane's `assigned_capacity_pph` is the sum of `throughput_pph` over the distinct chutes that currently hold an `ACTIVE` assignment to that lane, and each qualifying chute contributes its rated throughput exactly once even if it holds two active assignments to the same lane."

    PRD §3.2 pins the excluded statuses in the next breath: "Assignments in
    `SUSPENDED`, `SUPERSEDED` or `ENDED` contribute no capacity at all."

    Design: Corner/calculations/superseded_assignment_contributes_no_lane_capacity
    """
    world.set_clock("2026-08-03T09:00:00Z")
    center = world.create_center(code="SC1", flex_pool_total=20)
    slow_chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    fast_chute = world.create_chute(center["id"], chute_number=2, throughput_pph=1800)
    lane = world.create_lane(
        center["id"], lane_code="L-WEST", forecast_hourly_volume=3000
    )

    slow_assignment = world.map_lane_to_chute(
        slow_chute["id"],
        lane["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )
    fast_assignment = world.map_lane_to_chute(
        fast_chute["id"],
        lane["id"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )
    assert world.lane(lane["id"])["assigned_capacity_pph"] == 3000

    replacement = world.map_lane_to_chute(
        fast_chute["id"],
        lane["id"],
        window_start="2026-08-03T10:00:00Z",
        window_end="2026-08-03T14:00:00Z",
        supersede=True,
    )
    assert replacement["status"] == "ACTIVE"
    assert replacement["window_start"].startswith("2026-08-03T10:00:00")

    retired = world.assignment(fast_assignment["id"])
    assert retired["status"] == "SUPERSEDED"
    assert retired["effective_window_end"].startswith("2026-08-03T10:00:00")
    assert world.assignment(slow_assignment["id"])["status"] == "ACTIVE"

    # The retired row still names the fast chute, but only the ACTIVE rows feed
    # capacity, so the chute is counted exactly once and the lane stays at 3000.
    settled_lane = world.lane(lane["id"])
    assert settled_lane["assigned_capacity_pph"] == 3000
    assert settled_lane["backlog_package_count"] == 0
    assert float(settled_lane["lane_pressure_ratio"]) == 0.0


def test_worked_hours_and_rate_rounding_on_close(world, api):
    """PRD §3.7: "Clocking out advances the assignment `CHECKED_IN → COMPLETED`, again only for its own worker, and settles the shift: `checked_out_at` is stamped from the logical clock, and `worked_hours` becomes the elapsed time between check-in and check-out expressed in hours and rounded half up to two decimal places."

    PRD §3.9 pins where that figure is priced: "Each completed row contributes its
    `worked_hours` multiplied by the hourly rate of that worker's `hire_class` —
    2,150 cents per hour for `CORE`, 1,875 cents for `SEASONAL`, 2,480 cents for
    `FLEX` — rounded half up to whole cents **per assignment line**, and the
    rounded lines are then summed into the base cost."

    Design: Corner/calculations/worked_hours_and_rate_rounding_on_close
    """
    world.set_clock("2026-08-03T05:00:00Z")
    center = world.create_center(code="SC1", flex_pool_total=20)
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)

    plan = world.create_submitted_plan(
        center["id"],
        shift_date="2026-08-03",
        shift_window_start="2026-08-03T06:00:00Z",
        shift_window_end="2026-08-03T14:00:00Z",
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    approved = world.approve_plan(plan["id"], center["id"])
    expected_planned = expected_planned_labor_cents(4, 0, 0, 8.00)
    assert approved["planned_labor_cents"] == expected_planned
    assert approved["flex_draw_count"] == 0
    assert float(
        approved["provisional_cost_per_package_cents"]
    ) == expected_provisional_cost_per_package(expected_planned, 4000)
    assert float(approved["provisional_cost_per_package_cents"]) == 20.20

    worker = world.create_certified_worker(
        center["id"], full_name="Precise Pat", hire_class="CORE", hire_date="2026-08-01"
    )

    # 06:00:00 to 13:30:36 is 27,036 seconds, i.e. exactly 7.51 hours.
    completed = world.complete_assignment_with_hours(
        plan["id"],
        worker["id"],
        chute["id"],
        "2026-08-03T06:00:00Z",
        "2026-08-03T13:30:36Z",
    )
    assert completed["status"] == "COMPLETED"
    assert float(completed["worked_hours"]) == 7.51

    closed = validate_success(
        api.close_shift_plan(
            plan["id"],
            f.close_plan_payload(world.center_version(center["id"])),
            OPS_MANAGER_HEADERS,
        )
    )
    assert closed["status"] == "CLOSED"

    # 7.51 x 2150 == 16146.5, which round half up lifts to 16147.
    expected_actual = round_cents(
        Decimal("7.51") * Decimal(RATE_CENTS_PER_HOUR["CORE"])
    )
    assert expected_actual == 16147
    assert closed["actual_labor_cents"] == expected_actual

    # That odd cent flows straight into the final unit cost.
    assert float(closed["final_cost_per_package_cents"]) == expected_final_cost_per_package(
        expected_actual, 0, 0
    )
    assert float(closed["final_cost_per_package_cents"]) == 28147.00

    settled_center = world.center(center["id"])
    assert settled_center["flex_pool_available"] == 20
    assert settled_center["flex_pool_reserved"] == 0
    world.assert_ledgers(center["id"])


def test_oversized_package_cuft_constant_rounds_half_up(world, api):
    """PRD §3.8: "Each class line is computed on its own and rounded half up to two decimal places: the small line is its count multiplied by 0.335 cubic feet per package, the medium line its count multiplied by 1.205, the large line its count multiplied by 3.755, and the oversized line its count multiplied by 11.505."

    Design: Corner/calculations/oversized_package_cuft_constant_rounds_half_up
    """
    building = _sorting_building(world, "2026-08-03T09:00:00Z")
    center, lane = building["center"], building["lane"]

    world.induct_packages(center["id"], building["inbound_door"]["id"], 100)
    load = world.stage_load(
        center["id"],
        building["outbound_door"]["id"],
        lane["id"],
        trailer_code="T-OUT-1",
        trailer_cube_cuft=500.00,
        dispatch_cut_time="2026-08-03T13:00:00Z",
    )
    assert float(load["cube_used_cuft"]) == 0

    scanned = world.scan(load["id"], oversized_count=1)

    # A single oversized package is the only count that exposes the rule:
    # 1 x 11.505 rounds UP to 11.51 rather than down to 11.50.
    assert float(scanned["cube_used_cuft"]) == expected_batch_cube(oversized=1)
    assert float(scanned["cube_used_cuft"]) == 11.51
    assert float(scanned["cube_utilization_pct"]) == expected_cube_utilization_pct(
        11.51, 500.00
    )
    assert float(scanned["cube_utilization_pct"]) == 2.30
    assert scanned["package_count"] == 1
    assert scanned["load_status"] == "LOADING"

    assert world.center(center["id"])["wip_package_count"] == 99
    assert world.lane(lane["id"])["sorted_package_count"] == 1
    world.assert_ledgers(center["id"])
