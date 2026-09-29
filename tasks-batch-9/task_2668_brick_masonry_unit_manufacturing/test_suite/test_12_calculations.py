"""
The arithmetic of the domain: the firing gradient, the grade bands, the weighted
body chemistry, the auto-fill waterfall, the blend averages and the lead-time sum.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INSUFFICIENT_BLEND_INVENTORY
from test_helpers.test_users import (
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    PLANT_ADMIN,
    QUALITY_MANAGER,
    QUALITY_MANAGER_ID,
)


class TestFiringArithmetic:
    """
    Section 3.4 turns one reported curve into one base index per kiln run and one
    position index per car, and reads the grade off the position index.
    """

    def test_the_position_gradient_splits_one_firing_into_two_colours(self, api, clock):
        """
        Position 3 comes out at 52.18 and position 1, two positions off, at 49.81.

        Section 3.4: base_cdi is "0.62 multiplied by the quantity actual_peak_temp_c
        minus 900 divided by 10, plus 4.0 multiplied by actual_soak_hours";
        position_temp_delta_c is "the negative of 6.0 multiplied by the absolute
        difference between the car's kiln_position and that centreline"; position_cdi
        is "the already-rounded base_cdi plus 0.62 multiplied by the already-rounded
        position_temp_delta_c divided by 10"; and colour is "50.0 plus 3.2 multiplied
        by the signed difference". The lot copies fired_units from the run's
        net_green_units, colour family from the body and durability grade from the
        body's computed grade.

        Design: Corner/calculations/firing_color_development_applies_the_position_temperature_gradient
        """
        env = fx.build_two_fired_lots(api, clock=None, positions=(3, 1))
        graded = env["kiln_run"]
        assert graded["base_cdi"] == 20.68
        assert graded["firing_curve_deviation"] == 1.00
        assert graded["graded_by_user_id"] == env["plant"]["id"]

        # `position_temp_delta_c` is only ever named inside the position_cdi formula
        # as an intermediate; section 3.4 never declares it as a fired-lot attribute,
        # so the observable effect of the gradient is asserted through position_cdi.
        centre = env["lot_one"]
        assert centre["kiln_position"] == 3
        assert centre["position_cdi"] == 20.68
        assert centre["color_index"] == 52.18
        assert centre["grade"] == "ON_COLOR"
        assert centre["fired_units"] == 9600
        assert centre["color_family"] == "RED"
        assert centre["durability_grade"] == "SW"
        assert centre["source_formulation_id"] == env["formulation"]["id"]

        edge = env["lot_two"]
        assert edge["kiln_position"] == 1
        assert edge["position_cdi"] == 19.94
        assert edge["color_index"] == 49.81
        assert edge["grade"] == "ON_COLOR"
        assert centre["dye_lot_code"] and edge["dye_lot_code"]
        assert centre["dye_lot_code"] != edge["dye_lot_code"]

    def test_target_plus_six_exactly_is_salvage_and_one_hundredth_over_is_scrap(
        self, api, clock
    ):
        """
        A base of 26.00 stays sellable; 26.06 is written off against the plant.

        Section 3.4: "If position_cdi is strictly greater than the target plus 6.00,
        the grade is OVERFIRE_SCRAP", and "a position_cdi equal to the target plus
        6.00 is not overfire - it falls through and, being more than 3.00 away from
        target, becomes OFF_COLOR_SALVAGE". Only the scrap branch writes the plant's
        fired_scrap_units.

        Design: Corner/calculations/firing_grade_band_is_inclusive_at_target_plus_six
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        operator = env["operator"]
        car_two = fx.create_kiln_car(api, plant_id)
        run_edge = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        run_over = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], car_two["id"]
        )

        first = fx.create_kiln_run(
            api, plant_id, env["kiln"]["id"], env["formulation"]["id"]
        )
        first = fx.load_kiln_run(api, plant_id, first, run_edge["id"], 3)
        fx.start_kiln_run(api, plant_id, first["id"])
        graded_edge = validate_success(
            api.grade_kiln_run(first["id"], F.grade_payload(1000, 4.95), operator)
        )
        assert graded_edge["base_cdi"] == 26.00
        assert graded_edge["firing_curve_deviation"] == 6.95

        lot_edge = fx.fired_lots_of_run(api, run_edge["id"])[0]
        assert lot_edge["position_cdi"] == 26.00
        assert lot_edge["grade"] == "OFF_COLOR_SALVAGE"
        assert lot_edge["color_index"] == 69.20
        assert lot_edge["status"] == "AVAILABLE"
        assert lot_edge["available_units"] == 9600

        second = fx.create_kiln_run(
            api,
            plant_id,
            env["kiln"]["id"],
            env["formulation"]["id"],
            start_at="2026-08-07T07:00:00Z",
            end_at="2026-08-09T00:00:00Z",
        )
        second = fx.load_kiln_run(api, plant_id, second, run_over["id"], 3)
        fx.start_kiln_run(api, plant_id, second["id"])
        graded_over = validate_success(
            api.grade_kiln_run(second["id"], F.grade_payload(1001, 4.95), operator)
        )
        assert graded_over["base_cdi"] == 26.06

        lot_over = fx.fired_lots_of_run(api, run_over["id"])[0]
        assert lot_over["grade"] == "OVERFIRE_SCRAP"
        assert lot_over["color_index"] == 69.39
        assert lot_over["status"] == "SCRAP"

        plant = validate_success(api.get_plant(plant_id, PLANT_ADMIN))
        assert plant["fired_scrap_units"] == 9600


class TestBodyChemistryWeighting:
    """
    Section 3.2 weights each pit's chemistry by its own share and counts only the
    shale pits towards shale_share_pct.
    """

    def test_three_shares_summing_to_one_hundred_weight_the_body(self, api, clock):
        """
        40 / 30 / 30 over identical pits lands the absorption index at 9.90 and MW.

        Section 3.2: blend_iron_oxide_pct is "the sum over components of each
        contributing pit's iron_oxide_pct multiplied by that component's share_pct,
        divided by 100", shale_share_pct is "the exact two-decimal sum of share_pct
        over only those components whose pit has material_type SHALE", and absorption
        is "18.0 ... subtract 1.2 multiplied by blend_iron_oxide_pct, subtract 0.08
        multiplied by shale_share_pct, and add 1.5 multiplied by blend_lime_pct",
        which grades MW above 8.00 and up to 14.00.

        Design: Corner/calculations/body_blend_chemistry_weights_three_pit_shares_to_one_hundred
        """
        plant = fx.create_plant(api)
        clay_a = fx.create_clay_pit(api, plant["id"], iron_oxide_pct=6.000, lime_pct=1.000)
        clay_b = fx.create_clay_pit(api, plant["id"], iron_oxide_pct=6.000, lime_pct=1.000)
        shale_c = fx.create_shale_pit(
            api, plant["id"], iron_oxide_pct=6.000, lime_pct=1.000
        )
        body = fx.create_draft_formulation(api, plant["id"])

        after_first = validate_success(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(clay_a["id"], 40.00, body["version"]),
                BODY_ENGINEER,
            ),
        )
        assert after_first["component_share_total_pct"] == 40.00

        after_second = validate_success(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(
                    clay_b["id"], 30.00, after_first["version"]
                ),
                BODY_ENGINEER,
            ),
        )
        assert after_second["component_share_total_pct"] == 70.00

        after_third = validate_success(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(
                    shale_c["id"], 30.00, after_second["version"]
                ),
                BODY_ENGINEER,
            ),
        )
        assert after_third["component_share_total_pct"] == 100.00

        qualified = validate_success(api.qualify_formulation(body["id"], BODY_ENGINEER))
        assert qualified["blend_iron_oxide_pct"] == 6.000
        assert qualified["blend_lime_pct"] == 1.000
        assert qualified["shale_share_pct"] == 30.00
        assert qualified["absorption_index"] == 9.90
        assert qualified["computed_durability_grade"] == "MW"
        assert qualified["status"] == "QUALIFIED"


class TestAutoFillWaterfall:
    """
    Section 3.7 fills a short blend from the plant's own inventory, closest to the
    window midpoint first, and rolls the whole composition back if it cannot finish.
    """

    def test_the_buckets_are_drained_in_midpoint_distance_order(self, api, clock):
        """
        9600 at 52.18, then 9600 at 49.81, then the 2800 remainder at 53.17.

        Section 3.7: "The primary key is the absolute difference between the lot's
        color_index and the blend's target_color_index_midpoint ... ascending -
        closest to the midpoint first", and "each bucket is filled completely before
        the next is touched: from each lot the waterfall takes the lesser of the units
        still needed and that lot's available_units, appends a blend component with
        source AUTO_FILL, and reduces the shortfall accordingly". The profile is the
        units-weighted mean, and color_range_span "is the greatest lot color_index
        among the allocated components minus the least".

        Design: Corner/calculations/autofill_drains_the_bucket_closest_to_the_target_midpoint_first
        """
        env = fx.build_two_fired_lots(api, clock=None, positions=(3, 1))
        plant_id = env["plant"]["id"]
        car_three = fx.create_kiln_car(api, plant_id)
        run_three = fx.build_set_production_run(
            api,
            env["plant"],
            env["formulation"]["id"],
            car_three["id"],
            green_units_set=2900,
            green_loss_units=100,
        )
        later = fx.create_kiln_run(
            api,
            plant_id,
            env["kiln"]["id"],
            env["formulation"]["id"],
            start_at="2026-08-07T07:00:00Z",
            end_at="2026-08-09T00:00:00Z",
        )
        later = fx.load_kiln_run(api, plant_id, later, run_three["id"], 3)
        fx.start_kiln_run(api, plant_id, later["id"])
        fx.grade_kiln_run(api, plant_id, later["id"], 1045, 3.0)
        lot_three = fx.fired_lots_of_run(api, run_three["id"])[0]
        assert lot_three["color_index"] == 53.17
        assert lot_three["fired_units"] == 2800
        assert env["lot_one"]["color_index"] == 52.18
        assert env["lot_two"]["color_index"] == 49.81

        order = fx.build_assigned_order(api, requested_units=22000)
        blend = fx.create_blend(
            api,
            order["id"],
            22000,
            target_color_index_min=48.00,
            target_color_index_max=54.00,
        )
        assert blend["target_color_index_midpoint"] == 51.00

        composed = validate_success(
            api.compose_blend(blend["id"], F.compose_payload(True), BLEND_TECHNICIAN)
        )
        assert composed["allocated_units"] == 22000
        assert composed["status"] == "COMPOSED"
        assert composed["weighted_color_index"] == 51.27
        assert composed["color_range_span"] == 3.36
        assert composed["dye_lot_count"] == 3

        components = validate_success(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert [(c["fired_lot_id"], c["units"]) for c in components] == [
            (env["lot_one"]["id"], 9600),
            (env["lot_two"]["id"], 9600),
            (lot_three["id"], 2800),
        ]
        assert {c["source"] for c in components} == {"AUTO_FILL"}

        drained = validate_success(api.get_fired_lot(lot_three["id"], BLEND_TECHNICIAN))
        assert drained["available_units"] == 0
        assert drained["reserved_units"] == 2800

    def test_a_shortfall_after_filtering_rolls_the_whole_composition_back(
        self, api, clock
    ):
        """
        A quarantined lot and an off-texture lot leave 9600 eligible units against 12000.

        Section 3.7: a lot is eligible only when "its status is AVAILABLE or
        RESERVED ... its texture equals the order's texture", and "QUARANTINED and
        SCRAP lots, lots of other plants, off-family and off-texture lots,
        under-graded lots and lots outside the window are all excluded". "If the
        eligible inventory runs out before the shortfall does, the whole composition
        is rejected with ERR_INSUFFICIENT_BLEND_INVENTORY and nothing at all is
        persisted - not the auto-filled components, not the reservations."

        Design: Corner/calculations/autofill_skips_quarantined_and_off_texture_lots_and_persists_nothing_on_shortfall
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        car_b = fx.create_kiln_car(api, plant_id)
        car_c = fx.create_kiln_car(api, plant_id)
        run_a = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        run_b = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], car_b["id"]
        )
        run_c = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], car_c["id"], texture="SMOOTH"
        )
        kiln_run = fx.create_kiln_run(
            api, plant_id, env["kiln"]["id"], env["formulation"]["id"]
        )
        kiln_run = fx.load_kiln_run(api, plant_id, kiln_run, run_a["id"], 3)
        kiln_run = fx.load_kiln_run(api, plant_id, kiln_run, run_b["id"], 1)
        kiln_run = fx.load_kiln_run(api, plant_id, kiln_run, run_c["id"], 5)
        fx.start_kiln_run(api, plant_id, kiln_run["id"])
        fx.grade_kiln_run(api, plant_id, kiln_run["id"], 1040, 3.0)

        lot_a = fx.fired_lots_of_run(api, run_a["id"])[0]
        lot_b = fx.fired_lots_of_run(api, run_b["id"])[0]
        lot_c = fx.fired_lots_of_run(api, run_c["id"])[0]
        assert lot_a["color_index"] == 52.18
        assert lot_b["color_index"] == 49.81
        assert lot_c["color_index"] == 49.81
        assert lot_c["texture"] == "SMOOTH"

        held = validate_success(
            api.quarantine_fired_lot(
                lot_a["id"], F.quarantine_payload("Lime popping on the face"), QUALITY_MANAGER
            )
        )
        assert held["status"] == "QUARANTINED"

        order = fx.build_assigned_order(api, requested_units=12000)
        blend = fx.create_blend(
            api,
            order["id"],
            12000,
            target_color_index_min=48.00,
            target_color_index_max=54.00,
        )
        validate_error(
            api.compose_blend(blend["id"], F.compose_payload(True), BLEND_TECHNICIAN),
            ERR_INSUFFICIENT_BLEND_INVENTORY,
            422,
        )

        after = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert after["status"] == "DRAFT"
        assert after["allocated_units"] == 0
        assert after["weighted_color_index"] is None

        components, meta = validate_paginated(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert components == []
        assert meta["total_count"] == 0

        untouched = validate_success(api.get_fired_lot(lot_b["id"], BLEND_TECHNICIAN))
        assert untouched["available_units"] == 9600
        assert untouched["reserved_units"] == 0
        assert untouched["status"] == "AVAILABLE"


class TestBlendAggregatesAndPrecision:
    """
    Section 3.7 re-derives allocated_units after every draw and rounds the
    units-weighted colour mean exactly once, at the end.
    """

    def test_three_draws_on_one_lot_accumulate_into_one_running_total(self, api, clock):
        """
        4000, then 7000, then 9600 - and three components that were never merged.

        Section 3.7: "the blend's allocated_units is recomputed as the sum of units
        over its ALLOCATED components", dye_lot_count is "the number of distinct
        dye_lot_code values across those components", and consumption waits for
        delivery, so a fully drawn lot is still only RESERVED.

        Design: Corner/calculations/blend_allocated_units_running_total_across_three_draws_on_one_lot
        """
        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        order = fx.build_assigned_order(api, requested_units=9600)
        blend = fx.create_blend(
            api,
            order["id"],
            9600,
            target_color_index_min=48.00,
            target_color_index_max=54.00,
        )

        running = []
        for units in (4000, 3000, 2600):
            blend = validate_success(
                api.add_blend_component(
                    blend["id"],
                    F.blend_component_payload(lot["id"], units, blend["version"]),
                    BLEND_TECHNICIAN,
                )
            )
            running.append(blend["allocated_units"])
        assert running == [4000, 7000, 9600]

        drawn = validate_success(api.get_fired_lot(lot["id"], BLEND_TECHNICIAN))
        assert drawn["available_units"] == 0
        assert drawn["reserved_units"] == 9600
        assert drawn["consumed_units"] == 0
        assert drawn["status"] == "RESERVED"

        composed = validate_success(
            api.compose_blend(blend["id"], F.compose_payload(False), BLEND_TECHNICIAN)
        )
        assert composed["allocated_units"] == 9600
        assert composed["weighted_color_index"] == 52.18
        assert composed["color_range_span"] == 0.00
        assert composed["dye_lot_count"] == 1

        components = validate_success(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert [c["units"] for c in components] == [4000, 3000, 2600]

    def test_the_weighted_mean_is_rounded_once_at_the_end(self, api, clock):
        """
        9600 units at 52.18 and 2800 at 49.81 average to 51.64, not 51.65.

        Section 3.7: "sum each component's lot color_index multiplied by that
        component's units, accumulating at full precision, divide the total by
        allocated_units, and round half up to two decimal places once at the end.
        Rounding each component's product before summing, or averaging the
        per-component rounded contributions, is forbidden - both drift".

        Design: Corner/calculations/weighted_color_index_is_averaged_without_intermediate_rounding
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        car_two = fx.create_kiln_car(api, plant_id)
        big = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        small = fx.build_set_production_run(
            api,
            env["plant"],
            env["formulation"]["id"],
            car_two["id"],
            green_units_set=2900,
            green_loss_units=100,
        )
        kiln_run = fx.create_kiln_run(
            api, plant_id, env["kiln"]["id"], env["formulation"]["id"]
        )
        kiln_run = fx.load_kiln_run(api, plant_id, kiln_run, big["id"], 3)
        kiln_run = fx.load_kiln_run(api, plant_id, kiln_run, small["id"], 1)
        fx.start_kiln_run(api, plant_id, kiln_run["id"])
        fx.grade_kiln_run(api, plant_id, kiln_run["id"], 1040, 3.0)
        lot_big = fx.fired_lots_of_run(api, big["id"])[0]
        lot_small = fx.fired_lots_of_run(api, small["id"])[0]
        assert lot_big["fired_units"] == 9600
        assert lot_small["fired_units"] == 2800
        assert lot_small["color_index"] == 49.81

        order = fx.build_assigned_order(api, requested_units=12400)
        blend = fx.build_draft_blend_with_allocation(
            api,
            order,
            [(lot_big["id"], 9600), (lot_small["id"], 2800)],
            target_color_index_min=48.00,
            target_color_index_max=54.00,
        )
        composed = validate_success(
            api.compose_blend(blend["id"], F.compose_payload(False), BLEND_TECHNICIAN)
        )
        assert composed["weighted_color_index"] == 51.64
        assert composed["weighted_color_index"] != 51.65
        assert composed["color_range_span"] == 2.37
        assert composed["dye_lot_count"] == 2

        components = validate_success(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert components[0]["contribution_index"] == 500928.00
        assert components[1]["contribution_index"] == 139468.00


class TestLeadTimePromise:
    """
    Section 3.5 sums three constants and a ceiling term, and measures the promise
    from the logical clock rather than from wall-clock time.
    """

    def test_every_constant_and_the_run_out_term_land_in_the_promise(self, api, clock):
        """
        15 days standard, 50 with both flags, and 16 for one unit over a full day.

        Section 3.5: "Start from a base of 14 days. Add 28 days when is_special_order
        is true. Add 7 days when requires_panel_approval is true. Then add the run-out
        term: requested_units divided by the winning plant's
        base_capacity_green_units_per_day, rounded up to a whole day - never to the
        nearest, never down - so an order exactly equal to one day of capacity
        contributes 1 day and one unit more contributes 2." "With the clock at its
        startup default, a 12000-unit standard order at a plant rated 40000 green
        units per day promises 15 days out, at 2026-08-16T00:00:00Z; the same order
        flagged both is_special_order and requires_panel_approval promises 50 days
        out, at 2026-09-20T00:00:00Z."

        Design: Corner/calculations/order_lead_time_sums_all_three_constants_plus_the_run_out_term
        """
        env = fx.build_plant_with_assets(api, clock=None)
        assert env["plant"]["base_capacity_green_units_per_day"] == 40000

        standard = fx.build_assigned_order(api, requested_units=12000)
        assert standard["lead_time_days"] == 15
        assert standard["promised_ship_date"] == "2026-08-16T00:00:00Z"

        flagged = fx.build_assigned_order(
            api,
            requested_units=12000,
            is_special_order=True,
            requires_panel_approval=True,
        )
        assert flagged["lead_time_days"] == 50
        assert flagged["promised_ship_date"] == "2026-09-20T00:00:00Z"

        exactly_one_day = fx.build_assigned_order(api, requested_units=40000)
        assert exactly_one_day["lead_time_days"] == 15
        assert exactly_one_day["promised_ship_date"] == "2026-08-16T00:00:00Z"

        one_unit_over = fx.build_assigned_order(api, requested_units=40001)
        assert one_unit_over["lead_time_days"] == 16
        assert one_unit_over["promised_ship_date"] == "2026-08-17T00:00:00Z"


class TestDyeLotEquivalenceClass:
    """
    Section 3.6 walks the supersession chain upward from the panel's own body and
    keeps a RETIRED ancestor in the class.
    """

    def test_a_lot_fired_from_a_retired_ancestor_still_certifies(self, api, clock):
        """
        The panel names the successor body; the lot came from the retired one.

        Section 3.6: "Starting from the panel's own formulation_id, walk upward
        through each formulation's supersedes_formulation_id, collecting every
        formulation id encountered ... A RETIRED formulation stays in the class:
        retiring a body does not invalidate lots already fired from it." Certification
        then requires the lot's source_formulation_id to lie "inside the equivalence
        class", panel_delta_e - "the absolute difference between the blend's
        weighted_color_index and the panel's approved_color_index" - to be no greater
        than tolerance_delta_e, and color_range_span to be no greater than 12.00.

        Design: Corner/calculations/dye_lot_equivalence_accepts_a_lot_fired_from_a_superseded_formulation
        """
        env = fx.build_fired_lot(api, clock=None)
        first_body = env["formulation"]
        lot = env["fired_lot"]
        assert lot["source_formulation_id"] == first_body["id"]

        successor = fx.create_draft_formulation(
            api, env["plant"]["id"], supersedes_formulation_id=first_body["id"]
        )
        successor = fx.add_components(
            api,
            successor,
            [(env["clay_pit"]["id"], 50.00), (env["shale_pit"]["id"], 50.00)],
        )
        successor = fx.qualify_formulation(api, successor["id"])
        assert successor["computed_durability_grade"] == "SW"
        retired = validate_success(api.get_formulation(first_body["id"], BODY_ENGINEER))
        assert retired["status"] == "RETIRED"

        order = fx.build_assigned_order(
            api, requested_units=9600, requires_panel_approval=True
        )
        assert order["lead_time_days"] == 22

        blend = fx.build_composed_blend(api, order, [(lot["id"], 9600)])
        assert blend["weighted_color_index"] == 52.18
        assert blend["color_range_span"] == 0.00

        panel = fx.build_approved_panel(
            api,
            order["id"],
            successor["id"],
            lot["id"],
            52.00,
            tolerance_delta_e=2.00,
        )
        assert panel["status"] == "APPROVED"
        assert panel["approved_color_index"] == 52.00
        assert panel["expires_at"] == "2027-01-28T00:00:00Z"
        assert panel["pinned_dye_lot_code"] == lot["dye_lot_code"]
        assert panel["pinned_formulation_version"] == successor["version"]

        certified = validate_success(api.certify_blend(blend["id"], QUALITY_MANAGER))
        assert certified["status"] == "CERTIFIED"
        assert certified["panel_delta_e"] == 0.18
        assert certified["certified_at"] == "2026-08-01T00:00:00Z"
        assert certified["color_range_span"] == 0.00
        assert certified["certified_by_user_id"] == QUALITY_MANAGER_ID
        assert certified["certified_by_user_id"] != certified["composed_by_user_id"]
