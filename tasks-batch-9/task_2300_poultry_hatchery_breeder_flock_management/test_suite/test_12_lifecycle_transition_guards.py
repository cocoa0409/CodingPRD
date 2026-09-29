"""Where each lifecycle begins, which steps it refuses to repeat or skip, and the
one cycle that deliberately loops back on itself.

Every rejection is paired with a read-back proving the refused call left no trace,
and the transitions that do fire are checked for their full side-effect fan-out.
"""

from test_helpers import (
    ApiClient,
    CHICK_PROCESSOR,
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    VETERINARIAN_2,
    ApiErrorId,
    ChickBatchStatus,
    CorrectiveActionStatus,
    EggLotStatus,
    EnvironmentStatus,
    FlockStatus,
    HatcherLoadStatus,
    LabResult,
    LabTestStatus,
    OccupancyStatus,
    OrderStatus,
    QualityFlag,
    Role,
    SanitationStatus,
    SetterLoadStatus,
    UnitType,
    VerificationOutcome,
    assert_breeder_flock,
    assert_chick_batch,
    assert_corrective_action,
    assert_egg_lot,
    assert_forecast_chain,
    assert_hatch_window,
    assert_hatcher_load,
    assert_incubation_unit,
    assert_lab_test,
    assert_placement_order,
    assert_setter_load,
    assert_three_dp,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_headers,
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


class TestWhereALifecycleBegins:
    """A planned load occupies nothing and has moved on neither of its dimensions."""

    def test_a_new_setter_load_is_planned_and_nominal_at_once(self, api):
        """PRD 3.5: "A new load has `status` of `PLANNED`, `environment_status` of
        `NOMINAL`, `total_eggs_set` of 0, `deviation_degree_hours` of 0, and nulls for
        `set_at`, `weighted_age_days`, `storage_delay_hours`, `planned_transfer_at`,
        `planned_pull_at`, `pull_window_start_at`, `pull_window_end_at`, `fertile_count`,
        `fertility_pct`, `deviation_opened_at` and `abort_reason`."

        Design: Corner/state_machines/setter_load_starts_in_planned_and_nominal
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        unit = fx.create_unit(api, code="U1", unit_type=UnitType.SETTER.value)
        profile = fx.create_profile(api)

        load = validate_success(
            api.create_setter_load(
                f.setter_load_payload(
                    unit["id"], profile["id"], fx.STANDARD_PLANNED_SET_AT
                ),
                INCUBATION_OPERATOR,
            ),
            201,
        )

        assert_setter_load(
            load,
            unit_id=unit["id"],
            profile_id=profile["id"],
            status=SetterLoadStatus.PLANNED.value,
            environment_status=EnvironmentStatus.NOMINAL.value,
            total_eggs_set=0,
            version=1,
        )
        assert load["weighted_age_days"] is None
        assert load["storage_delay_hours"] is None
        assert load["set_at"] is None
        assert load["deviation_opened_at"] is None
        assert load["fertile_count"] is None
        assert load["abort_reason"] is None
        assert_three_dp(
            load["deviation_degree_hours"], 0.000, "deviation_degree_hours"
        )
        assert_incubation_unit(
            fx.read_unit(api, unit["id"]),
            occupancy_status=OccupancyStatus.FREE.value,
        )


class TestTransitionsThatFanOut:
    """One accepted call whose consequences reach five records."""

    def test_transfer_freezes_the_window_and_moves_machines_and_lots(self, api):
        """PRD 3.6: "The new record freezes a snapshot of the incubation history at that
        instant: `transferred_at` from the logical clock, `eggs_transferred` copying the
        setter load's `total_eggs_set`, `planned_pull_at`, `pull_window_start_at` and
        `pull_window_end_at` copying the setter load's corresponding instants, and
        `inherited_degree_hours` copying the setter load's `deviation_degree_hours` to three
        decimal places." And: "Meanwhile the setter machine's `occupancy_status` is released
        to `FREE`, the hatcher machine becomes `OCCUPIED` and `DIRTY`, and every contributing
        egg lot moves `SET → CONSUMED` with its `eggs_remaining` set to 0."

        Design: Corner/state_machines/transfer_side_effects_copy_window_and_move_units_and_lots
        """
        ctx = fx.candled_load_context(api, fertile_count=9600)
        hatcher_unit = fx.sanitized_unit(
            api, code="U2", unit_type=UnitType.HATCHER.value, capacity_eggs=20000
        )
        fx.set_clock(api, fx.STANDARD_TRANSFER_AT)

        hatcher_load = validate_success(
            api.transfer_setter_load(
                ctx["load"]["id"], hatcher_unit["id"], INCUBATION_OPERATOR
            ),
            201,
        )

        assert_hatcher_load(
            hatcher_load,
            setter_load_id=ctx["load"]["id"],
            unit_id=hatcher_unit["id"],
            status=HatcherLoadStatus.HATCHING.value,
            transferred_at=fx.STANDARD_TRANSFER_AT,
            eggs_transferred=10000,
            quality_flag=QualityFlag.NONE.value,
        )
        assert_hatch_window(
            hatcher_load,
            planned_pull_at="2026-08-22T18:00:00Z",
            pull_window_start_at="2026-08-22T12:00:00Z",
            pull_window_end_at="2026-08-23T00:00:00Z",
        )
        assert_three_dp(
            hatcher_load["inherited_degree_hours"], 0.000, "inherited_degree_hours"
        )
        assert hatcher_load["actual_pull_at"] is None
        assert hatcher_load["hold_release_at"] is None

        setter_load = fx.read_load(api, ctx["load"]["id"])
        assert_setter_load(setter_load, status=SetterLoadStatus.TRANSFERRED.value)
        assert_two_dp(setter_load["fertility_pct"], 96.00, "fertility_pct")
        assert_incubation_unit(
            fx.read_unit(api, ctx["setter_unit"]["id"]),
            occupancy_status=OccupancyStatus.FREE.value,
            sanitation_status=SanitationStatus.DIRTY.value,
        )
        assert_incubation_unit(
            fx.read_unit(api, hatcher_unit["id"]),
            occupancy_status=OccupancyStatus.OCCUPIED.value,
            sanitation_status=SanitationStatus.DIRTY.value,
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]),
            status=EggLotStatus.CONSUMED.value,
            settable_count=10000,
            eggs_remaining=0,
        )


class TestRepeatAndTerminalLockdown:
    """A step already taken, and a record that has reached the end of its road."""

    def test_photostimulation_is_neither_repeatable_nor_available_after_depletion(
        self, api
    ):
        """PRD 2.11: "The breeder flock admits the requested transition —
        `ERR_FLOCK_INVALID_STATE` (409), on start-lay, deplete and release-hold. This covers
        repeat triggers such as photostimulating twice, and terminal lockdown: nothing leaves
        `DEPLETED`."

        Design: Corner/state_machines/flock_cannot_start_lay_twice_or_after_deplete
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])

        repeat = api.start_lay(flock["id"], FLOCK_MANAGER)

        validate_error(repeat, ApiErrorId.ERR_FLOCK_INVALID_STATE, 409)
        assert_breeder_flock(
            fx.read_flock(api, flock["id"]),
            status=FlockStatus.IN_LAY.value,
            settable_forecast=5754,
        )

        depleted = validate_success(api.deplete_flock(flock["id"], FLOCK_MANAGER), 200)
        assert_breeder_flock(
            depleted,
            status=FlockStatus.DEPLETED.value,
            settable_forecast=0,
            production_rate_pct=0.0,
        )

        validate_error(
            api.start_lay(flock["id"], FLOCK_MANAGER),
            ApiErrorId.ERR_FLOCK_INVALID_STATE,
            409,
        )
        validate_error(
            api.deplete_flock(flock["id"], FLOCK_MANAGER),
            ApiErrorId.ERR_FLOCK_INVALID_STATE,
            409,
        )
        assert_breeder_flock(
            fx.read_flock(api, flock["id"]),
            status=FlockStatus.DEPLETED.value,
            settable_forecast=0,
        )

    def test_a_released_sample_refuses_both_the_same_and_a_different_result(self, api):
        """PRD 3.3: "A second release attempt against a test in any of the three terminal
        states is rejected with `ERR_LAB_TEST_ALREADY_RELEASED`, including a release carrying
        the same result as before." And PRD 2.11: "A released test is terminal and cannot be
        re-released, not even with the same result."

        Design: Corner/state_machines/released_lab_test_cannot_be_released_again
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.create_flock(api, program["id"])
        pending = fx.register_lab_test(api, flock["id"])
        released = fx.release_lab_test(api, pending["id"], LabResult.NEGATIVE.value)

        same_result = api.release_lab_test(
            released["id"], LabResult.NEGATIVE.value, VETERINARIAN
        )
        different_result = api.release_lab_test(
            released["id"], LabResult.POSITIVE.value, VETERINARIAN
        )

        validate_error(same_result, ApiErrorId.ERR_LAB_TEST_ALREADY_RELEASED, 409)
        validate_error(different_result, ApiErrorId.ERR_LAB_TEST_ALREADY_RELEASED, 409)
        after = get_success_data(api.get_lab_test(released["id"], VETERINARIAN), 200)
        assert_lab_test(
            after,
            status=LabTestStatus.NEGATIVE.value,
            result=LabResult.NEGATIVE.value,
            released_at=fx.CLOCK_SETUP,
            version=released["version"],
        )
        assert_breeder_flock(
            fx.read_flock(api, flock["id"]), status=FlockStatus.PLACED.value
        )
        assert fx.read_flock(api, flock["id"])["egg_hold_opened_at"] is None, (
            "the rejected re-release must not run the positive cascade"
        )

    def test_the_chick_flow_refuses_to_skip_vaccination_or_repeat_sexing(self, api):
        """PRD 3.7: "Chick processing is a strict three-step ladder run by a
        `ChickProcessor`: `PULLED → SEXED → VACCINATED → BOXED`. Skipping a rung —
        vaccinating an unsexed batch, boxing an unvaccinated one — is rejected with
        `ERR_CHICK_FLOW_INVALID_STATE`, and `BOXED` is terminal." And PRD 2.11: "The hatcher
        load admits the requested transition — also `ERR_INCUBATION_INVALID_STATE` (409), on
        chick pull. A hatcher load is pulled exactly once; a second pull from any of the
        three pulled states is rejected."

        Design: Corner/state_machines/chick_flow_cannot_skip_or_repeat_steps
        """
        ctx = fx.sexed_batch_context(api, sexing=fx.HEALTHY_SEXING)
        batch_id = ctx["batch"]["id"]

        skip_vaccination = api.box_chick_batch(batch_id, CHICK_PROCESSOR)
        repeat_sexing = api.sex_chick_batch(
            batch_id,
            f.sexing_payload(male_count=4700, female_count=4600),
            CHICK_PROCESSOR,
        )
        repeat_pull = api.pull_chicks(
            ctx["hatcher_load"]["id"], 9400, CHICK_PROCESSOR
        )

        validate_error(
            skip_vaccination, ApiErrorId.ERR_CHICK_FLOW_INVALID_STATE, 409
        )
        validate_error(repeat_sexing, ApiErrorId.ERR_CHICK_FLOW_INVALID_STATE, 409)
        validate_error(repeat_pull, ApiErrorId.ERR_INCUBATION_INVALID_STATE, 409)
        held = fx.read_batch(api, batch_id)
        assert_chick_batch(
            held, status=ChickBatchStatus.SEXED.value, male_count=4600
        )
        assert held["saleable_count"] is None, (
            "the refused boxing must not resolve the saleable pool"
        )
        _rows, meta = validate_paginated(
            api.list_chick_batches(
                CHICK_PROCESSOR, {"hatcher_load_id": ctx["hatcher_load"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused pull must not mint a second batch, got {meta['total_count']}"
        )

        vaccinated = validate_success(
            api.vaccinate_chick_batch(batch_id, "MAREKS_HVT", CHICK_PROCESSOR), 200
        )
        assert_chick_batch(
            vaccinated,
            status=ChickBatchStatus.VACCINATED.value,
            vaccine_cull_count=38,
            saleable_count=9262,
        )

        boxed = validate_success(api.box_chick_batch(batch_id, CHICK_PROCESSOR), 200)
        assert_chick_batch(
            boxed, status=ChickBatchStatus.BOXED.value, box_count=93
        )
        assert_hatcher_load(
            fx.read_hatcher_load(api, ctx["hatcher_load"]["id"]),
            status=HatcherLoadStatus.PROCESSED.value,
        )
        assert_incubation_unit(
            fx.read_unit(api, ctx["hatcher_unit"]["id"]),
            occupancy_status=OccupancyStatus.FREE.value,
        )

    def test_confirming_an_already_confirmed_order_is_refused(self, api):
        """PRD 2.11: "The placement order admits confirmation — `ERR_ORDER_INVALID_STATE`
        (409), on confirmation only; an order may be confirmed only from `REQUESTED`."

        Design: Corner/state_machines/order_cannot_be_confirmed_twice
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        farm = fx.cleared_farm(api)
        order = fx.requested_order(api, farm["id"])

        confirmed = validate_success(
            api.confirm_placement_order(order["id"], HATCHERY_MANAGER), 200
        )
        repeat = api.confirm_placement_order(order["id"], HATCHERY_MANAGER)

        assert_placement_order(
            confirmed,
            status=OrderStatus.CONFIRMED.value,
            allocated_chicks=0,
            remaining_need=5000,
        )
        validate_error(repeat, ApiErrorId.ERR_ORDER_INVALID_STATE, 409)
        assert_placement_order(
            fx.read_order(api, order["id"]),
            status=OrderStatus.CONFIRMED.value,
            version=confirmed["version"],
        )


class TestGuardsOwnedByANeighbouringRecord:
    """The blocking condition lives on a child aggregate, not on the record itself."""

    def _flock_with_allocated_lot(self, api: ApiClient):
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            storage_temp_c=15.0,
            collected_at="2026-07-30T00:00:00Z",
            collected_count=6500,
        )
        unit = fx.create_unit(api, code="U1", unit_type=UnitType.SETTER.value)
        profile = fx.create_profile(api)
        load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(
                    unit["id"], profile["id"], fx.STANDARD_PLANNED_SET_AT
                ),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        fx.draw_eggs(api, load["id"], lot["id"], 6000)
        return {"flock": flock, "lot": lot, "load": load}

    def test_depletion_waits_for_the_allocated_lot_to_come_back(self, api):
        """PRD 3.2: "Depleting from `IN_LAY` carries one extra guard: no egg lot of the
        flock may still be in `ALLOCATED`, because those eggs are already committed to a
        planned setter load; such an attempt is rejected with `ERR_FLOCK_INVALID_STATE`."

        Design: Corner/state_machines/flock_cannot_deplete_while_lot_allocated
        """
        ctx = self._flock_with_allocated_lot(api)
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]),
            status=EggLotStatus.ALLOCATED.value,
            eggs_remaining=200,
        )

        blocked = api.deplete_flock(ctx["flock"]["id"], FLOCK_MANAGER)

        validate_error(blocked, ApiErrorId.ERR_FLOCK_INVALID_STATE, 409)
        assert_breeder_flock(
            fx.read_flock(api, ctx["flock"]["id"]),
            status=FlockStatus.IN_LAY.value,
            settable_forecast=5754,
        )

        validate_success(
            api.abort_setter_load(ctx["load"]["id"], "FLOCK_DEPLETION", HATCHERY_MANAGER),
            200,
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]),
            status=EggLotStatus.IN_STORAGE.value,
            eggs_remaining=6200,
        )

        depleted = validate_success(
            api.deplete_flock(ctx["flock"]["id"], FLOCK_MANAGER), 200
        )
        assert_breeder_flock(
            depleted,
            status=FlockStatus.DEPLETED.value,
            settable_forecast=0,
            production_rate_pct=0.0,
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]),
            status=EggLotStatus.IN_STORAGE.value,
            eggs_remaining=6200,
        )


class TestACyclicLifecycle:
    """Failed verification is a loop, not a dead end."""

    def test_failed_verification_reopens_the_action_and_only_a_pass_lifts_the_derate(
        self, api
    ):
        """PRD 3.9: "An outcome of `FAIL` moves the action `IMPLEMENTED → OPEN`, adds 1 to
        `verification_round` and clears `implementation_note` back to null; the action then
        re-enters the acknowledge-implement-verify loop and must be acknowledged again before
        it can be implemented." And: "An outcome of `PASS` moves the action `IMPLEMENTED →
        VERIFIED`, decrements the flock's `corrective_action_count` by 1 and recomputes its
        `settable_forecast` — the 0.95 derate falls away only once the count returns to 0, so
        a flock carrying two open actions stays derated after the first is verified." And: "in
        both outcomes the acting `X-User-ID` must differ from the recorded
        `opened_by_user_id` or the call is rejected with `ERR_SEGREGATION_OF_DUTIES` before
        the action's state is examined."

        Design: Corner/state_machines/corrective_action_failed_verification_reopens_cycle
        """
        ctx = fx.low_hatchability_boxed_context(api, box_headers=CHICK_PROCESSOR)
        action = fx.open_corrective_action(api, ctx["flock"]["id"])
        assert_corrective_action(
            action,
            status=CorrectiveActionStatus.OPEN.value,
            verification_round=1,
            opened_by_user_id="u_proc_1",
        )
        assert_two_dp(
            action["observed_hatchability_pct"], 81.99, "observed_hatchability_pct"
        )
        assert_forecast_chain(
            fx.read_flock(api, ctx["flock"]["id"]), settable_forecast=5308
        )

        acknowledged = validate_success(
            api.acknowledge_corrective_action(action["id"], FLOCK_MANAGER), 200
        )
        assert_corrective_action(
            acknowledged, status=CorrectiveActionStatus.ACKNOWLEDGED.value
        )
        implemented = validate_success(
            api.implement_corrective_action(
                action["id"], "Adjusted feed to 168 g and re-set lighting", FLOCK_MANAGER
            ),
            200,
        )
        assert_corrective_action(
            implemented,
            status=CorrectiveActionStatus.IMPLEMENTED.value,
            implementation_note="Adjusted feed to 168 g and re-set lighting",
        )

        by_the_opener = api.verify_corrective_action(
            action["id"],
            VerificationOutcome.PASS.value,
            make_headers(Role.VETERINARIAN.value, "u_proc_1"),
        )
        validate_error(by_the_opener, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        assert_corrective_action(
            fx.read_action(api, action["id"]),
            status=CorrectiveActionStatus.IMPLEMENTED.value,
        )

        failed = validate_success(
            api.verify_corrective_action(
                action["id"], VerificationOutcome.FAIL.value, VETERINARIAN_2
            ),
            200,
        )
        assert_corrective_action(
            failed,
            status=CorrectiveActionStatus.OPEN.value,
            verification_round=2,
        )
        assert failed["implementation_note"] is None, (
            "a failed round clears the note so the next round starts clean"
        )
        flock_after_fail = fx.read_flock(api, ctx["flock"]["id"])
        assert flock_after_fail["corrective_action_count"] == 1, (
            "a failed verification does not close the action"
        )
        assert_forecast_chain(flock_after_fail, settable_forecast=5308)

        validate_success(
            api.acknowledge_corrective_action(action["id"], FLOCK_MANAGER), 200
        )
        validate_success(
            api.implement_corrective_action(
                action["id"], "Second round: culled low-fertility males", FLOCK_MANAGER
            ),
            200,
        )
        verified = validate_success(
            api.verify_corrective_action(
                action["id"], VerificationOutcome.PASS.value, VETERINARIAN_2
            ),
            200,
        )

        assert_corrective_action(
            verified,
            status=CorrectiveActionStatus.VERIFIED.value,
            verification_round=2,
        )
        flock_after_pass = fx.read_flock(api, ctx["flock"]["id"])
        assert flock_after_pass["corrective_action_count"] == 0, (
            "a passing verification closes the action"
        )
        assert_forecast_chain(flock_after_pass, settable_forecast=5587)
