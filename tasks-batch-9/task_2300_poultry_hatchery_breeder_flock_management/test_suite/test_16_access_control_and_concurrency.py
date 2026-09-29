"""Who may call what, whose rows a grower principal may see, and the two guarantees
that hold underneath every write: a version that only a mutation moves, and a cascade
that has already finished by the time the response is serialised.
"""

from test_helpers import (
    CHICK_PROCESSOR,
    EGG_LOT_READER_HEADERS,
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    NON_EXISTENT_UUID,
    VETERINARIAN,
    ApiErrorId,
    AssignmentStatus,
    EggLotStatus,
    ItemStatus,
    OccupancyStatus,
    Role,
    SanitationStatus,
    SetterLoadStatus,
    UnitType,
    VerificationOutcome,
    assert_chick_batch,
    assert_delivery_assignment,
    assert_egg_lot,
    assert_incubation_unit,
    assert_instant,
    assert_placement_order,
    assert_setter_load,
    assert_setter_load_item,
    assert_stamped_at,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_unauthenticated_headers,
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


class TestRoleGate:
    """The role gate runs before identity resolution and before existence."""

    def test_seven_operations_refuse_the_neighbouring_role(self, api):
        """PRD 2.1: "A request whose `X-User-Role` is missing, is not one of the six recognised
        role names, or is a recognised role that is not authorised for the addressed operation is
        rejected with `ERR_FORBIDDEN_ROLE` (403); an unrecognised role string is treated as
        unauthorised rather than as a malformed request." And PRD 2.11: "Every `{id}` path
        parameter resolves to a live row of the addressed entity — the entity-specific not-found
        code (404), on every endpoint that addresses a record by path."

        Design: Corner/rbac/rbac_rejects_peer_role_exclusive_operations
        """
        fx.set_clock(api, fx.CLOCK_SETUP)

        attempts = [
            api.create_flock_program(f.flock_program_payload(code="PX"), FLOCK_MANAGER),
            api.create_lab_test(
                f.lab_test_payload(NON_EXISTENT_UUID), HATCHERY_MANAGER
            ),
            api.start_setter_load(NON_EXISTENT_UUID, CHICK_PROCESSOR),
            api.pull_chicks(NON_EXISTENT_UUID, 100, INCUBATION_OPERATOR),
            api.confirm_placement_order(NON_EXISTENT_UUID, CHICK_PROCESSOR),
            api.verify_corrective_action(
                NON_EXISTENT_UUID, VerificationOutcome.PASS.value, FLOCK_MANAGER
            ),
            api.condemn_egg_lot(
                NON_EXISTENT_UUID, "SHELL_QUALITY", INCUBATION_OPERATOR
            ),
        ]

        for index, response in enumerate(attempts):
            validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
            assert response.status_code != 404, (
                f"attempt {index} must not leak that the path id is unknown"
            )
        _rows, meta = validate_paginated(api.list_lab_tests(HATCHERY_MANAGER))
        assert meta["total_count"] == 0, "none of the refused calls created a row"

    def test_a_missing_user_id_outranks_the_role_that_would_have_been_allowed(self, api):
        """PRD 2.1: "A request with a missing or empty `X-User-ID` is rejected with
        `ERR_UNAUTHENTICATED` (401) before its body is even parsed, so a request that is
        simultaneously unauthenticated and malformed reports `ERR_UNAUTHENTICATED` and nothing
        else. The single exception is the logical-clock endpoint, which is reachable without
        authentication."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        anonymous = make_unauthenticated_headers(Role.FLOCK_MANAGER.value)

        listing = api.list_breeder_flocks(anonymous)
        placement = api.create_breeder_flock(
            f.breeder_flock_payload(NON_EXISTENT_UUID, code="F9", house_code="H9"),
            anonymous,
        )

        validate_error(listing, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        validate_error(placement, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert_instant(
            fx.set_clock(api, fx.CLOCK_SETUP, headers=anonymous),
            fx.CLOCK_SETUP,
            "the logical-clock setter is the one endpoint reachable without "
            "authentication and returns the current_utc now in force",
        )

    def test_a_grower_sees_its_own_farms_orders_and_nothing_else(self, api):
        """PRD 2.1: "When `X-User-Role` is `GrowerFarm`, `X-User-ID` is the identifier of the
        acting grower principal and is compared against the `operator_user_id` recorded on the
        `GrowerFarm` row: ownership checks on any farm, placement order or delivery assignment
        resolve the owning farm and require that farm's `operator_user_id` to equal `X-User-ID`,
        failing with `ERR_FARM_SCOPE_VIOLATION` (403) otherwise." And PRD 2.11: "It is checked
        after role authorisation and *before* existence, so an out-of-scope identifier reports the
        scope violation rather than a 404."

        Design: Corner/rbac/farm_principal_cross_farm_read_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        own_farm = fx.pending_farm(
            api, code="FM1", operator_user_id="u_grower_1", capacity_chicks=20000
        )
        sibling_farm = fx.pending_farm(
            api, code="FM2", operator_user_id="u_grower_2", capacity_chicks=20000
        )
        own_order = fx.requested_order(api, own_farm["id"], requested_chicks=5000)
        sibling_order = fx.requested_order(
            api, sibling_farm["id"], requested_chicks=4000
        )
        grower = fx.grower_headers_for(own_farm)

        own_read = validate_success(
            api.get_placement_order(own_order["id"], grower), 200
        )
        sibling_read = api.get_placement_order(sibling_order["id"], grower)
        sibling_farm_read = api.get_grower_farm(sibling_farm["id"], grower)
        cross_farm_write = api.create_placement_order(
            f.placement_order_payload(
                sibling_farm["id"],
                requested_placement_date="2026-08-23T00:00:00Z",
                requested_chicks=3000,
            ),
            grower,
        )

        assert_placement_order(
            own_read, id=own_order["id"], farm_id=own_farm["id"], requested_chicks=5000
        )
        validate_error(sibling_read, ApiErrorId.ERR_FARM_SCOPE_VIOLATION, 403)
        validate_error(sibling_farm_read, ApiErrorId.ERR_FARM_SCOPE_VIOLATION, 403)
        validate_error(cross_farm_write, ApiErrorId.ERR_FARM_SCOPE_VIOLATION, 403)

        scoped, scoped_meta = validate_paginated(api.list_placement_orders(grower))
        every_order, every_meta = validate_paginated(
            api.list_placement_orders(HATCHERY_MANAGER)
        )
        assert scoped_meta["total_count"] == 1, (
            f"the grower may read its own farm's orders and nothing else, got {scoped}"
        )
        assert [row["id"] for row in scoped] == [own_order["id"]]
        assert every_meta["total_count"] == 2, (
            "the refused cross-farm placement created nothing, and both farms' orders exist"
        )

    def test_the_four_roles_that_may_read_a_lot_receive_the_same_row(self, api):
        """PRD 2.4: "Reading a single egg lot likewise recomputes `effective_age_days` against
        the current clock without incrementing its `version`." And PRD 2.5: "`version`, an
        integer that starts at 1 on creation and increments by exactly 1 on every mutation of
        that record."

        Design: Corner/rbac/shared_reads_allowed_for_every_listed_role
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot = fx.graded_lot(
            api, flock["id"], collected_at="2026-07-30T00:00:00Z", collected_count=10500
        )

        reads = [
            validate_success(api.get_egg_lot(lot["id"], headers), 200)
            for headers in EGG_LOT_READER_HEADERS
        ]

        assert len(reads) == 4, "four roles are authorised to read one lot"
        for served in reads:
            assert served == reads[0], (
                "the shared read is not narrowed or reordered per role"
            )
            assert_egg_lot(
                served,
                id=lot["id"],
                status=EggLotStatus.GRADED.value,
                settable_count=10000,
                eggs_remaining=10000,
            )
            assert served["version"] == lot["version"], (
                "reading a lot for any role must not mutate it"
            )


class TestOptimisticConcurrency:
    """The version a client last read is the token that authorises its next write."""

    def test_the_pre_boxing_version_can_no_longer_allocate(self, api):
        """PRD 2.9: "Running the allocation waterfall over a boxed chick batch requires a
        non-optional `expected_chick_batch_version` field carrying the `version` of the
        `ChickBatch` the caller last read. A mismatch against the batch's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412) and no delivery assignment records are
        created at all. A successful run increments the batch's `version` by 1, so the same
        `expected_chick_batch_version` cannot be replayed to allocate the same chicks twice."

        Design: Corner/cross_cutting_layers/occ_allocation_requires_current_chick_batch_version
        """
        ctx = fx.vaccinated_batch_context(
            api, fertile_count=9600, hatched_count=9000, sexing=TIER_B_SEXING
        )
        stale_version = ctx["batch"]["version"]
        farm = fx.cleared_farm(
            api, code="FM1", operator_user_id="u_grower_1", capacity_chicks=20000
        )
        order = fx.confirmed_order(
            api,
            farm["id"],
            requested_chicks=5000,
            requested_placement_date="2026-08-22T00:00:00Z",
        )
        boxed = validate_success(
            api.box_chick_batch(ctx["batch"]["id"], CHICK_PROCESSOR), 200
        )
        boxed_version = boxed["version"]

        stale = api.allocate_chicks(boxed["id"], stale_version, HATCHERY_MANAGER)

        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        _rows, meta = validate_paginated(
            api.list_delivery_assignments(
                HATCHERY_MANAGER, {"chick_batch_id": boxed["id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused run created no assignment"
        after_refusal = fx.read_batch(api, boxed["id"])
        assert_chick_batch(after_refusal, unassigned_chicks=8481)
        assert after_refusal["version"] == boxed_version, (
            "a rejected allocation is not a write"
        )

        assignments = fx.run_allocation(api, boxed["id"], boxed_version)

        assert len(assignments) == 1, f"one order absorbs whole boxes, got {assignments}"
        assert_delivery_assignment(
            assignments[0],
            placement_order_id=order["id"],
            chicks_assigned=5000,
            boxes_assigned=50,
            status=AssignmentStatus.ASSIGNED.value,
        )
        final = fx.read_batch(api, boxed["id"])
        assert_chick_batch(final, unassigned_chicks=3481)
        assert final["version"] == boxed_version + 1, (
            "the served version cannot be replayed against the batch"
        )

    def test_three_writes_walk_one_lot_up_while_its_sibling_stands_still(self, api):
        """PRD 2.5: "Almost every record additionally carries `updated_at` — an ISO 8601 UTC
        timestamp with three fractional digits, refreshed on every mutation — and `version`, an
        integer that starts at 1 on creation and increments by exactly 1 on every mutation of
        that record." And: "When an operation mutates several records — and in this domain most
        operations do — every record it actually changes gets its own `updated_at` refresh and
        its own `version` increment."

        Design: Corner/cross_cutting_layers/version_increments_on_every_write_and_only_on_writes
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        flock_version = fx.read_flock(api, flock["id"])["version"]
        lot = fx.collect_lot(
            api, flock["id"], collected_at="2026-07-30T00:00:00Z", collected_count=10500
        )
        sibling = fx.collect_lot(
            api, flock["id"], collected_at="2026-07-30T06:00:00Z", collected_count=4200
        )

        assert lot["version"] == 1, "a new record starts at version 1"
        graded = validate_success(
            api.grade_egg_lot(lot["id"], f.grade_payload(), FLOCK_MANAGER), 200
        )
        interleaved = validate_success(
            api.get_egg_lot(lot["id"], INCUBATION_OPERATOR), 200
        )
        stored = validate_success(
            api.store_egg_lot(lot["id"], f.store_payload(15.0), INCUBATION_OPERATOR),
            200,
        )
        held = validate_success(api.sanitation_hold_egg_lot(lot["id"], VETERINARIAN), 200)

        assert graded["version"] == 2, "grading is the first mutation"
        assert interleaved["version"] == 2, "the interleaved read does not advance it"
        assert stored["version"] == 3, "storage is the second mutation"
        assert held["version"] == 4, "the sanitation hold is the third"
        for written in (graded, stored, held):
            assert_stamped_at(written, "updated_at", fx.CLOCK_SETUP, "EggLot")
        assert fx.read_lot(api, sibling["id"])["version"] == 1, (
            "the sibling lot is untouched by any of the first lot's writes"
        )
        assert fx.read_flock(api, flock["id"])["version"] == flock_version, (
            "grading and storing a lot bump no ancestor"
        )
        assert_egg_lot(
            held,
            status=EggLotStatus.SANITATION_HOLD.value,
            settable_count=10000,
            eggs_remaining=10000,
            sanitation_cycle_count=0,
        )


class TestImmediateCascade:
    """The response that triggers a cascade already shows the cascade's end state."""

    def test_the_condemn_response_already_shows_the_aborted_load(self, api):
        """PRD 2.7: "There is no deferred reconciliation and no eventual consistency: by the
        time the response is serialised, every dependent record the write affects has already
        moved, been recomputed, had `updated_at` refreshed and had `version` incremented." And
        PRD 3.4: "Condemning an `ALLOCATED` lot does considerably more, and the full cascade must
        be stated: every `ACTIVE` draw of that lot flips to `item_status` of `VOIDED`; each
        affected setter load has its `total_eggs_set` and `weighted_age_days` recomputed over the
        draws that remain active; and any load left with a `total_eggs_set` of 0 and still in
        `PLANNED` moves to `ABORTED` with an `abort_reason` of `EGG_LOTS_CONDEMNED` and releases
        its incubation unit's `occupancy_status` back to `FREE`."

        Design: Corner/consistency_model/cascade_visible_in_the_triggering_response
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot = fx.stored_lot(
            api,
            flock["id"],
            grade={
                "grade_a_count": 4000,
                "cracked_count": 100,
                "dirty_count": 60,
                "small_count": 40,
            },
            storage_temp_c=15.0,
            collected_at="2026-07-30T00:00:00Z",
            collected_count=4200,
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
        item = fx.draw_eggs(api, load["id"], lot["id"], 4000)

        condemned = validate_success(
            api.condemn_egg_lot(lot["id"], "SALMONELLA_SUSPECT", VETERINARIAN), 200
        )
        load_after = fx.read_load(api, load["id"])
        items_after = fx.list_items_of_load(api, load["id"])

        assert_egg_lot(
            condemned,
            status=EggLotStatus.CONDEMNED.value,
            condemned_reason="SALMONELLA_SUSPECT",
            settable_count=4000,
            eggs_remaining=0,
        )
        assert_setter_load(
            load_after,
            status=SetterLoadStatus.ABORTED.value,
            abort_reason="EGG_LOTS_CONDEMNED",
            total_eggs_set=0,
        )
        assert_incubation_unit(
            fx.read_unit(api, unit["id"]),
            occupancy_status=OccupancyStatus.FREE.value,
            sanitation_status=SanitationStatus.SANITIZED.value,
        )
        assert len(items_after) == 1, f"the draw stays for audit, got {items_after}"
        assert_setter_load_item(
            items_after[0],
            id=item["id"],
            item_status=ItemStatus.VOIDED.value,
            eggs_taken=4000,
        )
        assert_two_dp(
            items_after[0]["effective_age_days_at_set"],
            2.50,
            "effective_age_days_at_set",
        )
        assert fx.read_lot(api, lot["id"]) == condemned, (
            "a second read converges on nothing new"
        )
        assert fx.read_load(api, load["id"]) == load_after
