"""Compensating invariants: money and pounds that must come back exactly as they left.

A compartment's labor budget is split into a committed half and a remaining half whose
sum never moves, and a graded harvest lot's pounds are split into an allocated pool and
an available pool whose sum never moves either. Each pairing is exercised by driving a
forward operation and then its undo, and checking that the conserved total holds at
every step rather than only at the end.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    TEST_USERS,
    assert_lot_grade_pools_conserved,
    assert_zone_budget_conserved,
    create_commitment_week,
    create_labor_task,
    create_retail_program,
    create_worker,
    find_allocations,
    read_lot,
    read_program,
    read_week,
    read_worker,
    read_zone,
    run_allocation,
    setup_cold_held_lot,
    setup_transplanted_cycle,
    transition_labor_task,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]


def _zone_with_one_scheduled_task():
    """A TRANSPLANTED cycle plus one SCHEDULED harvest task on a fresh worker."""
    state = setup_transplanted_cycle()
    worker = create_worker()
    state["worker"] = worker
    state["task"] = create_labor_task(
        state["zone"]["id"], state["cycle"]["id"], worker["id"]
    )
    return state


class TestZoneLaborBudgetConservation:
    """Scheduling borrows from the remaining half; cancelling pays it back in full."""

    def test_scheduling_commits_the_money_and_the_time(self, api):
        """PRD §3.8: "Scheduling the task commits the money and the time: `planned_cost_usd` is added to the compartment's `labor_budget_committed_usd` and subtracted from `labor_budget_remaining_usd`, `planned_hours` is added to the worker's `committed_hours`, the compartment's `version` increments by one, and the task sits in `SCHEDULED` with null `actual_hours`, `actual_units`, `productivity_ratio`, `bonus_usd`, `actual_cost_usd` and `cancel_reason`."

        Design: Difficulty/compensating_invariant/zone_labor_budget_money_is_conserved_across_task_create_and_cancel
        """
        state = _zone_with_one_scheduled_task()
        task = state["task"]

        assert task["status"] == "SCHEDULED"
        assert task["planned_hours"] == pytest.approx(7.69, abs=0.01), (
            f"4200 units at 520 per hour and a 1.05 index plans 7.69 hours, got {task['planned_hours']}"
        )
        assert task["planned_cost_usd"] == pytest.approx(149.96, abs=0.01), (
            f"7.69 hours at 19.50 an hour costs 149.96, got {task['planned_cost_usd']}"
        )

        zone = read_zone(state["zone"]["id"])
        assert zone["labor_budget_committed_usd"] == pytest.approx(149.96, abs=0.01), (
            f"the planned cost joins the committed half, got {zone['labor_budget_committed_usd']}"
        )
        assert zone["labor_budget_remaining_usd"] == pytest.approx(19850.04, abs=0.01), (
            "the same amount leaves the remaining half, got "
            f"{zone['labor_budget_remaining_usd']}"
        )
        assert read_worker(state["worker"]["id"])["committed_hours"] == pytest.approx(
            7.69, abs=0.01
        ), "the planned hours join the worker's committed hours"

    def test_cancelling_restores_exactly_the_planned_cost_and_hours(self, api):
        """PRD §3.8: "Cancelling a task, reachable from either `SCHEDULED` or `IN_PROGRESS` and carrying a `cancel_reason`, removes exactly `planned_cost_usd` from the compartment's `labor_budget_committed_usd`, restores exactly `planned_cost_usd` to `labor_budget_remaining_usd`, subtracts `planned_hours` from the worker's `committed_hours`, and increments the compartment's `version` by one."

        Design: Difficulty/compensating_invariant/zone_labor_budget_money_is_conserved_across_task_create_and_cancel
        """
        state = _zone_with_one_scheduled_task()
        planned_cost = state["task"]["planned_cost_usd"]
        planned_hours = state["task"]["planned_hours"]
        committed_zone = read_zone(state["zone"]["id"])

        cancelled = transition_labor_task(
            state["task"]["id"], "CANCELLED", cancel_reason="Crew reassigned"
        )
        assert cancelled["status"] == "CANCELLED"

        released_zone = read_zone(state["zone"]["id"])
        assert released_zone["labor_budget_committed_usd"] == pytest.approx(
            committed_zone["labor_budget_committed_usd"] - planned_cost, abs=0.01
        ), (
            "exactly the planned cost leaves the committed half, got "
            f"{released_zone['labor_budget_committed_usd']}"
        )
        assert released_zone["labor_budget_remaining_usd"] == pytest.approx(
            committed_zone["labor_budget_remaining_usd"] + planned_cost, abs=0.01
        ), (
            "exactly the planned cost returns to the remaining half, got "
            f"{released_zone['labor_budget_remaining_usd']}"
        )
        assert read_worker(state["worker"]["id"])["committed_hours"] == pytest.approx(
            0.00, abs=0.01
        ), (
            f"the {planned_hours} planned hours leave the worker on cancellation, got "
            f"{read_worker(state['worker']['id'])['committed_hours']}"
        )
        assert released_zone["version"] > committed_zone["version"], (
            "the compartment version advances on the cancellation, got "
            f"{released_zone['version']} from {committed_zone['version']}"
        )

    def test_the_two_budget_halves_sum_to_the_compartment_budget_at_every_step(self, api):
        """PRD §2.9: "A compartment's `labor_budget_usd` is split into `labor_budget_committed_usd` and `labor_budget_remaining_usd`, and the two always sum to `labor_budget_usd`."

        Design: Difficulty/compensating_invariant/zone_labor_budget_money_is_conserved_across_task_create_and_cancel
        """
        state = setup_transplanted_cycle()
        zone_id = state["zone"]["id"]

        fresh = read_zone(zone_id)
        assert_zone_budget_conserved(fresh)
        assert fresh["labor_budget_usd"] == pytest.approx(20000.00, abs=0.01)

        worker = create_worker()
        task = create_labor_task(zone_id, state["cycle"]["id"], worker["id"])
        after_schedule = read_zone(zone_id)
        assert_zone_budget_conserved(after_schedule)
        assert after_schedule[
            "labor_budget_committed_usd"
        ] + after_schedule["labor_budget_remaining_usd"] == pytest.approx(
            20000.00, abs=0.01
        ), "the halves still sum to the compartment budget while money is committed"

        transition_labor_task(task["id"], "CANCELLED", cancel_reason="Crew reassigned")
        after_cancel = read_zone(zone_id)
        assert_zone_budget_conserved(after_cancel)
        assert after_cancel["labor_budget_committed_usd"] + after_cancel[
            "labor_budget_remaining_usd"
        ] == pytest.approx(20000.00, abs=0.01), (
            "the halves still sum to the compartment budget after the repayment"
        )


def _allocated_week_drawing_on_one_lot():
    """One COLD_HELD lot graded to 1200 A pounds, fully covering a 1000 pound week."""
    state = setup_cold_held_lot(
        plan_clock=CLOCK_EPOCH,
        production_clock="2026-08-31T06:00:00Z",
        lot_overrides={"harvest_date": "2026-08-31"},
    )
    program = create_retail_program()
    week = create_commitment_week(program["id"])
    run_allocation("2026-08-31")
    rows = find_allocations(commitment_week_id=week["id"])
    assert len(rows) == 1, f"the waterfall mints one row from one lot, got {len(rows)}"
    state["program"] = program
    state["week"] = week
    state["allocation"] = rows[0]
    return state


def _revoke(api, allocation_id):
    return validate_success(
        api.transition_lot_allocation(
            allocation_id,
            {
                "to_status": "REVOKED",
                "revoked_reason": "Fruit redirected to a wholesale buyer",
            },
            GM,
        )
    )


class TestHarvestLotPoundConservation:
    """Allocating and revoking move pounds between two pools whose sum never changes."""

    def test_minting_moves_pounds_out_of_the_available_pool_into_the_allocated_pool(
        self, api
    ):
        """PRD §3.10: "Minting an allocation adds its `allocated_lbs` to the lot's `allocated_a_lbs` or `allocated_b_lbs` according to its `grade` and subtracts the same amount from the matching available pool, and adds the same amount to the week's `allocated_lbs`."

        Design: Difficulty/compensating_invariant/harvest_lot_graded_pounds_are_conserved_across_allocate_and_revoke
        """
        state = _allocated_week_drawing_on_one_lot()
        row = state["allocation"]

        assert row["grade"] == "A", (
            f"an A_ONLY program draws grade A, got {row['grade']}"
        )
        assert row["allocated_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"a 1000 pound commitment takes 1000 pounds, got {row['allocated_lbs']}"
        )

        lot = read_lot(state["lot"]["id"])
        assert lot["allocated_a_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"the take joins allocated_a_lbs, got {lot['allocated_a_lbs']}"
        )
        assert lot["available_a_lbs"] == pytest.approx(200.00, abs=0.01), (
            "the same amount leaves available_a_lbs of the 1200 graded pounds, got "
            f"{lot['available_a_lbs']}"
        )
        assert_lot_grade_pools_conserved(lot)

        week = read_week(state["week"]["id"])
        assert week["allocated_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"the same amount joins the week's allocated_lbs, got {week['allocated_lbs']}"
        )

    def test_revoking_hands_back_exactly_the_allocated_pounds(self, api):
        """PRD §3.10: "Hop one subtracts `allocated_lbs` from the lot's `allocated_a_lbs` or `allocated_b_lbs` according to the row's `grade` and adds exactly the same amount back to the matching available pool."

        Design: Difficulty/compensating_invariant/harvest_lot_graded_pounds_are_conserved_across_allocate_and_revoke
        """
        state = _allocated_week_drawing_on_one_lot()
        lot_id = state["lot"]["id"]
        before = read_lot(lot_id)

        revoked = _revoke(api, state["allocation"]["id"])
        assert revoked["status"] == "REVOKED"

        after = read_lot(lot_id)
        assert after["allocated_a_lbs"] == pytest.approx(
            before["allocated_a_lbs"] - 1000.00, abs=0.01
        ), (
            f"exactly 1000 pounds leave allocated_a_lbs, got {after['allocated_a_lbs']}"
        )
        assert after["available_a_lbs"] == pytest.approx(
            before["available_a_lbs"] + 1000.00, abs=0.01
        ), (
            f"exactly the same 1000 pounds return to available_a_lbs, got {after['available_a_lbs']}"
        )
        assert after["available_a_lbs"] == pytest.approx(1200.00, abs=0.01), (
            "the whole graded A pool is available again, got "
            f"{after['available_a_lbs']}"
        )
        assert_lot_grade_pools_conserved(after)

    def test_the_second_hop_restates_the_week_and_reverts_it_to_open(self, api):
        """PRD §3.10: "Hop two, caused by hop one, drops the week's `allocated_lbs` by the same amount and recomputes its `fill_rate_pct`, `provisional_shortfall_lbs` and `provisional_penalty_usd`; a week that was `ALLOCATED` and is now short of its `committed_lbs` reverts `ALLOCATED` → `OPEN`."

        Design: Difficulty/compensating_invariant/harvest_lot_graded_pounds_are_conserved_across_allocate_and_revoke
        """
        state = _allocated_week_drawing_on_one_lot()
        week_id = state["week"]["id"]

        filled = read_week(week_id)
        assert filled["status"] == "ALLOCATED", (
            f"a fully covered week reads ALLOCATED, got {filled['status']}"
        )

        _revoke(api, state["allocation"]["id"])

        emptied = read_week(week_id)
        assert emptied["allocated_lbs"] == pytest.approx(0.00, abs=0.01), (
            f"the revoked pounds leave the week, got {emptied['allocated_lbs']}"
        )
        assert emptied["fill_rate_pct"] == pytest.approx(0.00, abs=0.01), (
            f"nothing allocated is a 0.00 fill rate, got {emptied['fill_rate_pct']}"
        )
        assert emptied["provisional_shortfall_lbs"] == pytest.approx(1000.00, abs=0.01), (
            "the whole 1000 pound commitment is short again, got "
            f"{emptied['provisional_shortfall_lbs']}"
        )
        assert emptied["provisional_penalty_usd"] == pytest.approx(400.00, abs=0.01), (
            "1000 short pounds at a 0.40 penalty rate is 400.00, got "
            f"{emptied['provisional_penalty_usd']}"
        )
        assert emptied["status"] == "OPEN", (
            f"a week short of its commitment reverts to OPEN, got {emptied['status']}"
        )

    def test_the_third_hop_counts_the_reverted_week_as_at_risk(self, api):
        """PRD §3.10: "Hop three, caused by hop two's reversion and only by it, increments the program's `at_risk_week_count` by one — a week that was already `OPEN` and merely got shorter does not increment that counter."

        Design: Difficulty/compensating_invariant/harvest_lot_graded_pounds_are_conserved_across_allocate_and_revoke
        """
        state = _allocated_week_drawing_on_one_lot()
        program_id = state["program"]["id"]

        assert read_program(program_id)["at_risk_week_count"] == 0, (
            "an allocated week is not yet at risk, got "
            f"{read_program(program_id)['at_risk_week_count']}"
        )

        _revoke(api, state["allocation"]["id"])

        assert read_program(program_id)["at_risk_week_count"] == 1, (
            "the ALLOCATED to OPEN reversion counts the week as at risk, got "
            f"{read_program(program_id)['at_risk_week_count']}"
        )

    def test_the_provisional_penalty_never_posts_to_the_program(self, api):
        """PRD §3.10: "This penalty is **advisory only**: it never posts to the program's `penalty_accrued_usd`, no matter how large it grows or how long the week sits there."

        Design: Difficulty/compensating_invariant/harvest_lot_graded_pounds_are_conserved_across_allocate_and_revoke
        """
        state = _allocated_week_drawing_on_one_lot()
        program_id = state["program"]["id"]

        _revoke(api, state["allocation"]["id"])

        week = read_week(state["week"]["id"])
        assert week["provisional_penalty_usd"] == pytest.approx(400.00, abs=0.01), (
            "the advisory penalty is carried on the week, got "
            f"{week['provisional_penalty_usd']}"
        )
        program = read_program(program_id)
        assert program["penalty_accrued_usd"] == pytest.approx(0.00, abs=0.01), (
            "no advisory penalty reaches the program's accrual, got "
            f"{program['penalty_accrued_usd']}"
        )
