"""Rejected requests, and the accepted one that follows each rejection: counts that
must reconcile, windows that bound a client instant on one side only, machine fit,
and the four agreements a request must reach with records it merely references.
"""

from test_helpers import (
    CHICK_PROCESSOR,
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    ApiErrorId,
    BiosecurityStatus,
    Breed,
    ChickBatchStatus,
    EggLotStatus,
    FlockStatus,
    HatcherLoadStatus,
    LabSubjectType,
    LabTestCode,
    LabTestStatus,
    OccupancyStatus,
    OrderStatus,
    SanitationStatus,
    SetterLoadStatus,
    UnitType,
    assert_chick_batch,
    assert_egg_lot,
    assert_grower_farm,
    assert_incubation_unit,
    assert_lab_test,
    assert_placement_order,
    assert_setter_load,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A 9000-chick pull sexed with 450 culls, giving a saleable pool of 8481.
TIER_B_SEXING = {
    "male_count": 4275,
    "female_count": 4275,
    "unsexed_count": 0,
    "sexing_cull_count": 450,
}


class TestCountsThatMustReconcile:
    """Grading, candling, pulling and sexing each compare a count to its source."""

    def test_grading_sub_counts_must_sum_and_must_leave_a_settable_egg(self, api):
        """PRD 3.4: "The four sub-counts must sum to exactly `collected_count`, or the request
        is rejected with `ERR_GRADE_COUNT_MISMATCH`; and `grade_a_count` must be at least 1, or
        the request is rejected with `ERR_NO_SETTABLE_EGGS`". And: "A new lot has `status` of
        `COLLECTED`, a `settable_count` of 0".

        Design: Corner/validations/grade_count_mismatch_and_no_settable_eggs_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot = fx.collect_lot(
            api, flock["id"], collected_at="2026-07-30T00:00:00Z", collected_count=10500
        )

        mismatched = api.grade_egg_lot(
            lot["id"],
            f.grade_payload(
                grade_a_count=4000, cracked_count=300, dirty_count=150, small_count=50
            ),
            FLOCK_MANAGER,
        )
        after_mismatch = fx.read_lot(api, lot["id"])
        nothing_settable = api.grade_egg_lot(
            lot["id"],
            f.grade_payload(
                grade_a_count=0, cracked_count=10000, dirty_count=300, small_count=200
            ),
            FLOCK_MANAGER,
        )
        graded = validate_success(
            api.grade_egg_lot(
                lot["id"],
                f.grade_payload(
                    grade_a_count=10000,
                    cracked_count=300,
                    dirty_count=150,
                    small_count=50,
                ),
                FLOCK_MANAGER,
            ),
            200,
        )

        validate_error(mismatched, ApiErrorId.ERR_GRADE_COUNT_MISMATCH, 422)
        assert_egg_lot(
            after_mismatch,
            status=EggLotStatus.COLLECTED.value,
            settable_count=0,
            version=1,
        )
        validate_error(nothing_settable, ApiErrorId.ERR_NO_SETTABLE_EGGS, 422)
        assert_egg_lot(
            graded,
            status=EggLotStatus.GRADED.value,
            settable_count=10000,
            eggs_remaining=10000,
            version=2,
        )

    def test_derived_counts_may_not_exceed_their_source_along_the_chain(self, api):
        """PRD 3.5: "The `fertile_count` may not exceed `total_eggs_set`, or
        `ERR_COUNT_EXCEEDS_SOURCE`". And PRD 3.6: "A `ChickProcessor` supplies a
        `hatched_count` of at least 1 giving the live chicks counted at pull, which may not
        exceed `eggs_transferred` or the pull is rejected with `ERR_COUNT_EXCEEDS_SOURCE`."
        And PRD 3.7: "Sexing supplies four counts — `male_count`, `female_count`,
        `unsexed_count` and `sexing_cull_count` — and they must sum to exactly `hatched_count`
        or the request is rejected with `ERR_SEX_COUNT_MISMATCH`".

        Design: Corner/validations/count_reconciliation_failures_rejected
        """
        ctx = fx.incubating_load_context(api)
        load_id = ctx["load"]["id"]

        over_candle = api.candle_setter_load(load_id, 10001, INCUBATION_OPERATOR)
        after_over_candle = fx.read_load(api, load_id)
        candled = validate_success(
            api.candle_setter_load(load_id, 9600, INCUBATION_OPERATOR), 200
        )

        validate_error(over_candle, ApiErrorId.ERR_COUNT_EXCEEDS_SOURCE, 422)
        assert_setter_load(
            after_over_candle, status=SetterLoadStatus.INCUBATING.value
        )
        assert after_over_candle["fertile_count"] is None, (
            "the rejected candling records no fertility"
        )
        assert_setter_load(candled, status=SetterLoadStatus.CANDLED.value)
        assert_two_dp(candled["fertility_pct"], 96.00, "fertility_pct")

        hatcher_unit = fx.sanitized_unit(
            api, code="U2", unit_type=UnitType.HATCHER.value, capacity_eggs=20000
        )
        fx.set_clock(api, fx.STANDARD_TRANSFER_AT)
        hatcher_load = get_success_data(
            api.transfer_setter_load(load_id, hatcher_unit["id"], INCUBATION_OPERATOR),
            201,
        )
        fx.set_clock(api, fx.CLOCK_PULL_IN_WINDOW)

        over_pull = api.pull_chicks(hatcher_load["id"], 10001, CHICK_PROCESSOR)
        after_over_pull = fx.read_hatcher_load(api, hatcher_load["id"])
        _batches, batch_meta = validate_paginated(
            api.list_chick_batches(CHICK_PROCESSOR)
        )
        batch = get_success_data(
            api.pull_chicks(hatcher_load["id"], 9400, CHICK_PROCESSOR), 201
        )

        validate_error(over_pull, ApiErrorId.ERR_COUNT_EXCEEDS_SOURCE, 422)
        assert after_over_pull["status"] == HatcherLoadStatus.HATCHING.value
        assert batch_meta["total_count"] == 0, "the rejected pull creates no batch"

        short_sexing = api.sex_chick_batch(
            batch["id"],
            f.sexing_payload(
                male_count=4600, female_count=4700, unsexed_count=0, sexing_cull_count=50
            ),
            CHICK_PROCESSOR,
        )
        after_short_sexing = fx.read_batch(api, batch["id"])
        sexed = validate_success(
            api.sex_chick_batch(
                batch["id"], f.sexing_payload(**fx.HEALTHY_SEXING), CHICK_PROCESSOR
            ),
            200,
        )

        validate_error(short_sexing, ApiErrorId.ERR_SEX_COUNT_MISMATCH, 422)
        assert_chick_batch(
            after_short_sexing, status=ChickBatchStatus.PULLED.value
        )
        assert after_short_sexing["male_count"] is None, (
            "the rejected sexing stores none of the four counts"
        )
        assert_chick_batch(sexed, status=ChickBatchStatus.SEXED.value)
        assert_two_dp(sexed["preliminary_yield_pct"], 98.94, "preliminary_yield_pct")


class TestBoundsOnScalarFields:
    """A window may be bounded on both sides, on one side, or by a floor of 100."""

    def test_the_page_window_is_bounded_on_both_sides_and_an_order_has_a_floor(
        self, api
    ):
        """PRD 2.3: "A `limit` of 0, a `limit` of 101 or a negative `offset` is rejected with
        `ERR_INVALID_PAGINATION` (400)." And PRD 3.8: "a `requested_chicks` count that must be
        at least one full box of 100 chicks." And PRD 2.11: "Every count field at or above its
        declared minimum and never negative — `ERR_NON_POSITIVE_COUNT` (400)."

        Design: Corner/validations/pagination_bounds_and_below_minimum_counts_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        farm = fx.cleared_farm(api)

        below_window = api.list_egg_lots(HATCHERY_MANAGER, {"limit": 0})
        above_window = api.list_egg_lots(HATCHERY_MANAGER, {"limit": 101})
        negative_offset = api.list_placement_orders(HATCHERY_MANAGER, {"offset": -1})
        half_box = api.create_placement_order(
            f.placement_order_payload(farm["id"], requested_chicks=50),
            HATCHERY_MANAGER,
        )
        whole_box = api.create_placement_order(
            f.placement_order_payload(farm["id"], requested_chicks=100),
            HATCHERY_MANAGER,
        )

        validate_error(below_window, ApiErrorId.ERR_INVALID_PAGINATION, 400)
        validate_error(above_window, ApiErrorId.ERR_INVALID_PAGINATION, 400)
        validate_error(negative_offset, ApiErrorId.ERR_INVALID_PAGINATION, 400)
        validate_error(half_box, ApiErrorId.ERR_NON_POSITIVE_COUNT, 400)
        assert_placement_order(
            get_success_data(whole_box, 201),
            status=OrderStatus.REQUESTED.value,
            requested_chicks=100,
            allocated_chicks=0,
            remaining_need=100,
        )
        _orders, meta = validate_paginated(api.list_placement_orders(HATCHERY_MANAGER))
        assert meta["total_count"] == 1, "only the whole-box order was accepted"

    def test_one_error_code_guards_a_past_bound_here_and_a_future_bound_there(self, api):
        """PRD 3.4: "The `collected_at` instant may not be in the future relative to the
        logical clock." And PRD 3.3: "`collected_at` may not be later than the current logical
        clock." And PRD 3.8: "The `requested_placement_date` may not fall before the current
        logical clock date."

        Design: Corner/validations/client_timestamps_outside_admissible_range_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        farm = fx.cleared_farm(api)

        future_collection = api.create_egg_lot(
            f.egg_lot_payload(
                flock["id"],
                collected_at="2026-08-02T00:00:00Z",
                collected_count=500,
            ),
            FLOCK_MANAGER,
        )
        future_sample = api.create_lab_test(
            f.lab_test_payload(
                flock["id"],
                test_code=LabTestCode.MYCOPLASMA_GALLISEPTICUM.value,
                collected_at="2026-08-01T18:00:00Z",
            ),
            VETERINARIAN,
        )
        past_placement = api.create_placement_order(
            f.placement_order_payload(
                farm["id"], requested_placement_date="2026-07-31T00:00:00Z"
            ),
            HATCHERY_MANAGER,
        )
        on_the_clock = api.create_egg_lot(
            f.egg_lot_payload(
                flock["id"],
                collected_at=fx.CLOCK_SETUP,
                collected_count=500,
            ),
            FLOCK_MANAGER,
        )

        validate_error(future_collection, ApiErrorId.ERR_TIMESTAMP_OUT_OF_RANGE, 422)
        validate_error(future_sample, ApiErrorId.ERR_TIMESTAMP_OUT_OF_RANGE, 422)
        validate_error(past_placement, ApiErrorId.ERR_TIMESTAMP_OUT_OF_RANGE, 422)
        assert_egg_lot(
            get_success_data(on_the_clock, 201),
            flock_id=flock["id"],
            collected_at=fx.CLOCK_SETUP,
            status=EggLotStatus.COLLECTED.value,
        )
        _lots, meta = validate_paginated(
            api.list_egg_lots(FLOCK_MANAGER, {"flock_id": flock["id"]})
        )
        assert meta["total_count"] == 1, (
            "only the collection standing exactly on the clock was accepted"
        )
        _orders, order_meta = validate_paginated(
            api.list_placement_orders(HATCHERY_MANAGER)
        )
        assert order_meta["total_count"] == 0, "the back-dated order was not created"


class TestMachineFitBeforeIncubation:
    """Type at planning, emptiness before capacity, capacity only once eggs exist."""

    def test_a_hatcher_cannot_host_a_setter_load_and_an_empty_load_cannot_start(
        self, api
    ):
        """PRD 3.1: "A `SETTER` machine accepts setter loads; a `HATCHER` machine accepts
        transfers; using one where the other is required is rejected with
        `ERR_UNIT_TYPE_MISMATCH`." And PRD 3.5: "at least one `ACTIVE` draw must exist,
        otherwise `ERR_NO_EGGS_LOADED`" and "`total_eggs_set` must not exceed the machine's
        `capacity_eggs`, otherwise `ERR_UNIT_CAPACITY_EXCEEDED`".

        Design: Corner/validations/unit_type_capacity_and_empty_load_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot = fx.stored_lot(
            api,
            flock["id"],
            storage_temp_c=15.0,
            collected_at="2026-07-30T00:00:00Z",
            collected_count=10500,
        )
        profile = fx.create_profile(api)
        setter = fx.sanitized_unit(
            api, code="U1", unit_type=UnitType.SETTER.value, capacity_eggs=5000
        )
        hatcher = fx.create_unit(
            api, code="U2", unit_type=UnitType.HATCHER.value, capacity_eggs=20000
        )

        wrong_machine = api.create_setter_load(
            f.setter_load_payload(
                hatcher["id"], profile["id"], fx.STANDARD_PLANNED_SET_AT
            ),
            INCUBATION_OPERATOR,
        )
        load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(
                    setter["id"], profile["id"], fx.STANDARD_PLANNED_SET_AT
                ),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        fx.set_clock(api, fx.STANDARD_PLANNED_SET_AT)
        empty_start = api.start_setter_load(load["id"], INCUBATION_OPERATOR)
        after_empty_start = fx.read_load(api, load["id"])
        fx.draw_eggs(api, load["id"], lot["id"], 10000)
        over_capacity = api.start_setter_load(load["id"], INCUBATION_OPERATOR)

        validate_error(wrong_machine, ApiErrorId.ERR_UNIT_TYPE_MISMATCH, 422)
        validate_error(empty_start, ApiErrorId.ERR_NO_EGGS_LOADED, 422)
        assert_setter_load(
            after_empty_start, status=SetterLoadStatus.PLANNED.value, total_eggs_set=0
        )
        assert after_empty_start["set_at"] is None, "a refused start stamps nothing"
        validate_error(over_capacity, ApiErrorId.ERR_UNIT_CAPACITY_EXCEEDED, 422)
        final_load = fx.read_load(api, load["id"])
        assert_setter_load(
            final_load, status=SetterLoadStatus.PLANNED.value, total_eggs_set=10000
        )
        assert final_load["set_at"] is None
        assert_incubation_unit(
            fx.read_unit(api, setter["id"]),
            sanitation_status=SanitationStatus.SANITIZED.value,
            occupancy_status=OccupancyStatus.FREE.value,
        )
        assert_egg_lot(
            fx.read_lot(api, lot["id"]),
            status=EggLotStatus.ALLOCATED.value,
            eggs_remaining=0,
        )


class TestAgreementWithReferencedRecords:
    """Four requests that are well formed but disagree with a record they name."""

    def test_a_breed_must_match_and_a_retired_programme_backs_nothing(self, api):
        """PRD 3.2: "The flock's `breed` must equal the breed of the programme named by
        `program_id`, or the placement is rejected with `ERR_BREED_MISMATCH`." And PRD 3.1:
        "retiring it sets `retired` to true and increments the programme's `version`, after which it
        rejects new flock placements and new photostimulation attempts with
        `ERR_PROGRAM_RETIRED`."

        Design: Corner/validations/breed_mismatch_and_retired_program_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        first_program = fx.create_program(api, code="P1")
        second_program = fx.create_program(api, code="P2")
        flock = fx.create_flock(api, second_program["id"], code="F1")
        fx.salmonella_clearance(api, flock["id"])

        wrong_breed = api.create_breeder_flock(
            f.breeder_flock_payload(
                first_program["id"],
                code="F2",
                breed=Breed.COBB_500.value,
                house_code="H2",
            ),
            FLOCK_MANAGER,
        )
        retired_first = validate_success(
            api.retire_flock_program(first_program["id"], HATCHERY_MANAGER), 200
        )
        against_retired = api.create_breeder_flock(
            f.breeder_flock_payload(first_program["id"], code="F3", house_code="H3"),
            FLOCK_MANAGER,
        )
        validate_success(
            api.retire_flock_program(second_program["id"], HATCHERY_MANAGER), 200
        )
        stimulate_under_retired = api.start_lay(flock["id"], FLOCK_MANAGER)

        validate_error(wrong_breed, ApiErrorId.ERR_BREED_MISMATCH, 422)
        assert retired_first["retired"] is True
        assert retired_first["version"] == 2, "retiring is a write on the programme"
        validate_error(against_retired, ApiErrorId.ERR_PROGRAM_RETIRED, 409)
        validate_error(stimulate_under_retired, ApiErrorId.ERR_PROGRAM_RETIRED, 409)
        after = fx.read_flock(api, flock["id"])
        assert after["status"] == FlockStatus.PLACED.value, (
            "the refused photostimulation leaves the flock where it was"
        )
        assert after["settable_forecast"] == 5754
        _flocks, meta = validate_paginated(api.list_breeder_flocks(FLOCK_MANAGER))
        assert meta["total_count"] == 1, "neither refused placement created a flock"

    def test_a_laboratory_subject_is_looked_up_only_where_its_discriminator_points(
        self, api
    ):
        """PRD 3.3: "The `subject_type` discriminator is `BREEDER_FLOCK`, `INCUBATION_UNIT` or
        `GROWER_FARM`, and it alone decides where `subject_id` is looked up". And: "An
        identifier that fails to resolve in the discriminated table is rejected with
        `ERR_LAB_SUBJECT_INVALID` even when that same identifier happens to resolve in one of
        the other two tables — the discriminator is not a hint, it is the whole lookup."

        Design: Corner/validations/polymorphic_lab_subject_invalid_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.create_flock(api, program["id"])
        unit = fx.create_unit(api, code="U1", unit_type=UnitType.SETTER.value)

        unit_id_as_flock = api.create_lab_test(
            f.lab_test_payload(
                unit["id"],
                subject_type=LabSubjectType.BREEDER_FLOCK.value,
                test_code=LabTestCode.SALMONELLA_PULLORUM.value,
                collected_at="2026-07-31T00:00:00Z",
            ),
            VETERINARIAN,
        )
        flock_id_as_unit = api.create_lab_test(
            f.lab_test_payload(
                flock["id"],
                subject_type=LabSubjectType.INCUBATION_UNIT.value,
                test_code=LabTestCode.SHELL_HYGIENE.value,
                collected_at="2026-07-31T00:00:00Z",
            ),
            VETERINARIAN,
        )
        on_the_right_table = api.create_lab_test(
            f.lab_test_payload(
                unit["id"],
                subject_type=LabSubjectType.INCUBATION_UNIT.value,
                test_code=LabTestCode.SHELL_HYGIENE.value,
                collected_at="2026-07-31T00:00:00Z",
            ),
            VETERINARIAN,
        )

        validate_error(unit_id_as_flock, ApiErrorId.ERR_LAB_SUBJECT_INVALID, 422)
        validate_error(flock_id_as_unit, ApiErrorId.ERR_LAB_SUBJECT_INVALID, 422)
        assert_lab_test(
            get_success_data(on_the_right_table, 201),
            subject_type=LabSubjectType.INCUBATION_UNIT.value,
            subject_id=unit["id"],
            test_code=LabTestCode.SHELL_HYGIENE.value,
            status=LabTestStatus.PENDING.value,
        )
        _tests, meta = validate_paginated(
            api.list_lab_tests(
                VETERINARIAN,
                {"subject_type": LabSubjectType.INCUBATION_UNIT.value},
            )
        )
        assert meta["total_count"] == 1, (
            "only the sample whose discriminator matched its table was registered"
        )

    def test_confirmation_waits_for_the_veterinarian_to_clear_the_farm(self, api):
        """PRD 3.3: "Only a `CLEARED` farm may have an order confirmed or a delivery accepted;
        anything else reports `ERR_FARM_NOT_CLEARED`." And PRD 3.8: "The destination farm's
        `biosecurity_status` must be `CLEARED`, otherwise `ERR_FARM_NOT_CLEARED`."

        Design: Corner/validations/order_confirmation_for_uncleared_farm_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        farm = fx.pending_farm(
            api, code="FM2", operator_user_id="u_grower_2", capacity_chicks=20000
        )
        order = fx.requested_order(api, farm["id"], requested_chicks=5000)

        too_early = api.confirm_placement_order(order["id"], HATCHERY_MANAGER)
        after_refusal = fx.read_order(api, order["id"])
        farm_before = get_success_data(
            api.get_grower_farm(farm["id"], HATCHERY_MANAGER), 200
        )
        cleared = validate_success(
            api.clear_grower_farm(farm["id"], VETERINARIAN), 200
        )
        confirmed = validate_success(
            api.confirm_placement_order(order["id"], HATCHERY_MANAGER), 200
        )

        validate_error(too_early, ApiErrorId.ERR_FARM_NOT_CLEARED, 422)
        assert_placement_order(
            after_refusal, status=OrderStatus.REQUESTED.value, version=order["version"]
        )
        assert_grower_farm(
            farm_before, biosecurity_status=BiosecurityStatus.PENDING.value
        )
        assert_grower_farm(cleared, biosecurity_status=BiosecurityStatus.CLEARED.value)
        assert_placement_order(
            confirmed,
            status=OrderStatus.CONFIRMED.value,
            allocated_chicks=0,
            remaining_need=5000,
        )

    def test_an_allocation_run_that_matches_no_order_creates_nothing(self, api):
        """PRD 3.8: "If no order qualified for the run in the first place, the entire call is
        rejected with `ERR_NO_ELIGIBLE_PLACEMENT_ORDER` and nothing is created."

        Design: Corner/validations/allocation_with_no_eligible_order_rejected
        """
        ctx = fx.boxed_batch_context(
            api, fertile_count=9600, hatched_count=9000, sexing=TIER_B_SEXING
        )
        batch_id = ctx["batch"]["id"]
        boxed_version = ctx["batch"]["version"]
        farm = fx.cleared_farm(api, code="FM1", capacity_chicks=20000)
        wrong_breed_order = fx.confirmed_order(
            api,
            farm["id"],
            requested_breed=Breed.COBB_500.value,
            requested_placement_date="2026-08-22T00:00:00Z",
            requested_chicks=5000,
        )

        no_match = api.allocate_chicks(batch_id, boxed_version, HATCHERY_MANAGER)

        validate_error(no_match, ApiErrorId.ERR_NO_ELIGIBLE_PLACEMENT_ORDER, 422)
        assert_chick_batch(
            fx.read_batch(api, batch_id), saleable_count=8481, unassigned_chicks=8481
        )
        assert fx.list_assignments_of_batch(api, batch_id) == [], (
            "the refused run creates no delivery assignment"
        )
        assert_placement_order(
            fx.read_order(api, wrong_breed_order["id"]),
            status=OrderStatus.CONFIRMED.value,
            allocated_chicks=0,
            remaining_need=5000,
        )

        matching_order = fx.confirmed_order(
            api,
            farm["id"],
            requested_breed=Breed.ROSS_308.value,
            requested_placement_date="2026-08-23T00:00:00Z",
            requested_chicks=4000,
        )
        assignments = get_success_data(
            api.allocate_chicks(batch_id, boxed_version, HATCHERY_MANAGER), 201
        )

        assert len(assignments) == 1, (
            f"only the breed-matched order is served, got {assignments}"
        )
        assert assignments[0]["placement_order_id"] == matching_order["id"]
        assert assignments[0]["chicks_assigned"] == 4000
        assert assignments[0]["boxes_assigned"] == 40
        assert_chick_batch(fx.read_batch(api, batch_id), unassigned_chicks=4481)
        assert_placement_order(
            fx.read_order(api, matching_order["id"]),
            status=OrderStatus.FULFILLED.value,
            allocated_chicks=4000,
            remaining_need=0,
        )
