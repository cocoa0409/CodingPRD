"""Writes whose admissibility is decided by the state of a neighbouring record: the
machine a load is about to start in, the flock that owns the eggs, and the
environment dimension a transfer must clear.
"""

from test_helpers import (
    ApiClient,
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    ApiErrorId,
    CondemnedReason,
    EggLotStatus,
    EnvironmentStatus,
    FlockStatus,
    ItemStatus,
    LabResult,
    OccupancyStatus,
    SanitationStatus,
    SetterLoadStatus,
    UnitType,
    assert_breeder_flock,
    assert_egg_lot,
    assert_four_dp,
    assert_incubation_unit,
    assert_instant,
    assert_setter_load,
    assert_setter_load_item,
    assert_three_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

GRADE_6200 = {
    "grade_a_count": 6200,
    "cracked_count": 150,
    "dirty_count": 100,
    "small_count": 50,
}


class TestSetterStartRequiresItsMachine:
    """Sanitation is consumed by the start it enables."""

    def _dirty_machine_load(self, api: ApiClient):
        return fx.planned_load_context(
            api,
            sanitize_setter=False,
            collected_count=6500,
            grade=GRADE_6200,
            eggs_taken=6000,
        )

    def test_start_rejected_while_the_machine_is_still_dirty(self, api):
        """PRD 3.5: "Five preconditions apply: the load must be `PLANNED`; at least one
        `ACTIVE` draw must exist, otherwise `ERR_NO_EGGS_LOADED`, which is exactly the
        situation a condemnation cascade leaves behind; the machine's `sanitation_status`
        must be `SANITIZED`, otherwise `ERR_UNIT_NOT_SANITIZED`; the machine's
        `occupancy_status` must be `FREE`, otherwise `ERR_UNIT_OCCUPIED`; and
        `total_eggs_set` must not exceed the machine's `capacity_eggs`, otherwise
        `ERR_UNIT_CAPACITY_EXCEEDED`."

        Design: Difficulty/cross_entity_state_dependency/setter_start_requires_sanitized_free_unit
        """
        ctx = self._dirty_machine_load(api)
        fx.set_clock(api, "2026-08-01T18:00:00Z")

        response = api.start_setter_load(ctx["load"]["id"], INCUBATION_OPERATOR)

        validate_error(response, ApiErrorId.ERR_UNIT_NOT_SANITIZED, 422)
        load = fx.read_load(api, ctx["load"]["id"])
        assert_setter_load(load, status=SetterLoadStatus.PLANNED.value)
        assert load["set_at"] is None, "a rejected start must not stamp set_at"
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]), status=EggLotStatus.ALLOCATED.value
        )

    def test_start_after_a_fresh_sanitation_consumes_it_and_occupies_the_machine(
        self, api
    ):
        """PRD 3.5: "On success `set_at` is stamped from the logical clock, the machine's
        `occupancy_status` becomes `OCCUPIED` and its `sanitation_status` drops to
        `DIRTY`, every contributing egg lot moves `ALLOCATED → SET`, the load's `version`
        increments by 1, and the hatch window is derived."

        Design: Difficulty/cross_entity_state_dependency/setter_start_requires_sanitized_free_unit
        """
        ctx = self._dirty_machine_load(api)
        fx.set_clock(api, "2026-08-01T18:00:00Z")
        validate_error(
            api.start_setter_load(ctx["load"]["id"], INCUBATION_OPERATOR),
            ApiErrorId.ERR_UNIT_NOT_SANITIZED,
            422,
        )
        sanitized = get_success_data(
            api.sanitize_incubation_unit(ctx["setter_unit"]["id"], INCUBATION_OPERATOR),
            200,
        )
        assert_incubation_unit(
            sanitized,
            sanitation_status=SanitationStatus.SANITIZED.value,
            occupancy_status=OccupancyStatus.FREE.value,
        )

        started = validate_success(
            api.start_setter_load(ctx["load"]["id"], INCUBATION_OPERATOR), 200
        )

        assert_setter_load(
            started,
            status=SetterLoadStatus.INCUBATING.value,
            set_at="2026-08-01T18:00:00Z",
            storage_delay_hours=0,
        )
        assert_four_dp(started["weighted_age_days"], 2.5000, "weighted_age_days")
        assert_incubation_unit(
            fx.read_unit(api, ctx["setter_unit"]["id"]),
            occupancy_status=OccupancyStatus.OCCUPIED.value,
            sanitation_status=SanitationStatus.DIRTY.value,
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]), status=EggLotStatus.SET.value
        )


class TestEggOperationsGatedOnEggHold:
    """A hold freezes the flock's eggs in three places and needs a second pair of eyes."""

    def _flock_on_egg_hold(self, api: ApiClient):
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        stored = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            collected_at="2026-07-30T00:00:00Z",
            collected_count=6500,
        )
        graded = fx.graded_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            collected_at="2026-07-31T00:00:00Z",
            collected_count=6500,
        )
        positive = fx.register_lab_test(
            api, flock["id"], collected_at="2026-08-01T06:00:00Z"
        )
        fx.release_lab_test(
            api, positive["id"], LabResult.POSITIVE.value, VETERINARIAN
        )
        return {"flock": flock, "stored": stored, "graded": graded}

    def test_egg_hold_condemns_stored_lots_and_leaves_graded_lots_alone(self, api):
        """PRD 3.3: "When the subject is a `BREEDER_FLOCK`, the flock moves `IN_LAY →
        EGG_HOLD`, its `egg_hold_opened_at` is set to the current logical clock and its
        `egg_hold_opened_by_user_id` records the `X-User-ID` of the principal that made
        the release call — and then the egg condemnation cascade runs: **every** egg lot
        of that flock currently in `IN_STORAGE` or `ALLOCATED` moves to `CONDEMNED` with a
        `condemned_reason` of `FLOCK_EGG_HOLD`."

        Design: Difficulty/cross_entity_state_dependency/egg_operations_gated_on_flock_egg_hold
        """
        ctx = self._flock_on_egg_hold(api)

        flock = fx.read_flock(api, ctx["flock"]["id"])
        assert_breeder_flock(
            flock,
            status=FlockStatus.EGG_HOLD.value,
            egg_hold_opened_by_user_id="u_vet_1",
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["stored"]["id"]),
            status=EggLotStatus.CONDEMNED.value,
            condemned_reason=CondemnedReason.FLOCK_EGG_HOLD.value,
            eggs_remaining=0,
            settable_count=6200,
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["graded"]["id"]), status=EggLotStatus.GRADED.value
        )

    def test_hold_blocks_storing_and_collecting_and_bars_its_own_opener(self, api):
        """PRD 3.3: "While a flock sits in `EGG_HOLD` its eggs are frozen out of the
        production chain in three places: new collections against it, storing one of its
        graded lots, and drawing from one of its lots into a setter load are all rejected
        with `ERR_FLOCK_EGG_HOLD` — and the ban reaches lots that were already sitting in
        the cooler before the hold was raised, not just newly collected ones." And: "only
        when the acting `X-User-ID` differs from the recorded `egg_hold_opened_by_user_id`
        — a same-principal attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` before the
        flock's state is even examined".

        Design: Difficulty/cross_entity_state_dependency/egg_operations_gated_on_flock_egg_hold
        """
        ctx = self._flock_on_egg_hold(api)

        store_attempt = api.store_egg_lot(
            ctx["graded"]["id"], f.store_payload(15.0), INCUBATION_OPERATOR
        )
        validate_error(store_attempt, ApiErrorId.ERR_FLOCK_EGG_HOLD, 422)
        still_graded = fx.read_lot(api, ctx["graded"]["id"])
        assert_egg_lot(still_graded, status=EggLotStatus.GRADED.value)
        assert still_graded["stored_at"] is None

        collect_attempt = api.create_egg_lot(
            f.egg_lot_payload(
                ctx["flock"]["id"],
                collected_at="2026-08-01T08:00:00Z",
                collected_count=4000,
            ),
            FLOCK_MANAGER,
        )
        validate_error(collect_attempt, ApiErrorId.ERR_FLOCK_EGG_HOLD, 422)
        _rows, meta = validate_paginated(
            api.list_egg_lots(FLOCK_MANAGER, {"flock_id": ctx["flock"]["id"]})
        )
        assert meta["total_count"] == 2, (
            f"the rejected collection must create nothing, got {meta['total_count']}"
        )

        same_principal_release = api.release_egg_hold(ctx["flock"]["id"], VETERINARIAN)
        validate_error(
            same_principal_release, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403
        )
        assert_breeder_flock(
            fx.read_flock(api, ctx["flock"]["id"]), status=FlockStatus.EGG_HOLD.value
        )


class TestTransferGatedOnEnvironment:
    """An unresolved excursion stops the handover to the hatcher."""

    def _candled_load_with_open_deviation(self, api: ApiClient):
        ctx = fx.deviation_open_context(api)
        ctx["load"] = get_success_data(
            api.candle_setter_load(ctx["load"]["id"], 9600, INCUBATION_OPERATOR), 200
        )
        ctx["hatcher_unit"] = fx.sanitized_unit(
            api, code="U2", unit_type=UnitType.HATCHER.value, capacity_eggs=20000
        )
        return ctx

    def test_transfer_rejected_while_the_deviation_is_still_open(self, api):
        """PRD 3.6: "Three gates apply: the load's `environment_status` must not be
        `DEVIATION_OPEN`, otherwise `ERR_ENVIRONMENT_DEVIATION_OPEN` — eggs whose
        temperature excursion has not yet cleared may not proceed; and the destination
        machine named by `hatcher_unit_id` must be of `unit_type` `HATCHER` (otherwise
        `ERR_UNIT_TYPE_MISMATCH`), must have `sanitation_status` of `SANITIZED` (otherwise
        `ERR_UNIT_NOT_SANITIZED`) and must have `occupancy_status` of `FREE` (otherwise
        `ERR_UNIT_OCCUPIED`)."

        Design: Difficulty/cross_entity_state_dependency/transfer_blocked_by_open_environment_deviation
        """
        ctx = self._candled_load_with_open_deviation(api)
        before = fx.read_load(api, ctx["load"]["id"])
        assert_setter_load(
            before,
            status=SetterLoadStatus.CANDLED.value,
            environment_status=EnvironmentStatus.DEVIATION_OPEN.value,
        )
        assert_three_dp(before["deviation_degree_hours"], 2.000, "deviation_degree_hours")
        assert_instant(
            before["deviation_opened_at"], "2026-08-01T22:00:00Z", "deviation_opened_at"
        )

        response = api.transfer_setter_load(
            ctx["load"]["id"], ctx["hatcher_unit"]["id"], INCUBATION_OPERATOR
        )

        validate_error(response, ApiErrorId.ERR_ENVIRONMENT_DEVIATION_OPEN, 422)
        assert_incubation_unit(
            fx.read_unit(api, ctx["hatcher_unit"]["id"]),
            occupancy_status=OccupancyStatus.FREE.value,
        )
        assert_incubation_unit(
            fx.read_unit(api, ctx["setter_unit"]["id"]),
            occupancy_status=OccupancyStatus.OCCUPIED.value,
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]), status=EggLotStatus.SET.value
        )

    def test_deviation_cannot_be_cleared_after_candling_so_the_load_is_aborted(
        self, api
    ):
        """PRD 3.5: "An `IncubationOperator` ingests a probe reading against a load that is
        `INCUBATING`". And PRD 3.5: "From `INCUBATING` or from `CANDLED` the outcome is
        harsher and identical between the two: every `ACTIVE` draw flips to `VOIDED`,
        every contributing lot then sitting in `SET` moves to `CONDEMNED` with a
        `condemned_reason` of `LOAD_ABORTED` because part-incubated eggs cannot go back in
        the cooler, and the machine's `occupancy_status` is released to `FREE`."

        Design: Difficulty/cross_entity_state_dependency/transfer_blocked_by_open_environment_deviation
        """
        ctx = self._candled_load_with_open_deviation(api)
        validate_error(
            api.transfer_setter_load(
                ctx["load"]["id"], ctx["hatcher_unit"]["id"], INCUBATION_OPERATOR
            ),
            ApiErrorId.ERR_ENVIRONMENT_DEVIATION_OPEN,
            422,
        )

        late_reading = api.add_environment_reading(
            ctx["load"]["id"],
            f.environment_reading_payload("2026-08-02T00:00:00Z", 37.8),
            INCUBATION_OPERATOR,
        )
        validate_error(late_reading, ApiErrorId.ERR_INCUBATION_INVALID_STATE, 409)

        aborted = validate_success(
            api.abort_setter_load(
                ctx["load"]["id"], "ENVIRONMENT_DEVIATION", HATCHERY_MANAGER
            ),
            200,
        )

        assert_setter_load(
            aborted,
            status=SetterLoadStatus.ABORTED.value,
            abort_reason="ENVIRONMENT_DEVIATION",
            environment_status=EnvironmentStatus.DEVIATION_OPEN.value,
        )
        assert_three_dp(
            aborted["deviation_degree_hours"], 2.000, "deviation_degree_hours"
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]),
            status=EggLotStatus.CONDEMNED.value,
            condemned_reason=CondemnedReason.LOAD_ABORTED.value,
        )
        assert_incubation_unit(
            fx.read_unit(api, ctx["setter_unit"]["id"]),
            occupancy_status=OccupancyStatus.FREE.value,
        )
        assert_setter_load_item(
            fx.list_items_of_load(api, ctx["load"]["id"])[0],
            item_status=ItemStatus.VOIDED.value,
        )
