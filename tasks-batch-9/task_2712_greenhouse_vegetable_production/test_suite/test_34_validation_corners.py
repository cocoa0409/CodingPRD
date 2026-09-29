"""Individual validation gates at their awkward edges.

Each gate here is checked from both sides where the contract makes both sides
observable: a recipe tolerance that admits 0.7 and refuses 1.0, an aggregate hive
capacity that no single placement breaches, a pack-out floor that an explicit
acknowledgement unlocks, and a fiscal ceiling that refuses a task outright.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_fertigation_batch_payload,
    create_harvest_worker,
    create_hive_placement,
    create_labor_task_payload,
    grade_harvest_lot_payload,
    make_harvest_supervisor_headers,
    read_crop_cycle,
    read_lot,
    read_worker,
    read_zone,
    setup_production_cycle,
    setup_registered_lot,
    setup_transplanted_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]
IT = TEST_USERS["irrigation_tech_headers"]

PLAN_CLOCK = "2026-08-06T00:00:00Z"
PRODUCTION_CLOCK = "2026-08-24T06:00:00Z"


def _cycle_on_a_three_ms_recipe():
    """A TRANSPLANTED cycle whose cultivar asks for an EC of 3.0 millisiemens."""
    return setup_transplanted_cycle(clock=PLAN_CLOCK)


def _cycle_with_five_hives_placed():
    """A PRODUCTION cycle holding five of the compartment's eight hive slots."""
    state = setup_production_cycle(production_clock=PRODUCTION_CLOCK)
    state["first_placement"] = create_hive_placement(
        state["cycle"]["id"], 5, "2026-08-24T08:00:00Z"
    )
    return state


def _zone_with_a_hundred_dollar_budget():
    """A TRANSPLANTED cycle in a compartment whose entire labor budget is 100.00."""
    state = setup_transplanted_cycle(
        clock=PLAN_CLOCK, zone_overrides={"labor_budget_usd": 100.00}
    )
    state["harvest_worker"] = create_harvest_worker()
    return state


class TestFertigationRecipeTolerance:
    """The feed conductivity is judged against the cultivar behind the cycle."""

    def test_a_feed_a_full_millisiemens_off_the_recipe_is_refused(self, api):
        """PRD §3.5: "The batch's `target_ec_ms` must sit within 0.8 millisiemens per centimetre of the cultivar behind the named crop cycle — the check reaches through `crop_cycle_id` to `variety_id` and reads that cultivar's `ec_target_ms` — and a deviation beyond that tolerance is rejected with `ERR_TARGET_EC_OFF_RECIPE`."

        Design: Corner/validations/fertigation_target_ec_off_the_variety_recipe_is_rejected
        """
        state = _cycle_on_a_three_ms_recipe()
        assert state["variety"]["ec_target_ms"] == pytest.approx(3.0, abs=0.0005), (
            f"the cultivar recipe must read 3.0, got {state['variety']['ec_target_ms']}"
        )

        response = api.create_fertigation_batch(
            create_fertigation_batch_payload(
                state["zone"]["id"], state["cycle"]["id"], target_ec_ms=4.0
            ),
            IT,
        )
        validate_error(response, ApiErrorId.ERR_TARGET_EC_OFF_RECIPE.value)

        batches, meta = validate_paginated(
            api.list_fertigation_batches(GM, params={"zone_id": state["zone"]["id"]})
        )
        assert batches == [], f"a refused mix writes no batch, got {batches}"
        assert meta["total_count"] == 0, (
            f"no batch row may exist on the compartment, got {meta['total_count']}"
        )

    def test_a_feed_inside_the_tolerance_band_is_mixed(self, api):
        """PRD §3.5: "The batch's `target_ec_ms` must sit within 0.8 millisiemens per centimetre of the cultivar behind the named crop cycle — the check reaches through `crop_cycle_id` to `variety_id` and reads that cultivar's `ec_target_ms` — and a deviation beyond that tolerance is rejected with `ERR_TARGET_EC_OFF_RECIPE`."

        Design: Corner/validations/fertigation_target_ec_inside_the_tolerance_band_is_accepted
        """
        state = _cycle_on_a_three_ms_recipe()
        batch = validate_success(
            api.create_fertigation_batch(
                create_fertigation_batch_payload(
                    state["zone"]["id"], state["cycle"]["id"], target_ec_ms=3.7
                ),
                IT,
            ),
            201,
        )
        assert batch["status"] == "MIXED", (
            f"a newly mixed batch sits in MIXED, got {batch['status']}"
        )
        assert batch["target_ec_ms"] == pytest.approx(3.7, abs=0.0005), (
            "a deviation of 0.7 is inside the tolerance and is stored as asked, got "
            f"{batch['target_ec_ms']}"
        )
        assert batch["drain_reading_count"] == 0, (
            f"no drainage reading has been filed yet, got {batch['drain_reading_count']}"
        )


class TestHiveSlotCapacityIsAnAggregate:
    """Each placement can look modest while the set of them overruns the compartment."""

    def test_a_placement_that_would_overrun_the_compartment_is_refused(self, api):
        """PRD §3.7: "Two gates apply: the placement is blocked while the compartment's `ipm_posture` is `LOCKED`, rejected with `ERR_ZONE_IPM_LOCKED`, since nobody may walk into a locked compartment to set hives; and the compartment's `hive_slots_used`, which is the sum of `hive_count_placed` across every cycle in the compartment whose status is `TRANSPLANTED`, `PRODUCTION`, or `TERMINATION_SCHEDULED`, must remain within `hive_slot_capacity` after the placement, or the request is rejected with `ERR_HIVE_SLOTS_EXCEEDED`."

        Design: Corner/validations/hive_placements_exceeding_the_zone_slot_capacity_are_rejected
        """
        state = _cycle_with_five_hives_placed()
        assert state["first_placement"]["hive_count_placed"] == 5, (
            "the first placement seats five hives, got "
            f"{state['first_placement']['hive_count_placed']}"
        )
        assert read_zone(state["zone"]["id"])["hive_slot_capacity"] == 8, (
            "the compartment must offer eight slots for this aggregate to bite"
        )

        response = api.create_hive_placement(
            state["cycle"]["id"],
            {"hive_count": 4, "placed_at": "2026-08-24T09:00:00Z"},
            GM,
        )
        validate_error(response, ApiErrorId.ERR_HIVE_SLOTS_EXCEEDED.value)

        zone = read_zone(state["zone"]["id"])
        assert zone["hive_slots_used"] == 5, (
            "five hives are still seated and no more, got "
            f"{zone['hive_slots_used']}"
        )
        cycle = read_crop_cycle(state["cycle"]["id"])
        assert cycle["hive_count_placed"] == 5, (
            f"the refused placement adds no hives, got {cycle['hive_count_placed']}"
        )


class TestPackOutFloorNeedsAnAcknowledgement:
    """The identical pound figures pass or fail purely on the acknowledgement flag."""

    def test_a_seventy_five_percent_split_without_the_flag_is_refused(self, api):
        """PRD §3.9: "`MIN_PACK_OUT_PCT` is `80.00`, and a split whose computed `pack_out_pct` falls below that floor is rejected with `ERR_PACK_OUT_BELOW_MINIMUM` unless the request carries `low_pack_out_acknowledged` set to true."

        Design: Corner/validations/low_pack_out_needs_the_acknowledgement_flag_to_pass
        """
        state = setup_registered_lot(production_clock=PRODUCTION_CLOCK)
        supervisor = make_harvest_supervisor_headers(state["harvest_worker"]["id"])

        response = api.grade_harvest_lot(
            state["lot"]["id"],
            grade_harvest_lot_payload(
                grade_a_lbs=1000.00, grade_b_lbs=500.00, cull_lbs=500.00
            ),
            supervisor,
        )
        validate_error(response, ApiErrorId.ERR_PACK_OUT_BELOW_MINIMUM.value)

        lot = read_lot(state["lot"]["id"])
        assert lot["grading_status"] == "UNGRADED", (
            f"a refused grade leaves the lot ungraded, got {lot['grading_status']}"
        )
        assert lot["grade_a_lbs"] is None, (
            f"a refused grade records no grade A pounds, got {lot['grade_a_lbs']}"
        )

    def test_the_same_split_passes_once_the_grower_acknowledges_it(self, api):
        """PRD §3.9: "`MIN_PACK_OUT_PCT` is `80.00`, and a split whose computed `pack_out_pct` falls below that floor is rejected with `ERR_PACK_OUT_BELOW_MINIMUM` unless the request carries `low_pack_out_acknowledged` set to true."

        Design: Corner/validations/low_pack_out_needs_the_acknowledgement_flag_to_pass
        """
        state = setup_registered_lot(production_clock=PRODUCTION_CLOCK)
        supervisor = make_harvest_supervisor_headers(state["harvest_worker"]["id"])
        payload = grade_harvest_lot_payload(
            grade_a_lbs=1000.00, grade_b_lbs=500.00, cull_lbs=500.00
        )
        validate_error(
            api.grade_harvest_lot(state["lot"]["id"], payload, supervisor),
            ApiErrorId.ERR_PACK_OUT_BELOW_MINIMUM.value,
        )

        acknowledged = dict(payload)
        acknowledged["low_pack_out_acknowledged"] = True
        graded = validate_success(
            api.grade_harvest_lot(state["lot"]["id"], acknowledged, supervisor), 200
        )
        assert graded["grading_status"] == "GRADED", (
            f"the acknowledged split is accepted, got {graded['grading_status']}"
        )
        assert graded["pack_out_pct"] == pytest.approx(75.00, abs=0.01), (
            "1000 plus 500 marketable pounds of a 2000 lb lot packs out at 75.00, got "
            f"{graded['pack_out_pct']}"
        )
        assert graded["available_a_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"the whole grade A split is available, got {graded['available_a_lbs']}"
        )
        assert graded["available_b_lbs"] == pytest.approx(500.00, abs=0.01), (
            f"the whole grade B split is available, got {graded['available_b_lbs']}"
        )
        assert graded["regrade_count"] == 0, (
            f"a first grading is not a regrade, got {graded['regrade_count']}"
        )


class TestLaborBudgetIsTheFinalGate:
    """A compartment cannot schedule work it cannot pay for."""

    def test_a_task_costing_more_than_the_budget_remaining_is_refused(self, api):
        """PRD §3.8: "And last of all, the compartment's `labor_budget_remaining_usd` must be at least the task's computed `planned_cost_usd`, rejected with `ERR_LABOR_BUDGET_EXCEEDED`."

        Design: Corner/validations/labor_task_planned_cost_over_the_remaining_budget_is_rejected
        """
        state = _zone_with_a_hundred_dollar_budget()
        assert state["zone"]["labor_budget_remaining_usd"] == pytest.approx(
            100.00, abs=0.01
        ), (
            "a fresh compartment carries its whole budget as remaining, got "
            f"{state['zone']['labor_budget_remaining_usd']}"
        )

        response = api.create_labor_task(
            create_labor_task_payload(
                state["zone"]["id"],
                state["cycle"]["id"],
                state["harvest_worker"]["id"],
            ),
            GM,
        )
        validate_error(response, ApiErrorId.ERR_LABOR_BUDGET_EXCEEDED.value)

        tasks, meta = validate_paginated(
            api.list_labor_tasks(GM, params={"zone_id": state["zone"]["id"]})
        )
        assert tasks == [], f"a refused creation writes no task, got {tasks}"
        assert meta["total_count"] == 0, (
            f"no task row may exist on the compartment, got {meta['total_count']}"
        )
        zone = read_zone(state["zone"]["id"])
        assert zone["labor_budget_committed_usd"] == pytest.approx(0.00, abs=0.01), (
            "a refused creation commits nothing, got "
            f"{zone['labor_budget_committed_usd']}"
        )
        assert zone["labor_budget_remaining_usd"] == pytest.approx(100.00, abs=0.01), (
            "the budget is untouched, got "
            f"{zone['labor_budget_remaining_usd']}"
        )
        assert read_worker(state["harvest_worker"]["id"])[
            "committed_hours"
        ] == pytest.approx(0.00, abs=0.01), "a refused creation commits no worker hours"
