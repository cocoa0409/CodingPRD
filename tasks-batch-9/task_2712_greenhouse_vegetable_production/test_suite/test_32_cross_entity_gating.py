"""Writes on one resource that are gated on a second resource's own state.

Two gates are exercised: confirming an allocation row is gated on the cold chain
dimension of the harvest lot behind it, and creating a labor task is gated on the
pest posture derived on the compartment.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cold_chain_event,
    create_commitment_week,
    create_harvest_worker,
    create_labor_task_payload,
    create_posture_override,
    create_retail_program,
    find_allocations,
    read_allocation,
    read_labor_task,
    read_lot,
    read_week,
    read_worker,
    read_zone,
    run_allocation,
    setup_ipm_locked_zone,
    setup_precooled_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]
QI = TEST_USERS["quality_inspector_headers"]


def _provisional_row_on_a_precooled_lot():
    """One provisional row drawn by a run from a lot that is only PRECOOLED."""
    state = setup_precooled_lot(
        production_clock="2026-08-31T06:00:00Z",
        lot_overrides={"harvest_date": "2026-08-31"},
    )
    program = create_retail_program(program_code="NL-TOV-A")
    week = create_commitment_week(
        program["id"], iso_week="2026-W36", week_start_date="2026-08-31"
    )
    run_allocation("2026-08-31")
    rows = find_allocations(commitment_week_id=week["id"])
    state["program"] = program
    state["week"] = week
    state["rows"] = rows
    return state


def _ipm_locked_zone_and_harvest_worker():
    """A TRANSPLANTED cycle in a pest-locked compartment plus an idle HARVEST worker."""
    state = setup_ipm_locked_zone()
    state["harvest_worker"] = create_harvest_worker()
    return state


class TestConfirmIsGatedOnTheLotColdChain:
    """The waterfall draws from a pre-cooled lot, but confirmation will not."""

    def test_a_merely_precooled_lot_cannot_have_its_row_confirmed(self, api):
        """PRD §3.10: "It requires the owning week's `status` to be `ALLOCATED`, rejected otherwise with `ERR_WEEK_NOT_ALLOCATED`; the lot's `cold_chain_status` to be exactly `COLD_HELD`, rejected otherwise with `ERR_LOT_NOT_COLD_HELD`, so a merely pre-cooled lot that the waterfall was happy to draw from cannot yet be confirmed; and the lot's `grading_status` to be `GRADED` or `REGRADED`, rejected otherwise with `ERR_LOT_NOT_GRADED`."

        Design: Difficulty/cross_entity_state_dependency/lot_allocation_confirm_is_gated_on_the_harvest_lot_cold_chain_dimension
        """
        state = _provisional_row_on_a_precooled_lot()
        assert len(state["rows"]) == 1, (
            f"the run must mint exactly one row for the week, got {len(state['rows'])}"
        )
        row = state["rows"][0]
        assert row["status"] == "PROVISIONAL", (
            f"a fresh run mints provisional pounds, got {row['status']}"
        )
        assert read_lot(state["lot"]["id"])["cold_chain_status"] == "PRECOOLED", (
            "the lot behind the row must still be pre-cooled for this gate to matter"
        )
        assert read_week(state["week"]["id"])["status"] == "ALLOCATED", (
            "the week must already be ALLOCATED so the cold chain gate is the one that fires"
        )

        response = api.transition_lot_allocation(
            row["id"], {"to_status": "CONFIRMED"}, QI
        )
        validate_error(response, ApiErrorId.ERR_LOT_NOT_COLD_HELD.value)

        after = read_allocation(row["id"])
        assert after["status"] == "PROVISIONAL", (
            f"a refused confirmation leaves the row provisional, got {after['status']}"
        )
        assert after["version"] == row["version"], (
            f"a refused confirmation is not a mutation, expected version "
            f"{row['version']}, got {after['version']}"
        )

    def test_moving_the_lot_into_cold_storage_opens_the_same_confirmation(self, api):
        """PRD §3.10: "It requires the owning week's `status` to be `ALLOCATED`, rejected otherwise with `ERR_WEEK_NOT_ALLOCATED`; the lot's `cold_chain_status` to be exactly `COLD_HELD`, rejected otherwise with `ERR_LOT_NOT_COLD_HELD`, so a merely pre-cooled lot that the waterfall was happy to draw from cannot yet be confirmed; and the lot's `grading_status` to be `GRADED` or `REGRADED`, rejected otherwise with `ERR_LOT_NOT_GRADED`."

        Design: Difficulty/cross_entity_state_dependency/lot_allocation_confirm_is_gated_on_the_harvest_lot_cold_chain_dimension
        """
        state = _provisional_row_on_a_precooled_lot()
        row = state["rows"][0]
        validate_error(
            api.transition_lot_allocation(row["id"], {"to_status": "CONFIRMED"}, QI),
            ApiErrorId.ERR_LOT_NOT_COLD_HELD.value,
        )

        held = cold_chain_event(state["lot"]["id"], "COLD_HELD", 6.0)
        assert held["cold_chain_status"] == "COLD_HELD", (
            f"the lot must reach cold storage, got {held['cold_chain_status']}"
        )

        confirmed = validate_success(
            api.transition_lot_allocation(row["id"], {"to_status": "CONFIRMED"}, QI), 200
        )
        assert confirmed["status"] == "CONFIRMED", (
            f"the identical request must now succeed, got {confirmed['status']}"
        )
        assert confirmed["allocated_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"confirmation does not resize the row, got {confirmed['allocated_lbs']}"
        )

    def test_confirmation_moves_no_pounds_on_either_side(self, api):
        """PRD §3.10: "Confirmation moves no pounds at all: `CONFIRMED` still counts toward the week's `allocated_lbs` and toward the lot's allocated pool exactly as `PROVISIONAL` did."

        Design: Difficulty/cross_entity_state_dependency/lot_allocation_confirm_is_gated_on_the_harvest_lot_cold_chain_dimension
        """
        state = _provisional_row_on_a_precooled_lot()
        row = state["rows"][0]
        cold_chain_event(state["lot"]["id"], "COLD_HELD", 6.0)
        validate_success(
            api.transition_lot_allocation(row["id"], {"to_status": "CONFIRMED"}, QI), 200
        )

        lot = read_lot(state["lot"]["id"])
        assert lot["allocated_a_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"the lot's allocated pool is unchanged, got {lot['allocated_a_lbs']}"
        )
        assert lot["available_a_lbs"] == pytest.approx(200.00, abs=0.01), (
            f"the lot's available pool is unchanged, got {lot['available_a_lbs']}"
        )
        week = read_week(state["week"]["id"])
        assert week["allocated_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"confirmed pounds still count as allocated, got {week['allocated_lbs']}"
        )
        assert week["status"] == "ALLOCATED", (
            f"the week does not move on a confirmation, got {week['status']}"
        )


class TestLaborTaskCreationIsGatedOnThePestPosture:
    """A pest-locked compartment refuses new crew work until a grower overrules it."""

    def test_a_pest_locked_compartment_refuses_the_task(self, api):
        """PRD §3.8: "The compartment's `ipm_posture` must not be `LOCKED`, rejected with `ERR_ZONE_IPM_LOCKED`, and the current logical clock must have reached the compartment's `reentry_clear_at` whenever that field is set, rejected with `ERR_REENTRY_INTERVAL_ACTIVE`; both of these safety gates outrank everything below them."

        Design: Difficulty/cross_entity_state_dependency/labor_task_creation_is_gated_on_the_zone_ipm_posture_until_overridden
        """
        state = _ipm_locked_zone_and_harvest_worker()
        zone = read_zone(state["zone"]["id"])
        assert zone["open_pest_alert_count"] == 2, (
            "two at-or-above observations open two alerts, got "
            f"{zone['open_pest_alert_count']}"
        )
        assert zone["ipm_posture"] == "LOCKED", (
            f"two open alerts lock the pest gate, got {zone['ipm_posture']}"
        )

        response = api.create_labor_task(
            create_labor_task_payload(
                state["zone"]["id"], state["cycle"]["id"], state["harvest_worker"]["id"]
            ),
            GM,
        )
        validate_error(response, ApiErrorId.ERR_ZONE_IPM_LOCKED.value)

        tasks, meta = validate_paginated(
            api.list_labor_tasks(GM, params={"zone_id": state["zone"]["id"]})
        )
        assert tasks == [], f"a refused creation may not write a task, got {tasks}"
        assert meta["total_count"] == 0, (
            f"no task row may exist on the compartment, got {meta['total_count']}"
        )
        after = read_zone(state["zone"]["id"])
        assert after["labor_budget_committed_usd"] == pytest.approx(0.00, abs=0.01), (
            "a refused creation commits no money, got "
            f"{after['labor_budget_committed_usd']}"
        )
        assert read_worker(state["harvest_worker"]["id"])[
            "committed_hours"
        ] == pytest.approx(0.00, abs=0.01), "a refused creation commits no worker hours"

    def test_a_grower_override_lets_the_identical_request_through(self, api):
        """PRD §3.6: "An override of `ipm_posture` clears `open_pest_alert_count` to 0 and `reentry_clear_at` to null and sets `ipm_posture` to `NORMAL`, and it works from either `LOCKED` or `SCOUT_ALERT`."

        Design: Difficulty/cross_entity_state_dependency/labor_task_creation_is_gated_on_the_zone_ipm_posture_until_overridden
        """
        state = _ipm_locked_zone_and_harvest_worker()
        payload = create_labor_task_payload(
            state["zone"]["id"], state["cycle"]["id"], state["harvest_worker"]["id"]
        )
        validate_error(
            api.create_labor_task(payload, GM), ApiErrorId.ERR_ZONE_IPM_LOCKED.value
        )

        locked = read_zone(state["zone"]["id"])
        cleared = create_posture_override(locked["id"], locked["version"])
        assert cleared["ipm_posture"] == "NORMAL", (
            f"the override forces the pest gate to NORMAL, got {cleared['ipm_posture']}"
        )
        assert cleared["open_pest_alert_count"] == 0, (
            f"the override clears the open alerts, got {cleared['open_pest_alert_count']}"
        )
        assert cleared["reentry_clear_at"] is None, (
            f"the override clears the re-entry clock, got {cleared['reentry_clear_at']}"
        )

        task = validate_success(api.create_labor_task(payload, GM), 201)
        assert task["status"] == "SCHEDULED", (
            f"the identical request must now be accepted, got {task['status']}"
        )
        assert task["planned_hours"] == pytest.approx(7.69, abs=0.01), (
            "4200 units against a 520 unit standard on a 1.05 index plans 7.69 hours, got "
            f"{task['planned_hours']}"
        )
        assert task["planned_cost_usd"] == pytest.approx(149.96, abs=0.01), (
            f"7.69 hours at 19.50 US dollars an hour costs 149.96, got "
            f"{task['planned_cost_usd']}"
        )

    def test_the_task_admitted_after_the_override_commits_money_and_hours(self, api):
        """PRD §3.8: "Scheduling the task commits the money and the time: `planned_cost_usd` is added to the compartment's `labor_budget_committed_usd` and subtracted from `labor_budget_remaining_usd`, `planned_hours` is added to the worker's `committed_hours`, the compartment's `version` increments by one, and the task sits in `SCHEDULED` with null `actual_hours`, `actual_units`, `productivity_ratio`, `bonus_usd`, `actual_cost_usd` and `cancel_reason`."

        Design: Difficulty/cross_entity_state_dependency/labor_task_creation_is_gated_on_the_zone_ipm_posture_until_overridden
        """
        state = _ipm_locked_zone_and_harvest_worker()
        locked = read_zone(state["zone"]["id"])
        create_posture_override(locked["id"], locked["version"])

        task = validate_success(
            api.create_labor_task(
                create_labor_task_payload(
                    state["zone"]["id"],
                    state["cycle"]["id"],
                    state["harvest_worker"]["id"],
                ),
                GM,
            ),
            201,
        )
        assert read_labor_task(task["id"])["status"] == "SCHEDULED", (
            "the admitted task must be readable back as SCHEDULED"
        )

        zone = read_zone(state["zone"]["id"])
        assert zone["labor_budget_committed_usd"] == pytest.approx(149.96, abs=0.01), (
            "the planned cost joins the committed side, got "
            f"{zone['labor_budget_committed_usd']}"
        )
        assert zone["labor_budget_remaining_usd"] == pytest.approx(19850.04, abs=0.01), (
            "20000.00 less 149.96 leaves 19850.04, got "
            f"{zone['labor_budget_remaining_usd']}"
        )
        worker = read_worker(state["harvest_worker"]["id"])
        assert worker["committed_hours"] == pytest.approx(7.69, abs=0.01), (
            f"the planned hours join the worker, got {worker['committed_hours']}"
        )
