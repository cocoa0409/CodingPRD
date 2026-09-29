"""State machine corners: initial states, declared edges, refused edges and terminality.

Every entity in this service is born in a declared initial state, moves only along the
edges the specification declares, and locks down once it reaches a terminal state. These
tests walk one happy path per machine and then push each machine off its declared edges
to confirm the refusal is loud rather than silent.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_three_decimal_places,
    create_climate_strategy_payload,
    create_commitment_week,
    create_drainage_reading,
    create_fertigation_batch,
    create_labor_task,
    create_retail_program,
    create_worker,
    create_zone,
    read_batch,
    read_crop_cycle,
    read_labor_task,
    read_program,
    read_week,
    read_zone,
    set_clock,
    setup_planned_cycle,
    setup_transplanted_cycle,
    transition_crop_cycle,
    transition_fertigation_batch,
    validate_error,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]


class TestFertigationBatchMachine:
    """MIXED is the initial state, the drainage reading is a self-loop, RECONCILED is the exit."""

    def test_a_batch_walks_from_mixed_through_delivered_to_reconciled(self, api):
        """PRD §3.5: "Finally, a delivered batch may be reconciled, moving `DELIVERED` → `RECONCILED`, but only once at least one drainage reading has been accepted against it; a batch with `drain_reading_count` of zero is rejected with `ERR_NO_DRAIN_READINGS`."

        Design: Corner/state_machines/fertigation_batch_is_born_in_mixed_and_walks_to_delivered_then_reconciled
        """
        state = setup_transplanted_cycle()
        batch = create_fertigation_batch(
            state["zone"]["id"],
            state["cycle"]["id"],
            requested_recirculated_liters=6000,
            reservoir_ec_ms=4.6,
        )
        assert batch["status"] == "MIXED", (
            f"a new batch is born MIXED, got {batch['status']}"
        )

        delivered = transition_fertigation_batch(
            batch["id"], "DELIVERED", delivered_volume_liters=12000
        )
        assert delivered["status"] == "DELIVERED"

        after_reading = create_drainage_reading(
            batch["id"],
            drain_volume_liters=3600.0,
            drain_ec_ms=3.4,
            reading_at="2026-08-06T12:00:00Z",
        )
        assert after_reading["status"] == "DELIVERED", (
            "the drainage-reading edge is a self-loop on DELIVERED, got "
            f"{after_reading['status']}"
        )

        reconciled = transition_fertigation_batch(batch["id"], "RECONCILED")
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["drain_fraction_pct"] == pytest.approx(30.00, abs=0.01), (
            "reconciliation freezes the 30.00 percent drain fraction, got "
            f"{reconciled['drain_fraction_pct']}"
        )

    def test_an_in_band_reading_raises_no_alarm_and_leaves_the_posture_normal(self, api):
        """PRD §3.5: "If any of the three holds and the batch's `drain_alarm` was still false, `drain_alarm` latches to true and the compartment's `drain_alarm_count` increments by exactly one."

        Design: Corner/state_machines/fertigation_batch_is_born_in_mixed_and_walks_to_delivered_then_reconciled
        """
        state = setup_transplanted_cycle()
        zone_id = state["zone"]["id"]
        batch = create_fertigation_batch(zone_id, state["cycle"]["id"])
        transition_fertigation_batch(
            batch["id"], "DELIVERED", delivered_volume_liters=12000
        )

        create_drainage_reading(
            batch["id"],
            drain_volume_liters=3600.0,
            drain_ec_ms=3.4,
            reading_at="2026-08-06T12:00:00Z",
        )

        assert read_batch(batch["id"])["drain_alarm"] is False, (
            "a 30.00 percent fraction against a 30 percent target with a 3.4 reading "
            "breaches nothing, got drain_alarm=True"
        )
        zone = read_zone(zone_id)
        assert zone["drain_alarm_count"] == 0, (
            f"no latch means no compartment counter, got {zone['drain_alarm_count']}"
        )
        assert zone["irrigation_posture"] == "NORMAL", (
            f"an unalarmed compartment stays NORMAL, got {zone['irrigation_posture']}"
        )

    def test_a_request_inside_the_cap_is_honoured_in_full(self, api):
        """PRD §3.5: "When the request is inside the cap, the technician's volume is honoured in full and `blended_ec_ms` equals `provisional_blend_ec_ms`."

        Design: Corner/state_machines/fertigation_batch_is_born_in_mixed_and_walks_to_delivered_then_reconciled
        """
        state = setup_transplanted_cycle()
        batch = create_fertigation_batch(
            state["zone"]["id"],
            state["cycle"]["id"],
            requested_recirculated_liters=6000,
            reservoir_ec_ms=4.6,
        )

        assert batch["recirc_cap_pct"] == 60, (
            "a provisional blend of 2.500 selects the 60 percent tier, got "
            f"{batch['recirc_cap_pct']}"
        )
        assert batch["recirculated_liters_applied"] == pytest.approx(6000, abs=0.01), (
            "6000 requested litres sit inside the 7200 litre cap, got "
            f"{batch['recirculated_liters_applied']}"
        )
        assert batch["fresh_liters_applied"] == pytest.approx(6000, abs=0.01), (
            f"the remaining 6000 litres are fresh water, got {batch['fresh_liters_applied']}"
        )
        assert_three_decimal_places(
            batch["blended_ec_ms"], 2.500, "blended_ec_ms"
        )


def _zone_without_lights_or_screen():
    """A POLY compartment with neither supplemental lighting nor a thermal screen."""
    set_clock("2026-08-06T00:00:00Z")
    return create_zone(
        code="ZC-11",
        glazing_type="POLY",
        has_thermal_screen=False,
        has_supplemental_lighting=False,
        chp_connected=False,
        hive_slot_capacity=4,
        labor_budget_usd=8000.00,
    )


class TestClimateStrategyCapabilityGate:
    """A window may only demand equipment the compartment actually has."""

    def test_lighting_hours_on_a_compartment_without_lights_is_refused(self, api):
        """PRD §3.4: "Demanding equipment the compartment does not have is rejected with `ERR_ZONE_CAPABILITY_MISSING`."

        Design: Corner/state_machines/climate_strategy_lighting_on_a_zone_without_lights_is_rejected
        """
        zone = _zone_without_lights_or_screen()

        response = api.create_climate_strategy(
            create_climate_strategy_payload(
                zone["id"], zone["version"], lighting_hours=6, screen_position_pct=0
            ),
            GM,
        )
        validate_error(response, ApiErrorId.ERR_ZONE_CAPABILITY_MISSING.value)

        after = read_zone(zone["id"])
        assert after["climate_plan_revision"] == 0, (
            "a refused window writes no plan revision, got "
            f"{after['climate_plan_revision']}"
        )

    def test_the_same_window_with_no_lighting_hours_is_accepted(self, api):
        """PRD §3.4: "Every create — superseding or not — must carry `expected_zone_version` matching the compartment's current `version` as described in §2.8, increments the compartment's `climate_plan_revision` by one, and increments the compartment's `version` by one."

        Design: Corner/state_machines/climate_strategy_lighting_on_a_zone_without_lights_is_rejected
        """
        zone = _zone_without_lights_or_screen()

        created = validate_success(
            api.create_climate_strategy(
                create_climate_strategy_payload(
                    zone["id"], zone["version"], lighting_hours=0, screen_position_pct=0
                ),
                GM,
            ),
            201,
        )
        assert created["status"] == "ACTIVE", (
            f"a newly created window sits in ACTIVE, got {created['status']}"
        )

        after = read_zone(zone["id"])
        assert after["climate_plan_revision"] == 1, (
            "an accepted window raises climate_plan_revision by one, got "
            f"{after['climate_plan_revision']}"
        )
        assert after["version"] == zone["version"] + 1, (
            "an accepted window raises the compartment version by one, got "
            f"{after['version']} from {zone['version']}"
        )


class TestLaborTaskEdgeDiscipline:
    """A scheduled task must be started before it can be completed."""

    def test_a_scheduled_task_cannot_jump_straight_to_completed(self, api):
        """PRD §2.10: "The requested from-state to to-state pair is one this specification declares for that entity — `ERR_INVALID_STATE_TRANSITION`, 409."

        Design: Corner/state_machines/labor_task_scheduled_cannot_jump_straight_to_completed
        """
        state = setup_transplanted_cycle()
        worker = create_worker(full_name="Petra Lund", productivity_index=1.00)
        task = create_labor_task(
            state["zone"]["id"],
            state["cycle"]["id"],
            worker["id"],
            planned_units=4000,
            standard_units_per_hour=500,
        )
        assert task["status"] == "SCHEDULED"

        response = api.transition_labor_task(
            task["id"],
            {"to_status": "COMPLETED", "actual_hours": 8.0, "actual_units": 4000},
            GM,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        after = read_labor_task(task["id"])
        assert after["status"] == "SCHEDULED", (
            f"the refused jump leaves the task SCHEDULED, got {after['status']}"
        )
        assert after["actual_hours"] is None, (
            f"no actual hours are recorded, got {after['actual_hours']}"
        )
        assert after["bonus_usd"] is None, (
            f"no bonus is computed, got {after['bonus_usd']}"
        )
        zone = read_zone(state["zone"]["id"])
        assert zone["labor_budget_committed_usd"] == pytest.approx(156.00, abs=0.01), (
            "8.00 planned hours at 19.50 remain committed at 156.00, got "
            f"{zone['labor_budget_committed_usd']}"
        )


def _unfilled_week_past_its_delivery_window():
    """One A_ONLY program and one 1000 pound week that never received an allocation."""
    set_clock("2026-08-31T06:00:00Z")
    program = create_retail_program(program_code="NL-TOV-T")
    week = create_commitment_week(program["id"])
    return {"program": program, "week": week}


def _close_week(api, week_id):
    return api.transition_commitment_week(week_id, {"to_status": "CLOSED_SHORT"}, GM)


class TestCommitmentWeekTerminality:
    """A week closed short is written off once, and never again."""

    def test_closing_before_the_delivery_window_has_elapsed_is_refused(self, api):
        """PRD §3.10: "A week may also be closed straight from `OPEN` to `CLOSED_SHORT`, which is how a week nobody could fill gets written off, but only once the delivery window has elapsed: the current logical clock date must be at or after `week_start_date` plus 7 days, and an early attempt is rejected with `ERR_WEEK_STILL_OPEN`."

        Design: Corner/state_machines/commitment_week_closed_short_cannot_transition_again
        """
        state = _unfilled_week_past_its_delivery_window()

        response = _close_week(api, state["week"]["id"])
        validate_error(response, ApiErrorId.ERR_WEEK_STILL_OPEN.value)

        after = read_week(state["week"]["id"])
        assert after["status"] == "OPEN", (
            f"the refused close leaves the week OPEN, got {after['status']}"
        )

    def test_closing_an_unfilled_week_writes_it_off_with_nothing_shipped(self, api):
        """PRD §3.10: "Closing from `OPEN` revokes every remaining `PROVISIONAL` or `CONFIRMED` row with `revoked_reason` `WEEK_CLOSED_SHORT`, restoring lot availability, and leaves `shipped_lbs` at `0.00` so the final penalty is the full committed shortfall."

        Design: Corner/state_machines/commitment_week_closed_short_cannot_transition_again
        """
        state = _unfilled_week_past_its_delivery_window()
        set_clock("2026-09-07T06:00:00Z")

        closed = validate_success(_close_week(api, state["week"]["id"]))
        assert closed["status"] == "CLOSED_SHORT", (
            f"an unshipped week closes short, got {closed['status']}"
        )
        assert closed["shipped_lbs"] == pytest.approx(0.00, abs=0.01), (
            f"nothing shipped, got {closed['shipped_lbs']}"
        )
        assert closed["final_shortfall_lbs"] == pytest.approx(1000.00, abs=0.01), (
            "the whole 1000 pound commitment is the final shortfall, got "
            f"{closed['final_shortfall_lbs']}"
        )
        assert closed["fill_rate_pct"] == pytest.approx(0.00, abs=0.01), (
            f"nothing shipped is a 0.00 fill rate, got {closed['fill_rate_pct']}"
        )

    def test_a_closed_short_week_refuses_any_further_transition(self, api):
        """PRD §2.10: "The entity is not already terminal for the dimension the request touches — `ERR_TERMINAL_STATE`, 409."

        Design: Corner/state_machines/commitment_week_closed_short_cannot_transition_again
        """
        state = _unfilled_week_past_its_delivery_window()
        week_id = state["week"]["id"]
        set_clock("2026-09-07T06:00:00Z")
        validate_success(_close_week(api, week_id))

        replay = _close_week(api, week_id)
        validate_error(replay, ApiErrorId.ERR_TERMINAL_STATE.value)

        after = read_week(week_id)
        assert after["status"] == "CLOSED_SHORT", (
            f"the refused replay leaves the week CLOSED_SHORT, got {after['status']}"
        )

    def test_the_final_penalty_posts_to_the_program_exactly_once(self, api):
        """PRD §3.10: "Closing then posts `final_penalty_usd` to the program's `penalty_accrued_usd`."

        Design: Corner/state_machines/commitment_week_closed_short_cannot_transition_again
        """
        state = _unfilled_week_past_its_delivery_window()
        program_id = state["program"]["id"]
        week_id = state["week"]["id"]
        assert read_program(program_id)["penalty_accrued_usd"] == pytest.approx(
            0.00, abs=0.01
        )

        set_clock("2026-09-07T06:00:00Z")
        closed = validate_success(_close_week(api, week_id))
        assert closed["final_penalty_usd"] == pytest.approx(400.00, abs=0.01), (
            "1000 short pounds at a 0.40 penalty rate is 400.00, got "
            f"{closed['final_penalty_usd']}"
        )
        assert read_program(program_id)["penalty_accrued_usd"] == pytest.approx(
            400.00, abs=0.01
        ), (
            "the closing posts the final penalty to the program, got "
            f"{read_program(program_id)['penalty_accrued_usd']}"
        )

        _close_week(api, week_id)
        assert read_program(program_id)["penalty_accrued_usd"] == pytest.approx(
            400.00, abs=0.01
        ), (
            "a refused replay must not post the penalty twice, got "
            f"{read_program(program_id)['penalty_accrued_usd']}"
        )


class TestCropCycleTransitionIsNotIdempotent:
    """A cycle is born PLANNED and may cross into TRANSPLANTED exactly once."""

    def test_a_new_cycle_is_born_planned_and_plants_its_compartment(self, api):
        """PRD §3.2: "A freshly planned cycle sits in `PLANNED`, and the compartment it now occupies re-derives its occupancy `status` to `PLANTED`."

        Design: Corner/state_machines/crop_cycle_transplanted_twice_is_rejected
        """
        state = setup_planned_cycle(clock="2026-08-06T00:00:00Z")

        assert state["cycle"]["status"] == "PLANNED", (
            f"a new cycle is born PLANNED, got {state['cycle']['status']}"
        )
        assert read_zone(state["zone"]["id"])["status"] == "PLANTED", (
            "the occupied compartment re-derives to PLANTED, got "
            f"{read_zone(state['zone']['id'])['status']}"
        )

    def test_transplanting_an_already_transplanted_cycle_is_refused(self, api):
        """PRD §2.10: "This also catches a repeated non-terminal trigger, such as grading a lot whose `grading_status` is already `GRADED` (a restatement must go through the regrade operation)."

        Design: Corner/state_machines/crop_cycle_transplanted_twice_is_rejected
        """
        state = setup_planned_cycle(clock="2026-08-06T00:00:00Z")
        cycle_id = state["cycle"]["id"]

        first = transition_crop_cycle(cycle_id, "TRANSPLANTED")
        assert first["status"] == "TRANSPLANTED"

        replay = api.transition_crop_cycle(
            cycle_id, {"to_status": "TRANSPLANTED"}, GM
        )
        validate_error(replay, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        after = read_crop_cycle(cycle_id)
        assert after["status"] == "TRANSPLANTED", (
            f"the refused replay leaves the cycle TRANSPLANTED, got {after['status']}"
        )
        assert read_zone(state["zone"]["id"])["status"] == "PLANTED", (
            "the compartment still reads PLANTED, got "
            f"{read_zone(state['zone']['id'])['status']}"
        )
