"""Reading records back: the stored representation, the paginated collection, the
unknown identifier, the self-referential filter, the append-only probe log, and the
junction row that ties one cooler lot to two machines.
"""

from test_helpers import (
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    NON_EXISTENT_UUID,
    VETERINARIAN,
    ApiErrorId,
    EggLotStatus,
    EnvironmentStatus,
    FlockStatus,
    ItemStatus,
    UnitType,
    assert_breeder_flock,
    assert_egg_lot,
    assert_environment_reading,
    assert_forecast_chain,
    assert_ids_in_order,
    assert_one_dp,
    assert_ordered_by,
    assert_setter_load,
    assert_setter_load_item,
    assert_three_dp,
    assert_two_dp,
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


class TestSingleRecordReads:
    """A read serves the stored record to every permitted role, or a 404.

    PRD 2.4 lets a read recompute a derived field, so the two reads are compared
    to each other as well as to the creation response.
    """

    def test_a_placed_flock_reads_back_identically_for_two_permitted_roles(self, api):
        """PRD 2.4: "Reading a single breeder flock recomputes `age_weeks` and the whole
        forecast chain against the current clock without incrementing that flock's
        `version`."

        Design: Corner/entities/get_breeder_flock_returns_stored_representation
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        created = fx.create_flock(api, program["id"])

        as_flock_manager = validate_success(
            api.get_breeder_flock(created["id"], FLOCK_MANAGER), 200
        )
        as_veterinarian = validate_success(
            api.get_breeder_flock(created["id"], VETERINARIAN), 200
        )

        assert as_flock_manager == as_veterinarian, (
            "a read serves the same stored record to every permitted role"
        )
        assert_breeder_flock(
            as_flock_manager,
            id=created["id"],
            program_id=program["id"],
            code="F1",
            house_code="H1",
            hen_count=9000,
            status=FlockStatus.PLACED.value,
            age_weeks=29,
        )
        assert as_flock_manager["hatch_date"] == created["hatch_date"]
        assert as_flock_manager["placed_at"] == created["placed_at"]
        assert as_flock_manager["version"] == 1, (
            "recomputing the forecast on read must not bump version"
        )
        assert as_flock_manager["updated_at"] == created["updated_at"], (
            "recomputing the forecast on read must not refresh updated_at"
        )
        assert_forecast_chain(
            as_flock_manager,
            age_weeks=29,
            photoperiod_hours=14.0,
            feed_grams_per_hen_day=168.0,
            production_rate_pct=82.0,
            lighting_factor=0.7900,
            nutrition_factor=1.0500,
            settable_forecast=5754,
        )

    def test_reading_an_unknown_setter_load_is_a_not_found(self, api):
        """PRD 2.8: "Where a path names more than one record — a load's draws, a load's
        environment readings, a lot's draws — identifiers are resolved strictly left to
        right, and the first identifier that does not resolve determines the 404." And: "Each
        entity has its own not-found code".

        Design: Corner/entities/get_setter_load_unknown_id_not_found
        """
        fx.set_clock(api, fx.CLOCK_SETUP)

        response = api.get_setter_load(NON_EXISTENT_UUID, INCUBATION_OPERATOR)

        validate_error(response, ApiErrorId.ERR_SETTER_LOAD_NOT_FOUND, 404)


class TestCollectionReads:
    """Windowing, totals and the declared filters on a list endpoint."""

    def test_egg_lot_pages_report_the_full_total_and_the_has_more_flag(self, api):
        """PRD 2.3: "Unless a specific endpoint says otherwise, list results are ordered by
        `created_at` ascending. Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope." And: "`limit` caps the
        number of records returned; it defaults to 10, its minimum accepted value is 1 and its
        maximum is 100."

        Design: Corner/entities/list_egg_lots_paginates_with_total_count_and_has_more
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot_ids = [
            fx.collect_lot(
                api, flock["id"], collected_at=collected_at, collected_count=count
            )["id"]
            for collected_at, count in (
                ("2026-07-29T00:00:00Z", 6000),
                ("2026-07-30T00:00:00Z", 6100),
                ("2026-07-31T00:00:00Z", 6200),
            )
        ]

        first_page, first_meta = validate_paginated(
            api.list_egg_lots(FLOCK_MANAGER, {"limit": 2, "offset": 0})
        )
        second_page, second_meta = validate_paginated(
            api.list_egg_lots(FLOCK_MANAGER, {"limit": 2, "offset": 2})
        )
        filtered, filtered_meta = validate_paginated(
            api.list_egg_lots(FLOCK_MANAGER, {"status": EggLotStatus.COLLECTED.value})
        )

        assert len(first_page) == 2, f"the window caps the page at 2 rows, got {first_page}"
        assert first_meta["limit"] == 2 and first_meta["offset"] == 0
        assert first_meta["total_count"] == 3, (
            "total_count counts the matches before the window is applied"
        )
        assert first_meta["has_more"] is True, "2 of 3 rows served leaves more to come"
        assert len(second_page) == 1, f"the tail page holds the last row, got {second_page}"
        assert second_meta["total_count"] == 3 and second_meta["offset"] == 2
        assert second_meta["has_more"] is False, "the tail page exhausts the collection"
        assert_ids_in_order(first_page + second_page, lot_ids)
        assert len(filtered) == 3, "all three lots are still COLLECTED"
        assert filtered_meta["limit"] == 10, "the default window is 10 rows"
        assert filtered_meta["total_count"] == 3 and filtered_meta["has_more"] is False
        assert_ordered_by(filtered, "created_at")

    def test_the_source_flock_filter_selects_only_the_daughter_flock(self, api):
        """PRD 3.2: "An optional `source_flock_id` records the parent-stock lineage — the
        flock this flock's own eggs came from — and is left absent for imported grandparent
        stock; this self-reference is what later lets analytics attribute performance back up
        the lineage." And PRD 2.3: "Breeder flock listings filter on `program_id`,
        `source_flock_id` and `status`."

        Design: Corner/entities/self_referential_source_flock_filter
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        parent = fx.create_flock(
            api,
            program["id"],
            code="F0",
            house_code="H0",
            hatch_date="2025-06-01T00:00:00Z",
            placed_at="2025-10-01T00:00:00Z",
            hen_count=9500,
        )
        daughter = fx.create_flock(api, program["id"], source_flock_id=parent["id"])

        by_source, by_source_meta = validate_paginated(
            api.list_breeder_flocks(FLOCK_MANAGER, {"source_flock_id": parent["id"]})
        )
        by_program, by_program_meta = validate_paginated(
            api.list_breeder_flocks(FLOCK_MANAGER, {"program_id": program["id"]})
        )

        assert by_source_meta["total_count"] == 1, (
            f"only the daughter names F0 as its parent, got {by_source}"
        )
        assert by_source[0]["id"] == daughter["id"]
        assert by_source[0]["source_flock_id"] == parent["id"]
        assert by_program_meta["total_count"] == 2, (
            "both generations belong to the same programme"
        )
        assert_ids_in_order(by_program, [parent["id"], daughter["id"]])
        assert fx.read_flock(api, parent["id"])["source_flock_id"] is None, (
            "the parent generation names no parent of its own"
        )


class TestAppendOnlyAndJunctionRows:
    """Two records with no update path of their own: the probe reading and the draw."""

    def test_probe_readings_are_append_only_and_carry_no_version(self, api):
        """PRD 2.5: "an environment reading carries only `id` and `created_at`. It has no
        `updated_at` and no `version` at all." And PRD 3.5: "The `recorded_at` must be at or
        after the load's `set_at`, must not be later than the current logical clock, and must
        be strictly after the `recorded_at` of the load's latest existing reading; all three
        violations report `ERR_TIMESTAMP_OUT_OF_RANGE`."

        Design: Corner/entities/environment_reading_is_append_only_and_immutable
        """
        ctx = fx.incubating_load_context(api, set_at="2026-08-01T18:00:00Z")
        fx.set_clock(api, "2026-08-02T06:00:00Z")

        first = validate_success(
            api.add_environment_reading(
                ctx["load"]["id"],
                f.environment_reading_payload("2026-08-01T18:00:00Z", 37.9, 55.0),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        second = validate_success(
            api.add_environment_reading(
                ctx["load"]["id"],
                f.environment_reading_payload("2026-08-01T21:00:00Z", 37.7, 54.0),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        back_dated = api.add_environment_reading(
            ctx["load"]["id"],
            f.environment_reading_payload("2026-08-01T20:00:00Z", 37.8, 55.0),
            INCUBATION_OPERATOR,
        )

        validate_error(back_dated, ApiErrorId.ERR_TIMESTAMP_OUT_OF_RANGE, 422)
        assert_environment_reading(
            first,
            setter_load_id=ctx["load"]["id"],
            recorded_at="2026-08-01T18:00:00Z",
            temp_c=37.9,
            humidity_pct=55.0,
            target_temp_c=37.8,
        )
        assert_one_dp(first["elapsed_hours"], 0.0, "elapsed_hours")
        assert_two_dp(first["abs_deviation_c"], 0.10, "abs_deviation_c")
        assert_three_dp(first["segment_degree_hours"], 0.000, "segment_degree_hours")
        assert_environment_reading(
            second, recorded_at="2026-08-01T21:00:00Z", temp_c=37.7, humidity_pct=54.0
        )
        assert_one_dp(second["elapsed_hours"], 3.0, "elapsed_hours")
        assert_two_dp(second["abs_deviation_c"], 0.10, "abs_deviation_c")
        assert_three_dp(second["segment_degree_hours"], 0.000, "segment_degree_hours")

        rows, meta = validate_paginated(
            api.list_environment_readings(ctx["load"]["id"], INCUBATION_OPERATOR)
        )
        assert meta["total_count"] == 2, (
            f"the rejected back-dated probe appends nothing, got {meta['total_count']}"
        )
        assert_ids_in_order(rows, [first["id"], second["id"]])
        assert_ordered_by(rows, "recorded_at")
        load = fx.read_load(api, ctx["load"]["id"])
        assert_setter_load(load, environment_status=EnvironmentStatus.NOMINAL.value)
        assert_three_dp(
            load["deviation_degree_hours"], 0.000, "deviation_degree_hours"
        )

    def test_one_lot_draws_into_two_loads_through_two_junction_rows(self, api):
        """PRD 3.5: "The draw is a many-to-many bridge: one lot may be drawn into several
        loads, and one load draws from several lots." And PRD 2.10: "For every egg lot,
        `settable_count` equals `eggs_remaining` plus the sum of `eggs_taken` across that
        lot's draws whose `item_status` is `ACTIVE`."

        Design: Corner/entities/setter_load_item_junction_links_lot_to_two_loads
        """
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
        profile = fx.create_profile(api)
        unit_1 = fx.create_unit(api, code="U1", unit_type=UnitType.SETTER.value)
        unit_2 = fx.create_unit(api, code="U2", unit_type=UnitType.SETTER.value)
        load_1 = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(unit_1["id"], profile["id"], "2026-08-01T18:00:00Z"),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        load_2 = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(unit_2["id"], profile["id"], "2026-08-02T18:00:00Z"),
                INCUBATION_OPERATOR,
            ),
            201,
        )

        item_1 = fx.draw_eggs(api, load_1["id"], lot["id"], 3000)
        after_first = fx.read_lot(api, lot["id"])
        item_2 = fx.draw_eggs(api, load_2["id"], lot["id"], 3000)

        assert_egg_lot(
            after_first, status=EggLotStatus.ALLOCATED.value, eggs_remaining=3200
        )
        assert_egg_lot(
            fx.read_lot(api, lot["id"]),
            status=EggLotStatus.ALLOCATED.value,
            settable_count=6200,
            eggs_remaining=200,
        )
        for item, load in ((item_1, load_1), (item_2, load_2)):
            assert_setter_load_item(
                item,
                egg_lot_id=lot["id"],
                setter_load_id=load["id"],
                eggs_taken=3000,
                item_status=ItemStatus.ACTIVE.value,
            )
            assert_two_dp(
                item["effective_age_days_at_set"], 2.50, "effective_age_days_at_set"
            )
            assert_setter_load(fx.read_load(api, load["id"]), total_eggs_set=3000)

        from_the_lot, lot_meta = validate_paginated(
            api.list_egg_lot_draws(lot["id"], HATCHERY_MANAGER)
        )
        of_load_1, load_meta = validate_paginated(
            api.list_setter_load_items(load_1["id"], HATCHERY_MANAGER)
        )
        assert lot_meta["total_count"] == 2, (
            f"the lot side of the junction shows both draws, got {from_the_lot}"
        )
        assert_ids_in_order(from_the_lot, [item_1["id"], item_2["id"]])
        assert load_meta["total_count"] == 1, (
            f"the load side shows only its own draw, got {of_load_1}"
        )
        assert of_load_1[0]["id"] == item_1["id"]
