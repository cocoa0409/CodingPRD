"""What a create call returns: the echoed input, the server-owned audit fields,
the declared default states, and the two distinct shapes of rejection.
"""

from test_helpers import (
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    BiosecurityStatus,
    Breed,
    FlockStatus,
    OccupancyStatus,
    OrderStatus,
    SanitationStatus,
    UnitType,
    assert_breeder_flock,
    assert_error_envelope,
    assert_flock_program,
    assert_forecast_chain,
    assert_freshly_created,
    assert_grower_farm,
    assert_incubation_unit,
    assert_object_envelope,
    assert_placement_order,
    assert_stamped_at,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCreateEchoesTheAuthoredRecord:
    """A 201 body is the full representation of what was stored."""

    def test_programme_creation_echoes_both_step_tables_in_order(self, api):
        """PRD 3.1: "It is created with a `code` of 1 to 40 characters that must be unique
        among programmes that have not been retired, a `breed` that is one of `ROSS_308`,
        `COBB_500` or `HUBBARD_JA87`, a `stimulation_week` between 18 and 30 inclusive
        giving the flock age in weeks at which photostimulation may begin, and two step
        tables." And: "A programme is born with `retired` set to false".

        Design: Corner/entities/create_flock_program_returns_full_representation
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        payload = f.flock_program_payload()

        response = api.create_flock_program(payload, HATCHERY_MANAGER)

        program = validate_success(response, 201)
        assert_object_envelope(response.json())
        assert_flock_program(
            program,
            code="P1",
            breed=Breed.ROSS_308.value,
            stimulation_week=21,
            retired=False,
        )
        assert [
            (step["age_weeks"], step["photoperiod_hours"])
            for step in program["lighting_steps"]
        ] == [(21, 12.0), (24, 14.0), (30, 16.0)], (
            "the lighting table is echoed in the submitted order"
        )
        assert [
            (step["age_weeks"], step["feed_grams_per_hen_day"])
            for step in program["feed_steps"]
        ] == [(21, 150.0), (26, 168.0)], (
            "the feed table is echoed in the submitted order"
        )
        assert_freshly_created(program, "FlockProgram")
        assert_stamped_at(program, "created_at", fx.CLOCK_SETUP, "FlockProgram")

    def test_new_records_start_in_their_declared_default_states(self, api):
        """PRD 3.1: "A newly registered machine starts with `sanitation_status` of `DIRTY`
        and `occupancy_status` of `FREE`, and its `sanitized_at` is null until the first
        sanitation." And PRD 3.3: "The farm starts at `biosecurity_status` of `PENDING`
        with a null `cleared_at`." And PRD 3.8: "A new order starts at `status` of
        `REQUESTED` with `allocated_chicks` of 0 and `remaining_need` equal to
        `requested_chicks`".

        Design: Corner/entities/system_defaults_applied_on_create
        """
        fx.set_clock(api, fx.CLOCK_SETUP)

        unit = fx.create_unit(api)
        farm = fx.pending_farm(api)
        order = fx.requested_order(api, farm["id"])

        assert_incubation_unit(
            unit,
            sanitation_status=SanitationStatus.DIRTY.value,
            occupancy_status=OccupancyStatus.FREE.value,
        )
        assert unit["sanitized_at"] is None, (
            "sanitized_at stays null until the first sanitation"
        )
        assert_grower_farm(farm, biosecurity_status=BiosecurityStatus.PENDING.value)
        assert farm["cleared_at"] is None, "cleared_at stays null until clearance"
        assert_placement_order(
            order,
            status=OrderStatus.REQUESTED.value,
            requested_chicks=5000,
            allocated_chicks=0,
            remaining_need=5000,
        )
        for record, entity in (
            (unit, "IncubationUnit"),
            (farm, "GrowerFarm"),
            (order, "GrowerPlacementOrder"),
        ):
            assert_freshly_created(record, entity)


class TestDerivedAndServerOwnedFields:
    """The computed block comes from the programme and the clock, never the request."""

    def test_the_forecast_chain_is_derived_on_placement_and_on_photostimulation(
        self, api
    ):
        """PRD 3.2: "Next, `photoperiod_hours` is the `photoperiod_hours` of the applicable
        entry of the programme's `lighting_steps` — the last entry whose `age_weeks` is at
        most the flock's `age_weeks`". And: "A newly placed flock has `status` of `PLACED`,
        `corrective_action_count` of 0, `late_pull_count` of 0, a null
        `egg_hold_opened_at` and a null `egg_hold_opened_by_user_id`, and its whole
        forecast chain is computed immediately."

        Design: Corner/entities/flock_computed_fields_derived_on_create_and_start_lay
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)

        placed = fx.create_flock(api, program["id"])

        assert_breeder_flock(
            placed,
            status=FlockStatus.PLACED.value,
            corrective_action_count=0,
            late_pull_count=0,
        )
        assert placed["egg_hold_opened_at"] is None
        assert placed["egg_hold_opened_by_user_id"] is None
        assert_forecast_chain(
            placed,
            age_weeks=29,
            photoperiod_hours=14.0,
            feed_grams_per_hen_day=168.0,
            production_rate_pct=82.0,
            lighting_factor=0.7900,
            nutrition_factor=1.0500,
            settable_forecast=5754,
        )

        fx.salmonella_clearance(api, placed["id"])
        in_lay = validate_success(api.start_lay(placed["id"], FLOCK_MANAGER), 200)

        assert_breeder_flock(in_lay, status=FlockStatus.IN_LAY.value)
        assert_forecast_chain(
            in_lay,
            age_weeks=29,
            photoperiod_hours=14.0,
            feed_grams_per_hen_day=168.0,
            production_rate_pct=82.0,
            lighting_factor=0.7900,
            nutrition_factor=1.0500,
            settable_forecast=5754,
        )
        assert in_lay["corrective_action_count"] == 0, (
            "no corrective action is open, so no derate applies"
        )

    def test_created_at_is_frozen_while_updated_at_and_version_move(self, api):
        """PRD 2.5: "Every record also carries `created_at`, an ISO 8601 UTC timestamp with
        three fractional digits, taken from the logical clock at creation." And: "Almost
        every record additionally carries `updated_at` — an ISO 8601 UTC timestamp with
        three fractional digits, refreshed on every mutation — and `version`, an integer
        that starts at 1 on creation and increments by exactly 1 on every mutation of that
        record."

        Design: Corner/entities/system_fields_generated_and_version_increments
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.create_flock(api, program["id"])
        assert_freshly_created(flock, "BreederFlock")
        fx.set_clock(api, "2026-08-15T09:00:00Z")

        recomputed = validate_success(
            api.recompute_forecast(flock["id"], FLOCK_MANAGER), 200
        )

        assert recomputed["id"] == flock["id"], "a write never re-mints the identifier"
        assert recomputed["created_at"] == flock["created_at"], (
            "created_at is frozen at the creation clock"
        )
        assert recomputed["version"] == 2, (
            f"the first mutation takes version to 2, got {recomputed['version']}"
        )
        assert_stamped_at(
            recomputed, "updated_at", "2026-08-15T09:00:00Z", "BreederFlock"
        )
        assert_forecast_chain(
            recomputed,
            age_weeks=31,
            photoperiod_hours=16.0,
            feed_grams_per_hen_day=168.0,
            production_rate_pct=74.0,
            lighting_factor=0.8500,
            nutrition_factor=1.0500,
            settable_forecast=5587,
        )


class TestCreationRejections:
    """Shape, count and parent-resolution failures are three different rejections."""

    def test_omitting_a_required_count_field_persists_nothing(self, api):
        """PRD 2.11: "Required body fields present, of the declared type, with every enum
        value inside its declared set — `ERR_INVALID_REQUEST` (400), on every write
        endpoint."

        Design: Corner/entities/create_breeder_flock_missing_required_field_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        payload = f.breeder_flock_payload(program["id"])
        payload.pop("hen_count")

        response = api.create_breeder_flock(payload, FLOCK_MANAGER)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        assert_error_envelope(response.json())
        _rows, meta = validate_paginated(api.list_breeder_flocks(FLOCK_MANAGER))
        assert meta["total_count"] == 0, (
            f"the rejected placement must persist nothing, got {meta['total_count']}"
        )

    def test_out_of_enum_type_and_below_minimum_capacity_are_distinct_codes(self, api):
        """PRD 2.11: "The distinction from rule 6 is semantic versus structural: an
        `eggs_taken` of 0 or −5 is `ERR_NON_POSITIVE_COUNT`, whereas an `eggs_taken` of
        `"many"` is `ERR_INVALID_REQUEST`." And PRD 3.1: "It is registered with a `code` of
        1 to 40 characters, a `unit_type` of either `SETTER` or `HATCHER`, and a
        `capacity_eggs` integer between 1000 and 200000 inclusive giving the most eggs it
        may hold for one load."

        Design: Corner/entities/create_incubation_unit_invalid_enum_and_non_positive_capacity_rejected
        """
        fx.set_clock(api, fx.CLOCK_SETUP)

        bad_enum = api.create_incubation_unit(
            f.incubation_unit_payload(unit_type="FREEZER"), HATCHERY_MANAGER
        )
        validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST, 400)

        zero_capacity = api.create_incubation_unit(
            f.incubation_unit_payload(capacity_eggs=0), HATCHERY_MANAGER
        )
        validate_error(zero_capacity, ApiErrorId.ERR_NON_POSITIVE_COUNT, 400)

        accepted = validate_success(
            api.create_incubation_unit(f.incubation_unit_payload(), HATCHERY_MANAGER), 201
        )
        assert_incubation_unit(
            accepted, unit_type=UnitType.SETTER.value, capacity_eggs=20000
        )

    def test_an_unresolvable_body_foreign_key_reports_the_parents_own_code(self, api):
        """PRD 2.8: "Foreign-key identifiers supplied in a request body are resolved after
        the path, in the order in which the fields are declared on the entity being
        created, and they use the code of the *parent* entity that failed to resolve."

        Design: Corner/entities/create_egg_lot_unknown_flock_not_found
        """
        fx.set_clock(api, fx.CLOCK_SETUP)

        response = api.create_egg_lot(
            f.egg_lot_payload(NON_EXISTENT_UUID, collected_count=6000), FLOCK_MANAGER
        )

        validate_error(response, ApiErrorId.ERR_BREEDER_FLOCK_NOT_FOUND, 404)
        _rows, meta = validate_paginated(api.list_egg_lots(FLOCK_MANAGER))
        assert meta["total_count"] == 0, (
            f"the rejected collection must persist nothing, got {meta['total_count']}"
        )
