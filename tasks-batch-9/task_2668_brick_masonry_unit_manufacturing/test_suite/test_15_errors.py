"""
Error codes reached at the position in the ladder where they actually fire: dead
ids, code collisions, refused transitions, and the arithmetic guards.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BAND_COUNT_INSUFFICIENT,
    ERR_BLEND_NOT_DRAFT,
    ERR_BLEND_NOT_FOUND,
    ERR_CLAY_PIT_SUSPENDED,
    ERR_COLOR_RANGE_SPAN_EXCEEDED,
    ERR_DUPLICATE_CODE,
    ERR_FIRED_LOT_NOT_FOUND,
    ERR_FIRED_LOT_UNAVAILABLE,
    ERR_INVALID_KILN_POSITION,
    ERR_KILN_CAR_CAPACITY_EXCEEDED,
    ERR_KILN_CAR_NOT_FOUND,
    ERR_KILN_NOT_FOUND,
    ERR_KILN_POSITION_OCCUPIED,
    ERR_KILN_RUN_NOT_FOUND,
    ERR_KILN_RUN_STATE_INVALID,
    ERR_LOT_ATTRIBUTE_MISMATCH,
    ERR_ORDER_NOT_FOUND,
    ERR_PANEL_TOLERANCE_EXCEEDED,
    ERR_PRODUCTION_RUN_NOT_FOUND,
    ERR_SAMPLE_PANEL_NOT_FOUND,
)
from test_helpers.test_users import (
    ARCHITECT_REVIEWER,
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    LOGISTICS_COORDINATOR,
    PLANT_ADMIN,
    QUALITY_MANAGER,
    SALES_REP,
)


class TestDeadIdsReachEveryNotFoundCode:
    """
    Section 2.3 resolves the path before the body and the outermost path segment
    before any nested collection.
    """

    def test_each_entity_reports_its_own_not_found_code(self, api, clock):
        """
        Six reads, one nested collection and two body foreign keys, all 404.

        Section 5 gives every entity its own not-found code at HTTP 404, and section
        2.5 resolves "the path parameters, outermost first" before the body, so a
        nested collection under a dead parent reports the parent's 404 rather than an
        empty page. On the two creates the plant and the formulation both resolve, so
        only the equipment id is at fault - and an unresolvable kiln_id cannot yield
        an owning plant, so the scope check never runs.

        Design: Corner/errors/every_remaining_entity_not_found_code_is_reachable_from_a_dead_id
        """
        env = fx.build_plant_with_assets(api, clock=None)
        operator = env["operator"]

        validate_error(
            api.get_production_run(NON_EXISTENT_UUID, PLANT_ADMIN),
            ERR_PRODUCTION_RUN_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_kiln_run(NON_EXISTENT_UUID, PLANT_ADMIN), ERR_KILN_RUN_NOT_FOUND, 404
        )
        validate_error(
            api.get_fired_lot(NON_EXISTENT_UUID, PLANT_ADMIN), ERR_FIRED_LOT_NOT_FOUND, 404
        )
        validate_error(api.get_order(NON_EXISTENT_UUID, SALES_REP), ERR_ORDER_NOT_FOUND, 404)
        validate_error(
            api.get_blend(NON_EXISTENT_UUID, BLEND_TECHNICIAN), ERR_BLEND_NOT_FOUND, 404
        )
        validate_error(
            api.get_sample_panel(NON_EXISTENT_UUID, ARCHITECT_REVIEWER),
            ERR_SAMPLE_PANEL_NOT_FOUND,
            404,
        )
        nested = validate_error(
            api.list_fired_lot_blend_components(NON_EXISTENT_UUID, BLEND_TECHNICIAN),
            ERR_FIRED_LOT_NOT_FOUND,
            404,
        )
        assert isinstance(nested["message"], str) and nested["message"]

        validate_error(
            api.create_production_run(
                F.production_run_payload(
                    env["plant"]["id"], env["formulation"]["id"], NON_EXISTENT_UUID
                ),
                operator,
            ),
            ERR_KILN_CAR_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_kiln_run(
                F.kiln_run_payload(NON_EXISTENT_UUID, env["formulation"]["id"]), operator
            ),
            ERR_KILN_NOT_FOUND,
            404,
        )


class TestCodeUniquenessScopes:
    """
    Section 2.2 makes plant_code global and pit_name unique only inside its plant.
    """

    def test_a_plant_code_collides_globally_while_a_pit_name_collides_per_plant(
        self, api, clock
    ):
        """
        The same pit_name is legal at a second plant; the same plant_code never is.

        Section 2.2: "plant_code, formulation_code, order_code, blend_code and
        panel_code are unique across the whole system", while "pit_name, kiln_code and
        car_code are unique within their owning plant, so two plants may each have a
        car called the same thing. ... Any violation of any of these scopes is
        reported as ERR_DUPLICATE_CODE (HTTP 409)." A different material_type does not
        make it a different pit.

        Design: Corner/errors/duplicate_code_scope_is_global_for_plants_and_per_plant_for_pit_names
        """
        first = fx.create_plant(api)
        pit = fx.create_clay_pit(api, first["id"], pit_name="PIT-CLAY-A")

        validate_error(
            api.create_plant(
                F.plant_payload(plant_code=first["plant_code"]), PLANT_ADMIN
            ),
            ERR_DUPLICATE_CODE,
            409,
        )
        validate_error(
            api.create_clay_pit(
                first["id"],
                F.shale_pit_payload(pit_name="PIT-CLAY-A"),
                PLANT_ADMIN,
            ),
            ERR_DUPLICATE_CODE,
            409,
        )

        second = validate_success(api.create_plant(F.plant_payload(), PLANT_ADMIN), 201)
        twin = validate_success(
            api.create_clay_pit(
                second["id"], F.clay_pit_payload(pit_name="PIT-CLAY-A"), PLANT_ADMIN
            ),
            201,
        )
        assert twin["pit_name"] == pit["pit_name"]
        assert twin["id"] != pit["id"]

        plants, plants_meta = validate_paginated(api.list_plants(PLANT_ADMIN))
        assert plants_meta["total_count"] == 2
        pits, pits_meta = validate_paginated(api.list_clay_pits(first["id"], PLANT_ADMIN))
        assert pits_meta["total_count"] == 1


class TestKilnRunStateInvalidPositions:
    """
    Section 3.4 refuses a start with an empty kiln, a grade before firing and a
    second start, all under one code.
    """

    def test_the_same_code_covers_empty_start_early_grade_and_double_start(
        self, api, clock
    ):
        """
        Three refusals around one kiln run, and the run is still FIRING and ungraded.

        Section 3.4: starting a firing requires "at least one car loaded", grading
        requires the run to be FIRING, and the SCHEDULED to FIRING move is not
        idempotent - each violation is ERR_KILN_RUN_STATE_INVALID at HTTP 409. The
        firing arithmetic runs only at grading, so `base_cdi` stays null throughout.

        Design: Corner/errors/kiln_run_state_invalid_covers_start_without_a_car_grade_before_firing_and_double_start
        """
        env = fx.build_plant_with_assets(api, clock=None)
        operator = env["operator"]
        kiln_run = fx.create_kiln_run(
            api, env["plant"]["id"], env["kiln"]["id"], env["formulation"]["id"]
        )
        assert kiln_run["status"] == "SCHEDULED"
        assert kiln_run["loaded_units"] == 0

        validate_error(
            api.start_kiln_run(kiln_run["id"], operator), ERR_KILN_RUN_STATE_INVALID, 409
        )
        validate_error(
            api.grade_kiln_run(kiln_run["id"], F.grade_payload(1040, 3.0), operator),
            ERR_KILN_RUN_STATE_INVALID,
            409,
        )

        run = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        loaded = validate_success(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(run["id"], 3, kiln_run["version"]),
                operator,
            )
        )
        assert loaded["loaded_units"] == 9600

        firing = validate_success(api.start_kiln_run(kiln_run["id"], operator))
        assert firing["status"] == "FIRING"

        validate_error(
            api.start_kiln_run(kiln_run["id"], operator), ERR_KILN_RUN_STATE_INVALID, 409
        )

        after = validate_success(api.get_kiln_run(kiln_run["id"], operator))
        assert after["status"] == "FIRING"
        assert after["base_cdi"] is None


class TestLoadingArithmeticAndPositionGuards:
    """
    Section 3.3 caps a set by its car, and section 3.4 caps the position by the
    kiln's own position count and by what is already sitting in it.
    """

    def test_capacity_range_and_occupancy_each_refuse_one_load(self, api, clock):
        """
        A 5000-unit car will not take 6000; position 6 does not exist; position 3 is taken.

        Section 3.3 rejects a set larger than the car's `capacity_green_units` with
        ERR_KILN_CAR_CAPACITY_EXCEEDED, and section 3.4 requires "a kiln_position
        between 1 and the kiln's position_count inclusive
        (ERR_INVALID_KILN_POSITION)" that is "not already occupied on this kiln run
        (ERR_KILN_POSITION_OCCUPIED)". `loaded_units` accumulates the loaded runs'
        `net_green_units`, and a refused load leaves the version alone, so the same
        `expected_kiln_run_version` still opens the next attempt.

        Design: Corner/errors/kiln_loading_rejects_oversized_sets_out_of_range_positions_and_occupied_positions
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        operator = env["operator"]
        small_car = fx.create_kiln_car(api, plant_id, capacity_green_units=5000)
        assert env["kiln"]["position_count"] == 5

        validate_error(
            api.create_production_run(
                F.production_run_payload(
                    plant_id,
                    env["formulation"]["id"],
                    small_car["id"],
                    green_units_set=6000,
                ),
                operator,
            ),
            ERR_KILN_CAR_CAPACITY_EXCEEDED,
            422,
        )

        first_run = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        assert first_run["net_green_units"] == 9600
        kiln_run = fx.create_kiln_run(
            api, plant_id, env["kiln"]["id"], env["formulation"]["id"]
        )
        version_one = kiln_run["version"]

        validate_error(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(first_run["id"], 6, version_one),
                operator,
            ),
            ERR_INVALID_KILN_POSITION,
            422,
        )

        loaded_one = validate_success(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(first_run["id"], 3, version_one),
                operator,
            )
        )
        assert loaded_one["loaded_units"] == 9600
        assert loaded_one["version"] == version_one + 1

        second_run = fx.build_set_production_run(
            api,
            env["plant"],
            env["formulation"]["id"],
            small_car["id"],
            green_units_set=4000,
            green_loss_units=100,
        )
        assert second_run["net_green_units"] == 3900

        validate_error(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(second_run["id"], 3, loaded_one["version"]),
                operator,
            ),
            ERR_KILN_POSITION_OCCUPIED,
            409,
        )

        loaded_two = validate_success(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(second_run["id"], 4, loaded_one["version"]),
                operator,
            )
        )
        assert loaded_two["loaded_units"] == 13500
        assert loaded_two["version"] == loaded_one["version"] + 1

        runs, meta = validate_paginated(
            api.list_production_runs(operator, params={"kiln_run_id": kiln_run["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["status"] for row in runs} == {"LOADED"}
        assert sorted(row["kiln_position"] for row in runs) == [3, 4]


class TestDepletedPitBlocksQualificationOnly:
    """
    Section 3.2 gates qualification on pit status, while the append that names the
    same pit is still allowed.
    """

    def test_a_pit_drained_to_exactly_zero_blocks_the_next_qualification(
        self, api, clock
    ):
        """
        One 5000-unit run takes a 16.00-ton reserve to 0.00, which is DEPLETED.

        Section 3.1: "A pit whose available_tons reaches exactly 0.00 as the result of
        a clay commitment moves OPEN to DEPLETED; the boundary is exact." Section 3.2:
        "A contributing pit that is SUSPENDED or DEPLETED blocks qualification with
        ERR_CLAY_PIT_SUSPENDED", at HTTP 409 per section 5 - and the plant is still
        ACTIVE, so the plant-idled code cannot be the answer.

        Design: Corner/errors/qualifying_against_a_depleted_pit_returns_clay_pit_suspended_while_the_plant_is_still_active
        """
        plant = fx.create_plant(api)
        pit = fx.create_clay_pit(api, plant["id"], proven_reserve_tons=16.00)
        assert pit["available_tons"] == 16.00
        assert pit["status"] == "OPEN"
        car = fx.create_kiln_car(api, plant["id"])
        first = fx.build_qualified_formulation(api, plant["id"], [(pit["id"], 100.00)])
        assert first["status"] == "QUALIFIED"
        assert first["absorption_index"] == 10.80
        assert first["computed_durability_grade"] == "MW"

        operator = fx.make_plant_operator_headers(plant["id"])
        run = validate_success(
            api.create_production_run(
                F.production_run_payload(
                    plant["id"], first["id"], car["id"], green_units_set=5000
                ),
                operator,
            ),
            201,
        )
        assert run["clay_tons_committed"] == 16.00

        drained = validate_success(api.list_clay_pits(plant["id"], PLANT_ADMIN))[0]
        assert drained["available_tons"] == 0.00
        assert drained["committed_tons"] == 16.00
        assert drained["status"] == "DEPLETED"

        second = fx.create_draft_formulation(api, plant["id"])
        second = fx.add_components(api, second, [(pit["id"], 100.00)])
        assert second["component_share_total_pct"] == 100.00

        validate_error(
            api.qualify_formulation(second["id"], BODY_ENGINEER),
            ERR_CLAY_PIT_SUSPENDED,
            409,
        )

        assert validate_success(api.get_plant(plant["id"], PLANT_ADMIN))["status"] == "ACTIVE"
        after = validate_success(api.get_formulation(second["id"], BODY_ENGINEER))
        assert after["status"] == "DRAFT"
        assert after["qualified_at"] is None
        assert after["version"] == second["version"]


def _extra_lot(
    api,
    env,
    car,
    green_units_set,
    green_loss_units,
    texture,
    peak,
    soak,
    start_at,
    end_at,
):
    """Fire one more lot at the centre position of the same kiln, in its own window."""
    run = fx.build_set_production_run(
        api,
        env["plant"],
        env["formulation"]["id"],
        car["id"],
        green_units_set=green_units_set,
        green_loss_units=green_loss_units,
        texture=texture,
    )
    kiln_run = fx.create_kiln_run(
        api,
        env["plant"]["id"],
        env["kiln"]["id"],
        env["formulation"]["id"],
        start_at=start_at,
        end_at=end_at,
    )
    kiln_run = fx.load_kiln_run(api, env["plant"]["id"], kiln_run, run["id"], 3)
    fx.start_kiln_run(api, env["plant"]["id"], kiln_run["id"])
    fx.grade_kiln_run(api, env["plant"]["id"], kiln_run["id"], peak, soak)
    return fx.fired_lots_of_run(api, run["id"])[0]


class TestManualAllocationGuards:
    """
    Section 3.7 checks the lot's own availability and attributes before the blend's
    aggregate rules, and freezes the component list once the blend is composed.
    """

    def test_short_lots_wrong_texture_and_a_composed_blend_are_all_refused(
        self, api, clock
    ):
        """
        12000 against 9600 available, a SMOOTH lot on a WIRE_CUT order, then a frozen blend.

        Section 3.7: the lot "must have available_units at least the requested units
        (ERR_FIRED_LOT_UNAVAILABLE)" - checked ahead of the blend's own
        over-allocation rule - and "its color_family and texture must equal the
        order's (ERR_LOT_ATTRIBUTE_MISMATCH)". Components may be appended "while the
        blend is DRAFT ... otherwise ERR_BLEND_NOT_DRAFT", and compose demands DRAFT
        too, so it is not idempotent.

        Design: Corner/errors/manual_blend_component_rejects_short_lots_wrong_texture_and_a_composed_blend
        """
        env = fx.build_fired_lot(api, clock=None)
        wire_cut = env["fired_lot"]
        second_car = fx.create_kiln_car(api, env["plant"]["id"])
        smooth = _extra_lot(
            api,
            env,
            second_car,
            5000,
            200,
            "SMOOTH",
            1040,
            3.0,
            "2026-08-08T00:00:00Z",
            "2026-08-10T00:00:00Z",
        )
        assert wire_cut["available_units"] == 9600
        assert wire_cut["texture"] == "WIRE_CUT"
        assert smooth["available_units"] == 4800
        assert smooth["texture"] == "SMOOTH"
        assert smooth["color_index"] == 52.18
        assert smooth["grade"] == "ON_COLOR"

        order = fx.build_assigned_order(api, requested_units=9600)
        blend = fx.create_blend(api, order["id"], 9600)
        version_one = blend["version"]

        validate_error(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(wire_cut["id"], 12000, version_one),
                BLEND_TECHNICIAN,
            ),
            ERR_FIRED_LOT_UNAVAILABLE,
            409,
        )
        validate_error(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(smooth["id"], 4000, version_one),
                BLEND_TECHNICIAN,
            ),
            ERR_LOT_ATTRIBUTE_MISMATCH,
            422,
        )

        allocated = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(wire_cut["id"], 9600, version_one),
                BLEND_TECHNICIAN,
            )
        )
        assert allocated["allocated_units"] == 9600
        assert allocated["version"] == version_one + 1

        composed = validate_success(
            api.compose_blend(blend["id"], F.compose_payload(False), BLEND_TECHNICIAN)
        )
        assert composed["status"] == "COMPOSED"
        assert composed["version"] == allocated["version"] + 1

        validate_error(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(smooth["id"], 100, composed["version"]),
                BLEND_TECHNICIAN,
            ),
            ERR_BLEND_NOT_DRAFT,
            409,
        )
        validate_error(
            api.compose_blend(blend["id"], F.compose_payload(False), BLEND_TECHNICIAN),
            ERR_BLEND_NOT_DRAFT,
            409,
        )

        components, meta = validate_paginated(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert meta["total_count"] == 1
        assert {c["status"] for c in components} == {"ALLOCATED"}
        assert validate_success(api.get_fired_lot(smooth["id"], BLEND_TECHNICIAN))[
            "reserved_units"
        ] == 0


class TestPanelToleranceAtCertification:
    """
    Section 3.7 compares the shipped colour against the panel the architect signed
    off, and a panel from the right formulation can still be missed on colour.
    """

    def test_a_blend_twelve_points_off_the_approved_panel_is_refused(self, api, clock):
        """
        A panel approved at 40.00 will not accept a 52.18 blend inside a 1.00 tolerance.

        Section 3.7: `panel_delta_e` is "the absolute difference between the blend's
        weighted_color_index and the panel's approved_color_index", and it "must not
        exceed the panel's tolerance_delta_e, or the certification is rejected with
        ERR_PANEL_TOLERANCE_EXCEEDED". The allocated lot was fired from the panel's own
        formulation, so the dye-lot closure check passes first.

        Design: Corner/errors/certify_rejects_a_blend_whose_shipped_color_misses_the_approved_panel
        """
        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        order = fx.build_assigned_order(api, requires_panel_approval=True)
        panel = fx.build_approved_panel(
            api, order["id"], env["formulation"]["id"], lot["id"], 40.00
        )
        assert panel["status"] == "APPROVED"
        assert panel["approved_color_index"] == 40.00
        assert panel["tolerance_delta_e"] == 1.00

        blend = fx.build_composed_blend(api, order, [(lot["id"], 9600)])
        assert blend["weighted_color_index"] == 52.18
        assert lot["source_formulation_id"] == env["formulation"]["id"]

        validate_error(
            api.certify_blend(blend["id"], QUALITY_MANAGER),
            ERR_PANEL_TOLERANCE_EXCEEDED,
            422,
        )

        after = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert after["status"] == "COMPOSED"
        assert after["certified_at"] is None
        assert after["certified_by_user_id"] is None


class TestColorRangeSpanCeiling:
    """
    Section 3.7 puts a hard ceiling on the spread between the palest and the
    deepest dye lot in one shipment, independent of the blend's own target window.
    """

    def test_two_in_range_lots_nineteen_points_apart_cannot_be_composed(self, api, clock):
        """
        59.60 with 40.40 spans 19.20, over the 12.00 ceiling even though both are in range.

        Section 3.7: "color_range_span is the difference between the highest and the
        lowest color_index_at_allocation over the allocated components ... if the span
        strictly exceeds BLEND_SPAN_CEILING 12.00, the compose is rejected with
        ERR_COLOR_RANGE_SPAN_EXCEEDED and no colour profile is written." Section 3.4
        puts a 1000 C firing soaked 4.2 hours at a base CDI of 23.00 - the +3.00 edge
        of the ON_COLOR band - and a 2.7 hour soak at 17.00, the -3.00 edge. The failed
        compose leaves the components allocated so the technician can drop one lot.

        Design: Corner/errors/compose_rejects_a_blend_whose_dye_lot_spread_exceeds_the_span_ceiling
        """
        env = fx.build_plant_with_assets(api, clock=None)
        second_car = fx.create_kiln_car(api, env["plant"]["id"])
        pale_end = _extra_lot(
            api,
            env,
            env["kiln_car"],
            10000,
            400,
            "WIRE_CUT",
            1000,
            4.2,
            "2026-08-05T00:00:00Z",
            "2026-08-07T00:00:00Z",
        )
        deep_end = _extra_lot(
            api,
            env,
            second_car,
            5000,
            200,
            "WIRE_CUT",
            1000,
            2.7,
            "2026-08-08T00:00:00Z",
            "2026-08-10T00:00:00Z",
        )
        assert pale_end["color_index"] == 59.60
        assert pale_end["grade"] == "ON_COLOR"
        assert pale_end["fired_units"] == 9600
        assert deep_end["color_index"] == 40.40
        assert deep_end["grade"] == "ON_COLOR"
        assert deep_end["fired_units"] == 4800

        order = fx.build_assigned_order(api, requested_units=14400)
        blend = fx.build_draft_blend_with_allocation(
            api,
            order,
            [(pale_end["id"], 9600), (deep_end["id"], 4800)],
            target_color_index_min=40.00,
            target_color_index_max=60.00,
        )
        assert blend["allocated_units"] == 14400

        validate_error(
            api.compose_blend(blend["id"], F.compose_payload(False), BLEND_TECHNICIAN),
            ERR_COLOR_RANGE_SPAN_EXCEEDED,
            422,
        )

        after = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert after["status"] == "DRAFT"
        assert after["weighted_color_index"] is None
        assert after["color_range_span"] is None
        assert after["allocated_units"] == 14400

        components = validate_success(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN, params={"status": "ALLOCATED"})
        )
        assert len(components) == 2


class TestBandingCoversThePallets:
    """
    Section 3.8 needs at least one band per pallet, and the comparison is inclusive.
    """

    def test_nineteen_bands_cannot_secure_twenty_pallets(self, api, clock):
        """
        20 pallets with 19 bands is refused; 20 with 20 bills 22.23 tons for 58541 cents.

        Section 3.8: "each pallet needs at least one band, so band_count must be at
        least pallet_count, or the request is rejected with
        ERR_BAND_COUNT_INSUFFICIENT", while 20 pallets at 500 units each already cover
        the 9600 allocated. The final weight adds "60 pounds of pallet tare for each
        pallet, plus the banding weight for each band ... plus 4.5 pounds for each of
        the blend's allocated_units", and the rejected attempt writes nothing.

        Design: Corner/errors/package_requires_at_least_one_band_per_pallet
        """
        env = fx.build_fired_lot(api, clock=None)
        order = fx.build_assigned_order(api, requested_units=9600)
        blend = fx.build_certified_blend(api, order, [(env["fired_lot"]["id"], 9600)])
        assert blend["status"] == "CERTIFIED"
        assert order["estimated_freight_cents"] == 56881

        validate_error(
            api.package_order(order["id"], F.package_payload(20, 19), LOGISTICS_COORDINATOR),
            ERR_BAND_COUNT_INSUFFICIENT,
            422,
        )

        midway = validate_success(api.get_order(order["id"], LOGISTICS_COORDINATOR))
        assert midway["fulfillment_status"] == "IN_BLENDING"
        assert midway["pallet_count"] is None
        assert midway["final_freight_cents"] is None

        packaged = validate_success(
            api.package_order(order["id"], F.package_payload(20, 20), LOGISTICS_COORDINATOR)
        )
        assert packaged["fulfillment_status"] == "PACKAGED"
        assert packaged["final_billable_tons"] == 22.23
        assert packaged["final_base_freight_cents"] == 56020
        assert packaged["final_fuel_surcharge_cents"] == 2521
        assert packaged["final_freight_cents"] == 58541
        assert packaged["freight_variance_cents"] == 1660
