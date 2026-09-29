"""Endpoint behaviour that is not a single field write: a read that recomputes, a
nested write that resolves two identifiers in a fixed order, a bulk call that returns
fewer rows than it had candidates, and the run-time guards that refuse a step.
"""

from test_helpers import (
    CHICK_PROCESSOR,
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    NON_EXISTENT_UUID,
    VETERINARIAN_2,
    ApiErrorId,
    AssignmentStatus,
    CorrectiveActionStatus,
    EggLotStatus,
    ItemStatus,
    OccupancyStatus,
    OrderStatus,
    Role,
    SetterLoadStatus,
    TriggerReason,
    UnitType,
    VerificationOutcome,
    assert_chick_batch,
    assert_chick_conservation,
    assert_corrective_action,
    assert_delivery_assignment,
    assert_egg_lot,
    assert_incubation_unit,
    assert_placement_order,
    assert_setter_load,
    assert_setter_load_item,
    assert_stamped_at,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A second unresolvable identifier, so a request can miss on both sides at once.
OTHER_NON_EXISTENT_UUID = "00000000-0000-0000-0000-0000000000fe"

#: A 9000-chick pull sexed with 450 culls, giving a saleable pool of 8481.
TIER_B_SEXING = {
    "male_count": 4275,
    "female_count": 4275,
    "unsexed_count": 0,
    "sexing_cull_count": 450,
}


class TestReadsThatRecompute:
    """A GET may return a different number than the last GET without any write."""

    def test_the_same_stored_lot_ages_between_two_reads(self, api):
        """PRD 2.4: "Reading a single egg lot likewise recomputes `effective_age_days` against
        the current clock without incrementing its `version`." And PRD 3.4: "Multiply that base
        by a storage factor: 2.0 while the lot has never been stored, meaning its `stored_at` is
        still null; 1.5 once it has been stored at a `storage_temp_c` strictly greater than 18.0
        degrees Celsius; and 1.0 once it has been stored at 18.0 degrees or below."

        Design: Corner/endpoints/egg_lot_effective_age_recomputed_on_every_read
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

        first_read = validate_success(
            api.get_egg_lot(lot["id"], INCUBATION_OPERATOR), 200
        )
        fx.set_clock(api, "2026-08-03T00:00:00Z")
        second_read = validate_success(
            api.get_egg_lot(lot["id"], INCUBATION_OPERATOR), 200
        )

        assert_two_dp(first_read["effective_age_days"], 2.50, "effective_age_days")
        assert_egg_lot(
            first_read,
            status=EggLotStatus.IN_STORAGE.value,
            storage_temp_c=15.0,
            sanitation_cycle_count=0,
        )
        assert_two_dp(second_read["effective_age_days"], 4.00, "effective_age_days")
        assert_egg_lot(
            second_read,
            settable_count=10000,
            eggs_remaining=10000,
            sanitation_cycle_count=0,
        )
        assert second_read["version"] == first_read["version"], (
            "recomputing the age on read is not a write"
        )
        assert second_read["updated_at"] == first_read["updated_at"]


class TestIdentifierResolutionOrder:
    """Path before body, and one not-found code per entity."""

    def test_a_draw_reports_the_missing_load_before_the_missing_lot(self, api):
        """PRD 2.8: "Foreign-key identifiers supplied in a request body are resolved after the
        path, in the order in which the fields are declared on the entity being created, and
        they use the code of the *parent* entity that failed to resolve." And: "a draw against a
        non-existent load likewise reports the load's absence rather than the egg lot's."

        Design: Corner/endpoints/item_link_requires_both_load_and_lot_or_not_found
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
        unit = fx.sanitized_unit(
            api, code="U1", unit_type=UnitType.SETTER.value, capacity_eggs=20000
        )
        load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(
                    unit["id"], profile["id"], fx.STANDARD_PLANNED_SET_AT
                ),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        version = lot["version"]

        unknown_load = api.draw_eggs(
            NON_EXISTENT_UUID,
            f.draw_payload(lot["id"], 1000, version),
            INCUBATION_OPERATOR,
        )
        after_unknown_load = fx.read_lot(api, lot["id"])
        unknown_lot = api.draw_eggs(
            load["id"],
            f.draw_payload(NON_EXISTENT_UUID, 1000, version),
            INCUBATION_OPERATOR,
        )
        both_unknown = api.draw_eggs(
            NON_EXISTENT_UUID,
            f.draw_payload(OTHER_NON_EXISTENT_UUID, 1000, version),
            INCUBATION_OPERATOR,
        )
        item = get_success_data(
            api.draw_eggs(
                load["id"],
                f.draw_payload(lot["id"], 1000, version),
                INCUBATION_OPERATOR,
            ),
            201,
        )

        validate_error(unknown_load, ApiErrorId.ERR_SETTER_LOAD_NOT_FOUND, 404)
        assert_egg_lot(
            after_unknown_load,
            status=EggLotStatus.IN_STORAGE.value,
            eggs_remaining=10000,
        )
        validate_error(unknown_lot, ApiErrorId.ERR_EGG_LOT_NOT_FOUND, 404)
        validate_error(both_unknown, ApiErrorId.ERR_SETTER_LOAD_NOT_FOUND, 404)
        assert_setter_load_item(
            item,
            setter_load_id=load["id"],
            egg_lot_id=lot["id"],
            eggs_taken=1000,
            item_status=ItemStatus.ACTIVE.value,
        )
        _of_load, load_meta = validate_paginated(
            api.list_setter_load_items(load["id"], INCUBATION_OPERATOR)
        )
        _of_lot, lot_meta = validate_paginated(
            api.list_egg_lot_draws(lot["id"], INCUBATION_OPERATOR)
        )
        assert load_meta["total_count"] == 1, "the draw is visible from the load side"
        assert lot_meta["total_count"] == 1, "and from the lot side"

    def test_each_collection_answers_an_unknown_identifier_in_its_own_words(self, api):
        """PRD 2.8: "Each entity has its own not-found code: `ERR_FLOCK_PROGRAM_NOT_FOUND`,
        `ERR_INCUBATION_PROFILE_NOT_FOUND`, `ERR_INCUBATION_UNIT_NOT_FOUND`,
        `ERR_BREEDER_FLOCK_NOT_FOUND`, `ERR_EGG_LOT_NOT_FOUND`, `ERR_SETTER_LOAD_NOT_FOUND`,
        `ERR_HATCHER_LOAD_NOT_FOUND`, `ERR_CHICK_BATCH_NOT_FOUND`, `ERR_GROWER_FARM_NOT_FOUND`,
        `ERR_PLACEMENT_ORDER_NOT_FOUND`, `ERR_DELIVERY_ASSIGNMENT_NOT_FOUND`,
        `ERR_LAB_TEST_NOT_FOUND` and `ERR_CORRECTIVE_ACTION_NOT_FOUND`, each returned with HTTP
        404."

        Design: Corner/errors/every_entity_read_with_unknown_id_not_found
        """
        fx.set_clock(api, fx.CLOCK_SETUP)

        probes = [
            (api.get_flock_program, ApiErrorId.ERR_FLOCK_PROGRAM_NOT_FOUND),
            (api.get_incubation_profile, ApiErrorId.ERR_INCUBATION_PROFILE_NOT_FOUND),
            (api.get_incubation_unit, ApiErrorId.ERR_INCUBATION_UNIT_NOT_FOUND),
            (api.get_breeder_flock, ApiErrorId.ERR_BREEDER_FLOCK_NOT_FOUND),
            (api.get_egg_lot, ApiErrorId.ERR_EGG_LOT_NOT_FOUND),
            (api.get_setter_load, ApiErrorId.ERR_SETTER_LOAD_NOT_FOUND),
            (api.get_hatcher_load, ApiErrorId.ERR_HATCHER_LOAD_NOT_FOUND),
            (api.get_chick_batch, ApiErrorId.ERR_CHICK_BATCH_NOT_FOUND),
            (api.get_grower_farm, ApiErrorId.ERR_GROWER_FARM_NOT_FOUND),
            (api.get_placement_order, ApiErrorId.ERR_PLACEMENT_ORDER_NOT_FOUND),
            (api.get_delivery_assignment, ApiErrorId.ERR_DELIVERY_ASSIGNMENT_NOT_FOUND),
            (api.get_lab_test, ApiErrorId.ERR_LAB_TEST_NOT_FOUND),
            (api.get_corrective_action, ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_FOUND),
        ]

        for reader, expected in probes:
            validate_error(reader(NON_EXISTENT_UUID, HATCHERY_MANAGER), expected, 404)


class TestBulkAndRepeatedActions:
    """One call may serve fewer orders than qualified; none may serve one twice."""

    def test_the_pool_runs_out_before_the_second_eligible_order(self, api):
        """PRD 3.8: "If the pool holds fewer than 100 chicks, stop immediately". And: "Each
        order the run served advances: from `CONFIRMED` to `PARTIALLY_FULFILLED` when the grant
        is less than its `remaining_need`". And: "any sub-box remainder simply stays there — it
        is never allocated."

        Design: Corner/endpoints/allocation_response_shorter_than_eligible_order_list
        """
        ctx = fx.allocation_ready_context(
            api,
            farm_capacity=20000,
            orders=[
                {
                    "requested_chicks": 12000,
                    "requested_placement_date": "2026-08-22T00:00:00Z",
                },
                {
                    "requested_chicks": 4000,
                    "requested_placement_date": "2026-08-23T00:00:00Z",
                },
            ],
            fertile_count=9600,
            hatched_count=9000,
            sexing=TIER_B_SEXING,
        )
        big_order, small_order = ctx["orders"]
        boxed_version = ctx["batch"]["version"]

        assignments = fx.run_allocation(api, ctx["batch"]["id"], boxed_version)

        assert len(assignments) == 1, (
            f"the pool cannot reach the second order, got {assignments}"
        )
        assert_delivery_assignment(
            assignments[0],
            placement_order_id=big_order["id"],
            chicks_assigned=8400,
            boxes_assigned=84,
            status=AssignmentStatus.ASSIGNED.value,
        )
        assert_placement_order(
            fx.read_order(api, big_order["id"]),
            status=OrderStatus.PARTIALLY_FULFILLED.value,
            allocated_chicks=8400,
            remaining_need=3600,
        )
        assert_placement_order(
            fx.read_order(api, small_order["id"]),
            status=OrderStatus.CONFIRMED.value,
            allocated_chicks=0,
            remaining_need=4000,
        )
        batch = fx.read_batch(api, ctx["batch"]["id"])
        assert_chick_batch(batch, unassigned_chicks=81)
        assert batch["version"] == boxed_version + 1, (
            "one allocation run is one write on the batch"
        )
        rows = fx.list_assignments_of_batch(api, ctx["batch"]["id"])
        assert len(rows) == 1, f"only one assignment exists, got {rows}"
        assert_chick_conservation(batch, rows)

    def test_delivery_is_accepted_once_and_then_refused(self, api):
        """PRD 3.9: "On success `delivered_at` is stamped from the logical clock and the
        assignment's `version` increments by 1. `DELIVERED` is terminal." And PRD 2.11: "The
        delivery assignment admits the requested transition — `ERR_ASSIGNMENT_INVALID_STATE`
        (409), on deliver and reverse."

        Design: Corner/endpoints/delivery_conditional_action_then_repeat_conflict
        """
        ctx = fx.allocation_ready_context(
            api,
            farm_capacity=20000,
            orders=[
                {
                    "requested_chicks": 5000,
                    "requested_placement_date": "2026-08-22T00:00:00Z",
                }
            ],
            fertile_count=9600,
            hatched_count=9000,
            sexing=TIER_B_SEXING,
        )
        order = ctx["orders"][0]
        assignment = fx.run_allocation(api, ctx["batch"]["id"])[0]

        delivered = validate_success(
            api.deliver_assignment(assignment["id"], HATCHERY_MANAGER), 200
        )
        repeat = api.deliver_assignment(assignment["id"], HATCHERY_MANAGER)

        assert_delivery_assignment(
            delivered,
            status=AssignmentStatus.DELIVERED.value,
            chicks_assigned=5000,
            boxes_assigned=50,
            scheduled_delivery_date=assignment["scheduled_delivery_date"],
        )
        assert_stamped_at(
            delivered, "delivered_at", fx.CLOCK_PULL_IN_WINDOW, "DeliveryAssignment"
        )
        validate_error(repeat, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE, 409)
        after_repeat = fx.read_assignment(api, assignment["id"])
        assert after_repeat["delivered_at"] == delivered["delivered_at"], (
            "the refused second delivery does not re-stamp the instant"
        )
        assert_placement_order(
            fx.read_order(api, order["id"]),
            status=OrderStatus.FULFILLED.value,
            allocated_chicks=5000,
        )
        batch = fx.read_batch(api, ctx["batch"]["id"])
        assert_chick_batch(batch, unassigned_chicks=3481)
        assert_chick_conservation(
            batch, fx.list_assignments_of_batch(api, ctx["batch"]["id"])
        )


class TestRunTimeGuards:
    """A machine physically held, and a ladder that cannot be entered mid-way."""

    def test_a_second_load_may_be_planned_in_a_machine_but_not_started_in_it(self, api):
        """PRD 3.5: "the machine's `occupancy_status` must be `FREE`, otherwise
        `ERR_UNIT_OCCUPIED`". And PRD 3.1: "`occupancy_status` is `OCCUPIED` while a non-terminal
        load holds the machine and is released back to `FREE` by transfer, by abort, or by the
        boxing that finishes a hatch."

        Design: Corner/errors/second_load_in_occupied_unit_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        first_lot = fx.stored_lot(
            api,
            flock["id"],
            grade={
                "grade_a_count": 6000,
                "cracked_count": 150,
                "dirty_count": 100,
                "small_count": 50,
            },
            storage_temp_c=15.0,
            collected_at="2026-07-30T00:00:00Z",
            collected_count=6300,
        )
        second_lot = fx.stored_lot(
            api,
            flock["id"],
            grade={
                "grade_a_count": 4000,
                "cracked_count": 100,
                "dirty_count": 60,
                "small_count": 40,
            },
            storage_temp_c=15.0,
            collected_at="2026-07-31T00:00:00Z",
            collected_count=4200,
        )
        profile = fx.create_profile(api)
        unit = fx.sanitized_unit(
            api, code="U1", unit_type=UnitType.SETTER.value, capacity_eggs=20000
        )
        first_load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(
                    unit["id"], profile["id"], fx.STANDARD_PLANNED_SET_AT
                ),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        fx.draw_eggs(api, first_load["id"], first_lot["id"], 6000)
        second_load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(
                    unit["id"], profile["id"], "2026-10-01T18:00:00Z"
                ),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        fx.draw_eggs(api, second_load["id"], second_lot["id"], 4000)
        fx.set_clock(api, fx.STANDARD_PLANNED_SET_AT)
        started = validate_success(
            api.start_setter_load(first_load["id"], INCUBATION_OPERATOR), 200
        )
        validate_success(api.sanitize_incubation_unit(unit["id"], INCUBATION_OPERATOR), 200)

        refused = api.start_setter_load(second_load["id"], INCUBATION_OPERATOR)

        validate_error(refused, ApiErrorId.ERR_UNIT_OCCUPIED, 409)
        assert_setter_load(started, status=SetterLoadStatus.INCUBATING.value)
        assert_incubation_unit(
            fx.read_unit(api, unit["id"]),
            occupancy_status=OccupancyStatus.OCCUPIED.value,
        )
        blocked = fx.read_load(api, second_load["id"])
        assert_setter_load(
            blocked, status=SetterLoadStatus.PLANNED.value, total_eggs_set=4000
        )
        # ``weighted_age_days`` is recomputed by the draw, not by the start, so
        # only the instants and the delay the start would have derived stay null.
        for field in ("set_at", "storage_delay_hours", "planned_transfer_at"):
            assert blocked[field] is None, (
                f"the refused start left {field} unstamped, got {blocked[field]}"
            )
        assert_egg_lot(
            fx.read_lot(api, second_lot["id"]),
            status=EggLotStatus.ALLOCATED.value,
            eggs_remaining=0,
        )

    def test_the_corrective_ladder_cannot_be_entered_at_its_second_rung(self, api):
        """PRD 3.9: "A `FlockManager` acknowledges an `OPEN` action, moving it `OPEN →
        ACKNOWLEDGED` and incrementing its `version`. The same `FlockManager` role then records
        the measure taken by supplying a `note`, moving the action `ACKNOWLEDGED → IMPLEMENTED`".
        And: "Verification belongs to a `Veterinarian`, who supplies an `outcome`, and in both
        outcomes the acting `X-User-ID` must differ from the recorded `opened_by_user_id` or the
        call is rejected with `ERR_SEGREGATION_OF_DUTIES` before the action's state is examined."

        Design: Corner/errors/corrective_action_out_of_order_steps_rejected
        """
        ctx = fx.low_hatchability_boxed_context(api, box_headers=CHICK_PROCESSOR)
        action = fx.open_corrective_action(api, ctx["flock"]["id"])

        assert_corrective_action(
            action,
            flock_id=ctx["flock"]["id"],
            status=CorrectiveActionStatus.OPEN.value,
            trigger_reason=TriggerReason.HATCHABILITY_BELOW_THRESHOLD.value,
            verification_round=1,
        )
        assert_two_dp(
            action["observed_hatchability_pct"], 81.99, "observed_hatchability_pct"
        )

        early_implement = api.implement_corrective_action(
            action["id"], "Skipping the acknowledgement", FLOCK_MANAGER
        )
        early_verify = api.verify_corrective_action(
            action["id"], VerificationOutcome.PASS.value, VETERINARIAN_2
        )
        by_the_opener = api.verify_corrective_action(
            action["id"],
            VerificationOutcome.PASS.value,
            make_headers(Role.VETERINARIAN.value, "u_proc_1"),
        )
        acknowledged = validate_success(
            api.acknowledge_corrective_action(action["id"], FLOCK_MANAGER), 200
        )

        validate_error(
            early_implement, ApiErrorId.ERR_CORRECTIVE_ACTION_INVALID_STATE, 409
        )
        validate_error(
            early_verify, ApiErrorId.ERR_CORRECTIVE_ACTION_INVALID_STATE, 409
        )
        validate_error(by_the_opener, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        assert_corrective_action(
            acknowledged,
            status=CorrectiveActionStatus.ACKNOWLEDGED.value,
            verification_round=1,
        )
        assert acknowledged["implementation_note"] is None, (
            "the refused implementation stored no note"
        )
        flock = fx.read_flock(api, ctx["flock"]["id"])
        assert flock["corrective_action_count"] == 1
        assert flock["settable_forecast"] == 5308, (
            "the derate stands until a PASS verification lifts it"
        )
