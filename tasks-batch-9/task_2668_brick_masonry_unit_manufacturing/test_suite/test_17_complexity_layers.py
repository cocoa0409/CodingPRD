"""
The cross-cutting layers: the three optimistic-concurrency guards, and the plant
selector's four exclusion reasons with cost beating proximity.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_STALE_VERSION
from test_helpers.test_users import (
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    PLANT_ADMIN,
    SALES_REP,
)


class TestFormulationVersionGuard:
    """
    Section 2.8 makes the component append carry the version the writer saw, so a
    second blind writer is refused rather than merged.
    """

    def test_a_blind_second_append_is_refused_and_writes_no_component(self, api, clock):
        """
        Two writers hold version 1; the second append is 412 and the retry lands.

        Section 2.8: "the write is applied only when the guard equals the row's current
        version; otherwise it is rejected with ERR_STALE_VERSION (HTTP 412) and nothing
        is written." The stale append here was arithmetically fine - 50.00 plus 50.00 is
        exactly 100.00 - so only the version distinguishes the two views.

        Design: Corner/complexity_layers/appending_a_clay_pit_with_a_stale_formulation_version_is_refused_and_changes_nothing
        """
        plant = fx.create_plant(api)
        clay = fx.create_clay_pit(api, plant["id"])
        shale = fx.create_shale_pit(api, plant["id"])
        body = fx.create_draft_formulation(api, plant["id"])
        version_one = body["version"]

        first = validate_success(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(clay["id"], 50.00, version_one),
                BODY_ENGINEER,
            )
        )
        assert first["version"] != version_one

        validate_error(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(shale["id"], 50.00, version_one),
                BODY_ENGINEER,
            ),
            ERR_STALE_VERSION,
            412,
        )

        after = validate_success(api.get_formulation(body["id"], BODY_ENGINEER))
        assert after["version"] == first["version"]
        assert after["component_share_total_pct"] == 50.00
        assert len(after["components"]) == 1

        retry = validate_success(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(shale["id"], 50.00, first["version"]),
                BODY_ENGINEER,
            )
        )
        assert retry["version"] != first["version"]
        assert retry["component_share_total_pct"] == 100.00

        qualified = validate_success(api.qualify_formulation(body["id"], BODY_ENGINEER))
        assert qualified["status"] == "QUALIFIED"
        assert qualified["absorption_index"] == 8.00
        assert qualified["computed_durability_grade"] == "SW"


class TestKilnRunVersionGuard:
    """
    Loading never changes the kiln run's status, so the version is the only thing
    that can tell two concurrent loaders apart.
    """

    def test_a_stale_load_leaves_the_position_free_and_the_run_untouched(self, api, clock):
        """
        Position 4 was never occupied, so the refusal is a 412 rather than a conflict.

        Section 2.8 guards the load with `expected_kiln_run_version`, and section 3.4
        keeps the run SCHEDULED across every load, so "status can never substitute for
        the version". A refused load neither adds to `loaded_units` nor moves the
        production run out of SET.

        Design: Corner/complexity_layers/loading_a_second_car_with_a_stale_kiln_run_version_is_refused_and_the_position_stays_free
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        operator = env["operator"]
        second_car = fx.create_kiln_car(api, plant_id)
        first_run = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        second_run = fx.build_set_production_run(
            api,
            env["plant"],
            env["formulation"]["id"],
            second_car["id"],
            green_units_set=5000,
            green_loss_units=200,
        )
        kiln_run = fx.create_kiln_run(
            api, plant_id, env["kiln"]["id"], env["formulation"]["id"]
        )
        version_one = kiln_run["version"]

        loaded = validate_success(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(first_run["id"], 3, version_one),
                operator,
            )
        )
        assert loaded["status"] == "SCHEDULED"
        assert loaded["version"] != version_one

        validate_error(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(second_run["id"], 4, version_one),
                operator,
            ),
            ERR_STALE_VERSION,
            412,
        )

        after = validate_success(api.get_kiln_run(kiln_run["id"], operator))
        assert after["version"] == loaded["version"]
        assert after["loaded_units"] == 9600
        assert (
            validate_success(api.get_production_run(second_run["id"], operator))["status"]
            == "SET"
        )

        retry = validate_success(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(second_run["id"], 4, loaded["version"]),
                operator,
            )
        )
        assert retry["status"] == "SCHEDULED"
        assert retry["version"] != loaded["version"]
        assert retry["loaded_units"] == 14400
        moved = validate_success(api.get_production_run(second_run["id"], operator))
        assert moved["status"] == "LOADED"
        assert moved["kiln_position"] == 4


class TestBlendVersionGuard:
    """
    A refused allocation reserves nothing, so the lot's three-column ledger still
    reconciles after the 412.
    """

    def test_a_stale_allocation_reserves_nothing_and_three_draws_are_one_dye_lot(
        self, api, clock
    ):
        """
        5000 lands, a blind 2000 is refused, then 2000 and 2600 fill the request.

        Section 2.8 guards the allocation with `expected_blend_version`; the refused add
        was affordable and the lot had 4600 units left, so only the version separates
        the two views. Section 2.9 keeps `fired_units` equal to the sum of the three
        columns throughout, and section 3.7 counts "the number of distinct dye_lot_code
        values", which is 1 for three draws on one lot.

        Design: Corner/complexity_layers/adding_blend_units_with_a_stale_blend_version_is_refused_and_reserves_nothing
        """
        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        order = fx.build_assigned_order(api, requested_units=9600)
        blend = fx.create_blend(api, order["id"], 9600)
        version_one = blend["version"]

        first = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 5000, version_one),
                BLEND_TECHNICIAN,
            )
        )
        assert first["version"] != version_one

        validate_error(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 2000, version_one),
                BLEND_TECHNICIAN,
            ),
            ERR_STALE_VERSION,
            412,
        )

        after = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert after["version"] == first["version"]
        assert after["allocated_units"] == 5000
        assert after["status"] == "DRAFT"

        held = validate_success(api.get_fired_lot(lot["id"], BLEND_TECHNICIAN))
        assert held["reserved_units"] == 5000
        assert held["available_units"] == 4600
        assert held["consumed_units"] == 0
        assert held["fired_units"] == 9600

        second = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 2000, first["version"]),
                BLEND_TECHNICIAN,
            )
        )
        assert second["version"] != first["version"]
        third = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 2600, second["version"]),
                BLEND_TECHNICIAN,
            )
        )
        assert third["version"] != second["version"]

        composed = validate_success(
            api.compose_blend(blend["id"], F.compose_payload(False), BLEND_TECHNICIAN)
        )
        assert composed["allocated_units"] == 9600
        assert composed["weighted_color_index"] == 52.18
        assert composed["color_range_span"] == 0.00
        assert composed["dye_lot_count"] == 1


def _sw_plant(api, grid_x, grid_y, rate, **plant_overrides):
    """A plant whose only body is 100 percent shale, which absorbs 5.20 and grades SW."""
    plant = fx.create_plant(
        api,
        grid_x=grid_x,
        grid_y=grid_y,
        freight_rate_cents_per_ton_mile=rate,
        **plant_overrides,
    )
    shale = fx.create_shale_pit(api, plant["id"])
    body = fx.build_qualified_formulation(api, plant["id"], [(shale["id"], 100.00)])
    return plant, body


class TestPlantSelectorPolicy:
    """
    Section 3.5 builds an eligible pool on four independent conditions and then
    ranks the survivors on quoted freight, not on distance.
    """

    def test_four_exclusions_then_the_cheapest_haul_beats_the_nearest_plant(
        self, api, clock
    ):
        """
        Six plants, four excluded, and a 60-mile winner beats a 10-mile rival.

        Section 3.5: a plant is eligible only when it is ACTIVE, within its own market
        radius of the jobsite, carrying "the order's unloading_equipment_required ...
        in that plant's unloading_equipment_available", and holding a QUALIFIED body in
        the right colour family whose grade "ranks at least as high as the order's
        required durability_grade". The survivors are then ranked on the estimated total
        freight in whole cents, and the run-out term of the promise reads "the winning
        plant's base_capacity_green_units_per_day".

        Design: Corner/complexity_layers/the_selector_rejects_four_plants_for_four_different_reasons_and_the_cheapest_haul_beats_the_nearest
        """
        equip_short, equip_body = _sw_plant(
            api,
            0,
            0,
            42,
            unloading_equipment_available=["CUSTOMER_FORKLIFT", "CRANE"],
        )
        assert equip_body["absorption_index"] == 5.20
        assert equip_body["computed_durability_grade"] == "SW"

        draft_only = fx.create_plant(
            api, grid_x=10, grid_y=10, freight_rate_cents_per_ton_mile=20
        )
        draft_shale = fx.create_shale_pit(api, draft_only["id"])
        draft_body = fx.create_draft_formulation(api, draft_only["id"])
        draft_body = fx.add_components(api, draft_body, [(draft_shale["id"], 100.00)])
        assert draft_body["status"] == "DRAFT"

        moderate = fx.create_plant(
            api, grid_x=20, grid_y=20, freight_rate_cents_per_ton_mile=30
        )
        moderate_clay = fx.create_clay_pit(api, moderate["id"])
        moderate_body = fx.build_qualified_formulation(
            api, moderate["id"], [(moderate_clay["id"], 100.00)]
        )
        assert moderate_body["absorption_index"] == 10.80
        assert moderate_body["computed_durability_grade"] == "MW"

        near, _ = _sw_plant(api, 25, 25, 300)
        far, _ = _sw_plant(api, 0, 60, 42, base_capacity_green_units_per_day=4000)
        idled, idled_body = _sw_plant(api, 30, 30, 10)
        assert validate_success(api.idle_plant(idled["id"], PLANT_ADMIN))["status"] == "IDLED"
        # Section 3.9 hop 2: a formulation whose pit hop 1 suspended moves
        # "QUALIFIED -> DRAFT", so the idled plant holds no QUALIFIED body and is
        # excluded from the eligible pool. RETIRED only ever comes from supersession.
        assert (
            validate_success(api.get_formulation(idled_body["id"], BODY_ENGINEER))["status"]
            == "DRAFT"
        )

        order = fx.create_order(api, requested_units=9600)
        assigned = validate_success(api.assign_plant(order["id"], SALES_REP))

        assert assigned["plant_id"] == far["id"]
        assert assigned["plant_id"] != near["id"]
        assert assigned["plant_id"] != equip_short["id"]
        assert assigned["distance_miles"] == 60
        assert assigned["estimated_billable_tons"] == 21.60
        assert assigned["estimated_base_freight_cents"] == 54432
        assert assigned["estimated_fuel_surcharge_cents"] == 2449
        assert assigned["estimated_freight_cents"] == 56881
        assert assigned["lead_time_days"] == 17
        assert assigned["promised_ship_date"] == "2026-08-18T00:00:00Z"
        assert assigned["fulfillment_status"] == "ASSIGNED"
        assert assigned["freight_status"] == "ESTIMATED"
