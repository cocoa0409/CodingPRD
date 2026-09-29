"""Values that land exactly on a declared boundary.

Two boundaries are exercised: a completed labor task whose productivity ratio
quantizes to exactly the bonus threshold, and a picked lot whose harvest date
sits exactly on the excluded upper edge of a week's eligibility window.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_commitment_week,
    create_harvest_worker,
    create_labor_task,
    create_retail_program,
    find_allocations,
    make_harvest_supervisor_headers,
    read_lot,
    read_week,
    read_worker,
    read_zone,
    run_allocation,
    set_clock,
    setup_cold_held_lot,
    setup_transplanted_cycle,
    transition_labor_task,
    validate_error,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]


def _task_in_progress_on_a_flat_standard():
    """A HARVEST task of 4000 units at a 500 units/hour standard, mid-shift."""
    state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
    worker = create_harvest_worker(full_name="Petra Lund", productivity_index=1.00)
    task = create_labor_task(
        state["zone"]["id"],
        state["cycle"]["id"],
        worker["id"],
        planned_units=4000,
        standard_units_per_hour=500,
        window_start="2026-08-06T07:00:00Z",
        window_end="2026-08-06T16:00:00Z",
    )
    set_clock("2026-08-06T07:00:00Z")
    transition_labor_task(
        task["id"], "IN_PROGRESS", make_harvest_supervisor_headers(worker["id"])
    )
    state["worker"] = worker
    state["task"] = task
    return state


def _lot_picked_on_the_week_boundary():
    """One cold-held lot picked 2026-08-31 with two open weeks around that date."""
    state = setup_cold_held_lot(
        production_clock="2026-08-31T06:00:00Z",
        lot_overrides={"harvest_date": "2026-08-31"},
    )
    program = create_retail_program(program_code="NL-TOV-A")
    state["program"] = program
    state["week_35"] = create_commitment_week(
        program["id"], iso_week="2026-W35", week_start_date="2026-08-24"
    )
    state["week_36"] = create_commitment_week(
        program["id"], iso_week="2026-W36", week_start_date="2026-08-31"
    )
    return state


class TestBonusThresholdIsInclusive:
    """4400 units in exactly 8.0 hours against a 500 units/hour standard."""

    def test_productivity_ratio_exactly_at_the_threshold_earns_the_bonus(self, api):
        """PRD §3.8: "`bonus_usd` is `actual_units` multiplied by 0.02 US dollars per unit, rounded half up to two decimal places, when `productivity_ratio` is at or above the bonus threshold of 1.10, and `0.00` otherwise — the threshold is inclusive, so a ratio of exactly 1.1000 earns the bonus."

        Design: Difficulty/boundary_precision_check/labor_productivity_ratio_exactly_at_bonus_threshold_pays_the_bonus
        """
        state = _task_in_progress_on_a_flat_standard()
        assert state["task"]["planned_hours"] == pytest.approx(8.00, abs=0.01), (
            "4000 units at a 500 units/hour standard on a 1.00 productivity index "
            f"plans 8.00 hours, got {state['task']['planned_hours']}"
        )
        assert state["task"]["planned_cost_usd"] == pytest.approx(156.00, abs=0.01), (
            "8.00 hours at 19.50 US dollars an hour with no overtime costs 156.00, got "
            f"{state['task']['planned_cost_usd']}"
        )

        completed = validate_success(
            api.transition_labor_task(
                state["task"]["id"],
                {"to_status": "COMPLETED", "actual_hours": 8.0, "actual_units": 4400},
                make_harvest_supervisor_headers(state["worker"]["id"]),
            ),
            200,
        )
        assert completed["status"] == "COMPLETED", (
            f"the task must reach COMPLETED, got {completed['status']}"
        )
        assert completed["productivity_ratio"] == pytest.approx(1.1000, abs=0.00005), (
            "4400 units over 8.0 hours against a 500 unit standard is exactly 1.1000, "
            f"got {completed['productivity_ratio']}"
        )
        assert completed["bonus_usd"] == pytest.approx(88.00, abs=0.01), (
            f"4400 units at 0.02 US dollars each pays 88.00, got {completed['bonus_usd']}"
        )
        assert completed["actual_cost_usd"] == pytest.approx(244.00, abs=0.01), (
            "156.00 of wage plus an 88.00 bonus settles at 244.00, got "
            f"{completed['actual_cost_usd']}"
        )

    def test_completion_replaces_the_planned_commitment_with_the_actual_cost(self, api):
        """PRD §3.8: "Completion then **replaces** this task's `planned_cost_usd` with its `actual_cost_usd` inside the compartment's `labor_budget_committed_usd` and recomputes `labor_budget_remaining_usd` accordingly, subtracts `planned_hours` from the worker's `committed_hours`, and increments the compartment's `version` by one."

        Design: Difficulty/boundary_precision_check/labor_productivity_ratio_exactly_at_bonus_threshold_pays_the_bonus
        """
        state = _task_in_progress_on_a_flat_standard()
        validate_success(
            api.transition_labor_task(
                state["task"]["id"],
                {"to_status": "COMPLETED", "actual_hours": 8.0, "actual_units": 4400},
                make_harvest_supervisor_headers(state["worker"]["id"]),
            ),
            200,
        )

        zone = read_zone(state["zone"]["id"])
        assert zone["labor_budget_committed_usd"] == pytest.approx(244.00, abs=0.01), (
            "the committed side must carry the actual cost rather than the planned one, "
            f"got {zone['labor_budget_committed_usd']}"
        )
        assert zone["labor_budget_remaining_usd"] == pytest.approx(19756.00, abs=0.01), (
            "20000.00 less the 244.00 actual cost leaves 19756.00, got "
            f"{zone['labor_budget_remaining_usd']}"
        )
        worker = read_worker(state["worker"]["id"])
        assert worker["committed_hours"] == pytest.approx(0.00, abs=0.01), (
            "completion removes the planned hours from the worker, got "
            f"{worker['committed_hours']}"
        )


class TestLotEligibilityWindowUpperBound:
    """A lot picked exactly seven days after a week start belongs to the next week."""

    def test_a_lot_on_the_excluded_upper_edge_leaves_the_run_with_no_candidates(self, api):
        """PRD §3.10: "It then builds its **candidate lot set**: every `HarvestLot` whose `grading_status` is `GRADED` or `REGRADED`, whose `cold_chain_status` is `PRECOOLED` or `COLD_HELD`, and whose `harvest_date` falls at or after the run's `week_start_date` and strictly before that date plus the `LOT_ELIGIBILITY_WINDOW_DAYS` window of 7 days — a half-open seven-day window, so a lot picked exactly seven days after the week start belongs to the next week, not this one."

        Design: Difficulty/boundary_precision_check/allocation_run_upper_bound_is_half_open_so_the_seventh_day_lot_is_not_eligible
        """
        state = _lot_picked_on_the_week_boundary()
        assert state["week_35"]["committed_lbs"] == pytest.approx(1000.00, abs=0.01), (
            "the week inherits the program's weekly commitment, got "
            f"{state['week_35']['committed_lbs']}"
        )

        response = api.create_allocation_run({"week_start_date": "2026-08-24"}, GM)
        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_LOTS.value)

    def test_the_same_lot_fills_the_week_starting_on_its_harvest_date(self, api):
        """PRD §3.10: "It then builds its **candidate lot set**: every `HarvestLot` whose `grading_status` is `GRADED` or `REGRADED`, whose `cold_chain_status` is `PRECOOLED` or `COLD_HELD`, and whose `harvest_date` falls at or after the run's `week_start_date` and strictly before that date plus the `LOT_ELIGIBILITY_WINDOW_DAYS` window of 7 days — a half-open seven-day window, so a lot picked exactly seven days after the week start belongs to the next week, not this one."

        Design: Difficulty/boundary_precision_check/allocation_run_upper_bound_is_half_open_so_the_seventh_day_lot_is_not_eligible
        """
        state = _lot_picked_on_the_week_boundary()
        evaluated = run_allocation("2026-08-31")
        assert len(evaluated) == 1, (
            f"only the 2026-08-31 week is a target for that run, got {len(evaluated)}"
        )
        week = evaluated[0]
        assert week["id"] == state["week_36"]["id"], (
            "the run must evaluate the week whose week_start_date it was given"
        )
        assert week["status"] == "ALLOCATED", (
            f"1000.00 covered pounds take the week to ALLOCATED, got {week['status']}"
        )
        assert week["allocated_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"the full commitment is drawn, got {week['allocated_lbs']}"
        )
        assert week["fill_rate_pct"] == pytest.approx(100.00, abs=0.01), (
            f"1000.00 of 1000.00 fills 100.00 percent, got {week['fill_rate_pct']}"
        )

        lot = read_lot(state["lot"]["id"])
        assert lot["allocated_a_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"grade A carries the whole take, got {lot['allocated_a_lbs']}"
        )
        assert lot["available_a_lbs"] == pytest.approx(200.00, abs=0.01), (
            f"1200.00 graded A less 1000.00 allocated leaves 200.00, got "
            f"{lot['available_a_lbs']}"
        )
        assert lot["available_b_lbs"] == pytest.approx(700.00, abs=0.01), (
            "an A_ONLY program never touches grade B, got "
            f"{lot['available_b_lbs']}"
        )

    def test_the_refused_run_leaves_the_earlier_week_wholly_unallocated(self, api):
        """PRD §3.10: "If the candidate set is empty the entire run is rejected with `ERR_NO_ELIGIBLE_LOTS` rather than returning an empty allocation set."

        Design: Difficulty/boundary_precision_check/allocation_run_upper_bound_is_half_open_so_the_seventh_day_lot_is_not_eligible
        """
        state = _lot_picked_on_the_week_boundary()
        validate_error(
            api.create_allocation_run({"week_start_date": "2026-08-24"}, GM),
            ApiErrorId.ERR_NO_ELIGIBLE_LOTS.value,
        )

        week = read_week(state["week_35"]["id"])
        assert week["status"] == "OPEN", (
            f"a refused run cannot move the week, got {week['status']}"
        )
        assert week["allocated_lbs"] == pytest.approx(0.00, abs=0.01), (
            f"no pounds may be promised, got {week['allocated_lbs']}"
        )
        assert week["provisional_shortfall_lbs"] == pytest.approx(1000.00, abs=0.01), (
            "the whole commitment is still short, got "
            f"{week['provisional_shortfall_lbs']}"
        )
        assert find_allocations() == [], (
            "a refused run mints no allocation rows at all"
        )
