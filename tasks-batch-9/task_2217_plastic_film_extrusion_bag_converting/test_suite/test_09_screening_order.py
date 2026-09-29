"""Requests violating two rules at once must surface the earlier check."""
import pytest

from test_helpers import (
    ADMIN,
    CONVERTER,
    ENGINEER,
    EXTRUDER,
    ApiErrorId,
    add_gauge_readings,
    create_extrusion_run_payload,
    create_regrind_pool_payload,
    get_success_data,
    read_pool_version,
    set_logical_clock,
    setup_approved_food_recipe,
    setup_approved_non_food_recipe,
    setup_bag_lot_qualified,
    setup_food_contact_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)


def _schedule(api, world, recipe, run_code, start, end, target_output_kg=500.0):
    return get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], recipe["id"],
                                     run_code=run_code,
                                     scheduled_start=start,
                                     scheduled_end=end,
                                     target_output_kg=target_output_kg),
        EXTRUDER))


class TestPathEntityStateOutranksQuantityChecks:
    """A held run refuses completion before any quantity rule is consulted."""

    @staticmethod
    def _held_run_with_two_readings(api):
        world = setup_approved_non_food_recipe(api)
        run = _schedule(api, world, world["recipe"], "RUN-NF-1",
                        "2026-08-05T06:00:00Z", "2026-08-05T14:00:00Z")
        get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
        add_gauge_readings(api, run["id"], (40.0, 40.0))
        world["run"] = get_success_data(
            api.hold_extrusion_run(run["id"], "screen pack change", EXTRUDER))
        return world

    def test_state_error_wins_over_both_quantity_violations(self, api):
        """Scrap above output and only two samples are never reported.

        PRD: "This ordering is observable and is part of the contract: a request
        that violates two rules must surface the earlier one."

        Design: Difficulty/priority_pair_validation_conflict/entity_state_priority_9_outranks_business_fiscal_priority_15_on_run_complete
        """
        world = self._held_run_with_two_readings(api)
        error = validate_error(
            api.complete_extrusion_run(world["run"]["id"], 100.0, 500.0, EXTRUDER),
            ApiErrorId.ERR_RUN_STATE_INVALID, 409)

        assert error["error_id"] != ApiErrorId.ERR_SCRAP_EXCEEDS_OUTPUT
        assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_GAUGE_DATA

    def test_the_run_is_left_exactly_as_it_was(self, api):
        """The refused completion writes nothing to the run.

        PRD: "The state of the entity named in the path permits the requested
        transition (a 409 state error naming that entity)."

        Design: Difficulty/priority_pair_validation_conflict/entity_state_priority_9_outranks_business_fiscal_priority_15_on_run_complete
        """
        world = self._held_run_with_two_readings(api)
        validate_error(
            api.complete_extrusion_run(world["run"]["id"], 100.0, 500.0, EXTRUDER),
            ApiErrorId.ERR_RUN_STATE_INVALID, 409)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["status"] == "HELD"
        assert run["gross_output_kg"] is None
        assert run["net_good_kg"] is None
        assert run["gauge_sample_count"] == 2
        assert run["gauge_capability_state"] == "INSUFFICIENT_DATA"

    def test_no_closure_side_effect_reaches_the_pool(self, api):
        """Because closure never ran, no scrap was booked.

        PRD: "It requires at least five gauge samples, or
        `ERR_INSUFFICIENT_GAUGE_DATA`; it requires `scrap_kg` to be no greater
        than `gross_output_kg`, or `ERR_SCRAP_EXCEEDS_OUTPUT`".

        Design: Difficulty/priority_pair_validation_conflict/entity_state_priority_9_outranks_business_fiscal_priority_15_on_run_complete
        """
        world = self._held_run_with_two_readings(api)
        validate_error(
            api.complete_extrusion_run(world["run"]["id"], 100.0, 500.0, EXTRUDER),
            ApiErrorId.ERR_RUN_STATE_INVALID, 409)

        pool = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["generation_count"] == 0
        assert pool["available_kg"] == pytest.approx(0.000, abs=0.01)


class TestFoodContactComplianceOutranksQuantityChecks:
    """An ineligible pool is reported even when the quantity is also impossible."""

    @staticmethod
    def _food_run_and_a_non_food_pool(api):
        world = setup_food_contact_catalog(api)
        world["pool_nf"] = get_success_data(
            api.create_regrind_pool(create_regrind_pool_payload(), ADMIN))
        world = setup_approved_food_recipe(api=api, world=world)
        run = _schedule(api, world, world["recipe"], "RUN-FD-1",
                        "2026-08-05T06:00:00Z", "2026-08-05T18:00:00Z",
                        target_output_kg=1000.0)
        world["run"] = get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
        return world

    def test_pool_eligibility_error_wins_over_availability_and_budget(self, api):
        """999.0 kg from an empty non-food pool answers with the safety error.

        PRD: "Food-contact, recycled-content and segregation-of-duties compliance
        (422, except the segregation violation which is 403)." This outranks
        "Quantity, data-sufficiency and budget sufficiency".

        Design: Difficulty/priority_pair_validation_conflict/business_safety_priority_11_outranks_business_fiscal_priority_15_on_reincorporation
        """
        world = self._food_run_and_a_non_food_pool(api)
        version = read_pool_version(api, world["pool_nf"]["id"])
        error = validate_error(api.create_regrind_reincorporation(
            world["run"]["id"],
            {"pool_id": world["pool_nf"]["id"], "kg": 999.0,
             "expected_regrind_pool_version": version},
            EXTRUDER), ApiErrorId.ERR_FOOD_CONTACT_POOL_INELIGIBLE, 422)

        assert error["error_id"] != ApiErrorId.ERR_REGRIND_INSUFFICIENT
        assert error["error_id"] != ApiErrorId.ERR_REGRIND_BUDGET_EXCEEDED
        assert error["error_id"] != ApiErrorId.ERR_STALE_POOL_VERSION

    def test_the_ineligible_pool_records_nothing(self, api):
        """No row is booked and no balance moves.

        PRD: "A food-contact product may not draw from a `NON_FOOD_ONLY` pool,
        and no product may draw from a pool whose `polymer_family` differs from
        the recipe's `dominant_polymer_family`; either is
        `ERR_FOOD_CONTACT_POOL_INELIGIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_priority_11_outranks_business_fiscal_priority_15_on_reincorporation
        """
        world = self._food_run_and_a_non_food_pool(api)
        version = read_pool_version(api, world["pool_nf"]["id"])
        validate_error(api.create_regrind_reincorporation(
            world["run"]["id"],
            {"pool_id": world["pool_nf"]["id"], "kg": 999.0,
             "expected_regrind_pool_version": version},
            EXTRUDER), ApiErrorId.ERR_FOOD_CONTACT_POOL_INELIGIBLE, 422)

        pool_nf = get_success_data(
            api.get_regrind_pool(world["pool_nf"]["id"], EXTRUDER))
        assert pool_nf["available_kg"] == pytest.approx(0.000, abs=0.01)
        assert pool_nf["cumulative_out_kg"] == pytest.approx(0.000, abs=0.01)
        assert pool_nf["reincorporation_count"] == 0

        _rows, meta = validate_paginated(api.list_regrind_transactions(
            EXTRUDER, params={"pool_id": world["pool_nf"]["id"]}))
        assert meta["total_count"] == 0

    def test_the_run_and_its_budget_are_untouched(self, api):
        """The run keeps running with its regrind budget intact.

        PRD: the budget rule that was never reached says
        "a draw that would push the run's cumulative regrind consumption above the run's"
        `target_output_kg` multiplied by `regrind_cap_pct` is refused.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_priority_11_outranks_business_fiscal_priority_15_on_reincorporation
        """
        world = self._food_run_and_a_non_food_pool(api)
        version = read_pool_version(api, world["pool_nf"]["id"])
        validate_error(api.create_regrind_reincorporation(
            world["run"]["id"],
            {"pool_id": world["pool_nf"]["id"], "kg": 999.0,
             "expected_regrind_pool_version": version},
            EXTRUDER), ApiErrorId.ERR_FOOD_CONTACT_POOL_INELIGIBLE, 422)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["status"] == "RUNNING"
        recipe = get_success_data(api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["regrind_cap_pct"] == pytest.approx(10.000, abs=0.01)


class TestOccupancyConflictOutranksThePastWindowGate:
    """A reschedule into an occupied past window reports the occupancy clash."""

    @staticmethod
    def _two_scheduled_runs_and_an_advanced_clock(api):
        world = setup_approved_non_food_recipe(api)
        world["run1"] = _schedule(api, world, world["recipe"], "RUN-NF-1",
                                  "2026-08-05T06:00:00Z", "2026-08-05T14:00:00Z")
        world["run2"] = _schedule(api, world, world["recipe"], "RUN-NF-2",
                                  "2026-08-06T06:00:00Z", "2026-08-06T14:00:00Z")
        set_logical_clock(api, "2026-08-05T20:00:00Z")
        return world

    def test_occupancy_error_wins_over_the_past_window_error(self, api):
        """The target window is both occupied and behind the clock.

        PRD: "Resource capability, exclusive line occupancy and aggregate press
        cylinder capacity (409, except the two capability mismatches which are
        422)." This is screened before "Clock-relative window and hold-limit
        gates (409)."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_priority_13_outranks_business_temporal_priority_14_on_reschedule
        """
        world = self._two_scheduled_runs_and_an_advanced_clock(api)
        error = validate_error(api.reschedule_extrusion_run(
            world["run2"]["id"], "2026-08-05T06:00:00Z", "2026-08-05T12:00:00Z",
            EXTRUDER), ApiErrorId.ERR_LINE_WINDOW_CONFLICT, 409)

        assert error["error_id"] != ApiErrorId.ERR_WINDOW_IN_PAST

    def test_the_rejected_reschedule_leaves_the_window_alone(self, api):
        """Both runs keep the windows they were scheduled with.

        PRD: "Rescheduling a run moves its `scheduled_start` and `scheduled_end`
        and re-runs exactly the same occupancy and past-window evaluation; it is
        permitted only while the run is still `SCHEDULED`, and an attempt on any
        other status yields `ERR_RUN_STATE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_priority_13_outranks_business_temporal_priority_14_on_reschedule
        """
        world = self._two_scheduled_runs_and_an_advanced_clock(api)
        validate_error(api.reschedule_extrusion_run(
            world["run2"]["id"], "2026-08-05T06:00:00Z", "2026-08-05T12:00:00Z",
            EXTRUDER), ApiErrorId.ERR_LINE_WINDOW_CONFLICT, 409)

        run2 = get_success_data(api.get_extrusion_run(world["run2"]["id"], EXTRUDER))
        assert run2["scheduled_start"].startswith("2026-08-06T06:00:00")
        assert run2["scheduled_end"].startswith("2026-08-06T14:00:00")
        assert run2["status"] == "SCHEDULED"

        run1 = get_success_data(api.get_extrusion_run(world["run1"]["id"], EXTRUDER))
        assert run1["status"] == "SCHEDULED"

    def test_the_line_gap_that_produced_the_clash_is_observable(self, api):
        """The same recipe on both runs means the gap itself is zero.

        PRD: "Line occupancy is exclusive, and the required gap between two runs
        depends on what they have in common."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_priority_13_outranks_business_temporal_priority_14_on_reschedule
        """
        world = self._two_scheduled_runs_and_an_advanced_clock(api)
        validate_error(api.reschedule_extrusion_run(
            world["run2"]["id"], "2026-08-05T06:00:00Z", "2026-08-05T12:00:00Z",
            EXTRUDER), ApiErrorId.ERR_LINE_WINDOW_CONFLICT, 409)

        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["purge_buffer_minutes"] == 45


class TestStaleVersionOutranksTheUnpackedQuantityCheck:
    """A stale lot version answers 412 before the bag count is even looked at."""

    @staticmethod
    def _lot_packed_once_with_a_captured_version(api):
        world = setup_bag_lot_qualified(api)
        world["stale_version"] = world["bag_lot"]["version"]
        validate_success(api.packout_bag_lot(
            world["bag_lot"]["id"], 22500, world["stale_version"], CONVERTER), 200)
        return world

    def test_stale_version_error_wins_over_the_unpacked_ceiling(self, api):
        """99999 bags against 23500 unpacked never reaches the quantity gate.

        PRD: "A mismatch with the lot's current `version` is rejected with
        `ERR_STALE_BAG_LOT_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/optimistic_concurrency_priority_8_outranks_business_fiscal_priority_15_on_packout
        """
        world = self._lot_packed_once_with_a_captured_version(api)
        error = validate_error(api.packout_bag_lot(
            world["bag_lot"]["id"], 99999, world["stale_version"], CONVERTER),
            ApiErrorId.ERR_STALE_BAG_LOT_VERSION, 412)

        assert error["error_id"] != ApiErrorId.ERR_PACKOUT_EXCEEDS_UNPACKED

    def test_the_first_allocation_survives_the_rejected_second(self, api):
        """The lot keeps exactly the counters the accepted packout wrote.

        PRD: "Packout is likewise incremental and repeatable — each call re-reads
        `bag_count_unpacked` — so without this gate a stale caller could commit an
        allocation computed against an unpacked count that no longer exists."

        Design: Difficulty/priority_pair_validation_conflict/optimistic_concurrency_priority_8_outranks_business_fiscal_priority_15_on_packout
        """
        world = self._lot_packed_once_with_a_captured_version(api)
        validate_error(api.packout_bag_lot(
            world["bag_lot"]["id"], 99999, world["stale_version"], CONVERTER),
            ApiErrorId.ERR_STALE_BAG_LOT_VERSION, 412)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["packed_bag_count"] == 22500
        assert lot["packed_case_count"] == 45
        assert lot["pallet_count"] == 2
        assert lot["bag_count_unpacked"] == 23500
        assert lot["status"] == "PACKED"

    def test_the_accepted_packout_is_what_advanced_the_version(self, api):
        """The captured version is stale precisely because the first call moved it.

        PRD: "Each accepted packout increments the lot's `version` by one."

        Design: Difficulty/priority_pair_validation_conflict/optimistic_concurrency_priority_8_outranks_business_fiscal_priority_15_on_packout
        """
        world = self._lot_packed_once_with_a_captured_version(api)
        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))

        assert lot["version"] == world["stale_version"] + 1
