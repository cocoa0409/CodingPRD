"""Occupancy conflicts on two different resources with two different interval rules.

Setpoint windows occupy a (compartment, regime) pair over a half-open interval, so
adjacency is legal and the other regime is a separate track. Crew work occupies a
worker over a closed interval widened by the travel buffer on both sides.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_climate_strategy,
    create_climate_strategy_payload,
    create_harvest_worker,
    create_labor_task,
    create_labor_task_payload,
    read_climate_strategy,
    read_labor_task,
    read_worker,
    read_zone,
    set_clock,
    setup_transplanted_cycle,
    create_zone,
    validate_error,
    validate_paginated,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]

PLAN_CLOCK = "2026-08-06T00:00:00Z"


def _zone_with_one_day_window():
    """A compartment carrying one ACTIVE DAY window over 2026-08-07 06:00 to 18:00."""
    set_clock(PLAN_CLOCK)
    zone = create_zone()
    strategy = create_climate_strategy(zone["id"], zone["version"])
    return {"zone": zone, "day_strategy": strategy}


def _worker_with_one_scheduled_task():
    """One SCHEDULED HARVEST task over 2026-08-07 07:00 to 11:00, buffered 06:30 to 11:30."""
    state = setup_transplanted_cycle(clock=PLAN_CLOCK)
    worker = create_harvest_worker()
    task = create_labor_task(
        state["zone"]["id"],
        state["cycle"]["id"],
        worker["id"],
        window_start="2026-08-07T07:00:00Z",
        window_end="2026-08-07T11:00:00Z",
        planned_units=2000,
        standard_units_per_hour=520,
    )
    state["worker"] = worker
    state["task_a"] = task
    return state


class TestClimateWindowOccupancy:
    """A (compartment, regime) pair is occupied over a half-open interval."""

    def test_a_window_starting_where_the_last_one_ended_is_not_an_overlap(self, api):
        """PRD §3.4: "Because the interval is half-open, a new window that starts exactly at an existing window's `window_end` does not overlap it."

        Design: Difficulty/resource_temporal_overlap/climate_windows_use_half_open_intervals_keyed_by_zone_and_regime
        """
        state = _zone_with_one_day_window()
        assert state["day_strategy"]["status"] == "ACTIVE", (
            f"the first window must be ACTIVE, got {state['day_strategy']['status']}"
        )

        zone = read_zone(state["zone"]["id"])
        adjacent = validate_success(
            api.create_climate_strategy(
                create_climate_strategy_payload(
                    zone["id"],
                    zone["version"],
                    window_start="2026-08-07T18:00:00Z",
                    window_end="2026-08-08T02:00:00Z",
                    temp_setpoint_c=18.0,
                    rh_setpoint_pct=82,
                    co2_setpoint_ppm=420,
                    lighting_hours=4,
                    screen_position_pct=80,
                ),
                GM,
            ),
            201,
        )
        assert adjacent["status"] == "ACTIVE", (
            f"an adjacent window is accepted as ACTIVE, got {adjacent['status']}"
        )
        assert read_climate_strategy(state["day_strategy"]["id"])["status"] == "ACTIVE", (
            "an adjacent window does not supersede the window it touches"
        )
        assert read_zone(zone["id"])["version"] == zone["version"] + 1, (
            "an accepted window bumps the compartment version by one"
        )

    def test_a_genuine_overlap_on_the_same_regime_is_refused(self, api):
        """PRD §3.4: "When an `ACTIVE` window on the same compartment and the same `regime` overlaps the requested half-open window and `supersede` is absent or false, the create is rejected with `ERR_CLIMATE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/climate_windows_use_half_open_intervals_keyed_by_zone_and_regime
        """
        state = _zone_with_one_day_window()
        zone = read_zone(state["zone"]["id"])
        response = api.create_climate_strategy(
            create_climate_strategy_payload(
                zone["id"],
                zone["version"],
                window_start="2026-08-07T17:00:00Z",
                window_end="2026-08-07T23:00:00Z",
                temp_setpoint_c=20.0,
                rh_setpoint_pct=80,
                co2_setpoint_ppm=600,
                lighting_hours=4,
                screen_position_pct=50,
            ),
            GM,
        )
        validate_error(response, ApiErrorId.ERR_CLIMATE_WINDOW_OVERLAP.value)

        strategies, meta = validate_paginated(
            api.list_climate_strategies(GM, params={"zone_id": zone["id"]})
        )
        assert meta["total_count"] == 1, (
            "a refused create writes no window, so only the original remains, got "
            f"{meta['total_count']}"
        )
        assert strategies[0]["id"] == state["day_strategy"]["id"], (
            "the surviving window must be the original one"
        )
        assert read_zone(zone["id"])["version"] == zone["version"], (
            "a refused create does not bump the compartment version"
        )

    def test_the_same_clock_times_are_free_on_the_other_regime(self, api):
        """PRD §3.4: "The two regimes are independent occupancy tracks on the same compartment: a day window and a night window may overlap each other freely, but two active windows on the same compartment *and* the same regime may not."

        Design: Difficulty/resource_temporal_overlap/climate_windows_use_half_open_intervals_keyed_by_zone_and_regime
        """
        state = _zone_with_one_day_window()
        zone = read_zone(state["zone"]["id"])
        validate_error(
            api.create_climate_strategy(
                create_climate_strategy_payload(
                    zone["id"],
                    zone["version"],
                    window_start="2026-08-07T17:00:00Z",
                    window_end="2026-08-07T23:00:00Z",
                ),
                GM,
            ),
            ApiErrorId.ERR_CLIMATE_WINDOW_OVERLAP.value,
        )

        night = validate_success(
            api.create_climate_strategy(
                create_climate_strategy_payload(
                    zone["id"],
                    zone["version"],
                    regime="NIGHT",
                    window_start="2026-08-07T17:00:00Z",
                    window_end="2026-08-07T23:00:00Z",
                    temp_setpoint_c=17.5,
                    rh_setpoint_pct=85,
                    co2_setpoint_ppm=420,
                    lighting_hours=0,
                    screen_position_pct=100,
                ),
                GM,
            ),
            201,
        )
        assert night["regime"] == "NIGHT", (
            f"the accepted window must be the night one, got {night['regime']}"
        )
        assert night["status"] == "ACTIVE", (
            "the night track is free at those clock times, got "
            f"{night['status']}"
        )
        assert read_climate_strategy(state["day_strategy"]["id"])["status"] == "ACTIVE", (
            "a night window leaves the overlapping day window alone"
        )


class TestWorkerDoubleBookingBuffer:
    """A worker's committed window is widened by thirty minutes on both sides."""

    def test_a_task_twenty_minutes_after_the_last_one_conflicts(self, api):
        """PRD §3.8: "Touching exactly at a widened endpoint is not a conflict, so a task starting twenty minutes after another ends conflicts and is rejected with `ERR_WORKER_DOUBLE_BOOKED`, while a task starting exactly thirty minutes after another ends is accepted."

        Design: Difficulty/resource_temporal_overlap/worker_double_booking_uses_a_closed_window_widened_by_the_travel_buffer
        """
        state = _worker_with_one_scheduled_task()
        assert state["task_a"]["planned_hours"] == pytest.approx(3.66, abs=0.01), (
            "2000 units against a 520 unit standard on a 1.05 index plans 3.66 hours, got "
            f"{state['task_a']['planned_hours']}"
        )
        assert state["task_a"]["planned_cost_usd"] == pytest.approx(71.37, abs=0.01), (
            f"3.66 hours at 19.50 US dollars an hour costs 71.37, got "
            f"{state['task_a']['planned_cost_usd']}"
        )

        response = api.create_labor_task(
            create_labor_task_payload(
                state["zone"]["id"],
                state["cycle"]["id"],
                state["worker"]["id"],
                window_start="2026-08-07T11:20:00Z",
                window_end="2026-08-07T15:00:00Z",
                planned_units=2000,
                standard_units_per_hour=520,
            ),
            GM,
        )
        validate_error(response, ApiErrorId.ERR_WORKER_DOUBLE_BOOKED.value)

        tasks, meta = validate_paginated(
            api.list_labor_tasks(GM, params={"worker_id": state["worker"]["id"]})
        )
        assert meta["total_count"] == 1, (
            f"a refused create writes no second task, got {meta['total_count']}"
        )
        assert tasks[0]["id"] == state["task_a"]["id"], (
            "the surviving task must be the original one"
        )
        assert read_worker(state["worker"]["id"])["committed_hours"] == pytest.approx(
            3.66, abs=0.01
        ), "a refused create commits no further hours"

    def test_a_task_exactly_thirty_minutes_after_the_last_one_is_accepted(self, api):
        """PRD §3.8: "Touching exactly at a widened endpoint is not a conflict, so a task starting twenty minutes after another ends conflicts and is rejected with `ERR_WORKER_DOUBLE_BOOKED`, while a task starting exactly thirty minutes after another ends is accepted."

        Design: Difficulty/resource_temporal_overlap/worker_double_booking_uses_a_closed_window_widened_by_the_travel_buffer
        """
        state = _worker_with_one_scheduled_task()
        accepted = validate_success(
            api.create_labor_task(
                create_labor_task_payload(
                    state["zone"]["id"],
                    state["cycle"]["id"],
                    state["worker"]["id"],
                    window_start="2026-08-07T11:30:00Z",
                    window_end="2026-08-07T15:00:00Z",
                    planned_units=2000,
                    standard_units_per_hour=520,
                ),
                GM,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED", (
            f"the second task must be scheduled, got {accepted['status']}"
        )
        assert accepted["planned_hours"] == pytest.approx(3.66, abs=0.01), (
            f"the identical work plans the same 3.66 hours, got {accepted['planned_hours']}"
        )
        assert accepted["planned_cost_usd"] == pytest.approx(71.37, abs=0.01), (
            f"the identical work costs the same 71.37, got {accepted['planned_cost_usd']}"
        )
        assert read_labor_task(state["task_a"]["id"])["status"] == "SCHEDULED", (
            "the first task keeps its slot"
        )

    def test_two_accepted_tasks_stack_their_hours_and_money(self, api):
        """PRD §2.9: "A worker's `committed_hours` is the sum of `planned_hours` over that worker's labor tasks in `SCHEDULED` or `IN_PROGRESS` — measured hours never enter this figure, and completion removes the planned hours rather than replacing them."

        Design: Difficulty/resource_temporal_overlap/worker_double_booking_uses_a_closed_window_widened_by_the_travel_buffer
        """
        state = _worker_with_one_scheduled_task()
        validate_success(
            api.create_labor_task(
                create_labor_task_payload(
                    state["zone"]["id"],
                    state["cycle"]["id"],
                    state["worker"]["id"],
                    window_start="2026-08-07T11:30:00Z",
                    window_end="2026-08-07T15:00:00Z",
                    planned_units=2000,
                    standard_units_per_hour=520,
                ),
                GM,
            ),
            201,
        )

        worker = read_worker(state["worker"]["id"])
        assert worker["committed_hours"] == pytest.approx(7.32, abs=0.01), (
            f"two scheduled tasks of 3.66 hours commit 7.32 hours, got "
            f"{worker['committed_hours']}"
        )
        zone = read_zone(state["zone"]["id"])
        assert zone["labor_budget_committed_usd"] == pytest.approx(142.74, abs=0.01), (
            "two planned costs of 71.37 commit 142.74, got "
            f"{zone['labor_budget_committed_usd']}"
        )
        assert zone["labor_budget_remaining_usd"] == pytest.approx(19857.26, abs=0.01), (
            "20000.00 less 142.74 leaves 19857.26, got "
            f"{zone['labor_budget_remaining_usd']}"
        )
