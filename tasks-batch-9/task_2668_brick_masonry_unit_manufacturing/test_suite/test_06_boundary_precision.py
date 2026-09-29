"""
Boundaries that are inclusive on one side only, and figures whose third decimal
decides which side of the boundary they land on.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NO_PLANT_IN_MARKET_RADIUS
from test_helpers.test_users import BODY_ENGINEER, SALES_REP


def _two_body_plant(api, second_clay_iron_oxide_pct):
    """One plant, one shale pit, and two clay pits differing only in iron oxide."""
    plant = fx.create_plant(api)
    clay_a = fx.create_clay_pit(api, plant["id"], iron_oxide_pct=7.500, lime_pct=1.200)
    shale_b = fx.create_shale_pit(api, plant["id"], iron_oxide_pct=5.000, lime_pct=0.800)
    clay_c = fx.create_clay_pit(
        api, plant["id"], iron_oxide_pct=second_clay_iron_oxide_pct, lime_pct=1.200
    )
    first = fx.create_draft_formulation(api, plant["id"])
    fx.add_components(api, first, [(clay_a["id"], 50.00), (shale_b["id"], 50.00)])
    second = fx.create_draft_formulation(api, plant["id"])
    fx.add_components(api, second, [(clay_c["id"], 50.00), (shale_b["id"], 50.00)])
    return {"plant": plant, "first": first, "second": second}


class TestAbsorptionIndexDurabilityBoundary:
    """
    Section 3.2: "computed_durability_grade is then read off absorption_index in
    this pinned order with both bounds inclusive: an index of 8.00 or less grades
    SW; otherwise an index of 14.00 or less grades MW; otherwise the body grades
    NW."
    """

    def test_eight_exactly_grades_sw_while_eight_point_zero_six_grades_mw(
        self, api, clock
    ):
        """
        A 0.100 difference in one pit's iron oxide splits SW from MW.

        Section 3.2: absorption is "18.0" less "1.2 multiplied by
        blend_iron_oxide_pct", less "0.08 multiplied by shale_share_pct", plus "1.5
        multiplied by blend_lime_pct". At 6.250 iron, 50.00 shale share and 1.000
        lime that is exactly 8.00, which "8.00 or less grades SW"; at 6.200 iron it
        is 8.06, which falls through to MW. The same section notes qualification
        "re-runs the chemistry", so the grade is only stamped, never blocked.

        Design: Difficulty/boundary_precision_check/absorption_index_exactly_eight_grades_sw_while_eight_point_zero_six_grades_mw
        """
        env = _two_body_plant(api, 7.400)

        first = validate_success(api.qualify_formulation(env["first"]["id"], BODY_ENGINEER))
        assert first["blend_iron_oxide_pct"] == 6.250
        assert first["blend_lime_pct"] == 1.000
        assert first["shale_share_pct"] == 50.00
        assert first["absorption_index"] == 8.00
        assert first["computed_durability_grade"] == "SW"
        assert first["status"] == "QUALIFIED"

        second = validate_success(api.qualify_formulation(env["second"]["id"], BODY_ENGINEER))
        assert second["blend_iron_oxide_pct"] == 6.200
        assert second["blend_lime_pct"] == 1.000
        assert second["absorption_index"] == 8.06
        assert second["computed_durability_grade"] == "MW"
        assert second["status"] == "QUALIFIED"

    def test_the_index_is_rounded_before_the_band_is_read_off_it(self, api, clock):
        """
        An unrounded 8.0012 grades SW; 8.012 rounds to 8.01 and grades MW.

        Section 3.2 rounds first and reads the band second: the result "is clamped
        to the closed interval from 2.0 to 22.0 ... and then rounded half up to two
        decimal places to give absorption_index", and only that figure feeds the
        pinned SW / MW / NW ladder. A body at 6.249 iron computes 8.0012, which
        rounds to 8.00 and is therefore still SW.

        Design: Difficulty/boundary_precision_check/absorption_index_exactly_eight_grades_sw_while_eight_point_zero_six_grades_mw
        """
        env = _two_body_plant(api, 7.480)

        on_boundary = fx.create_draft_formulation(api, env["plant"]["id"])
        pits = validate_success(api.list_clay_pits(env["plant"]["id"], BODY_ENGINEER))
        shale = [p for p in pits if p["material_type"] == "SHALE"][0]
        near_clay = fx.create_clay_pit(
            api, env["plant"]["id"], iron_oxide_pct=7.498, lime_pct=1.200
        )
        fx.add_components(
            api, on_boundary, [(near_clay["id"], 50.00), (shale["id"], 50.00)]
        )

        rounded_down = validate_success(
            api.qualify_formulation(on_boundary["id"], BODY_ENGINEER)
        )
        assert rounded_down["blend_iron_oxide_pct"] == 6.249
        assert rounded_down["absorption_index"] == 8.00
        assert rounded_down["computed_durability_grade"] == "SW"

        one_step_over = validate_success(
            api.qualify_formulation(env["second"]["id"], BODY_ENGINEER)
        )
        assert one_step_over["blend_iron_oxide_pct"] == 6.240
        assert one_step_over["absorption_index"] == 8.01
        assert one_step_over["computed_durability_grade"] == "MW"


class TestMarketRadiusInclusiveBoundary:
    """
    Section 3.5: a plant is eligible when "the rectilinear haul distance from the
    plant to the jobsite is no greater than that plant's own market_radius_miles,
    the boundary being inclusive."
    """

    def _radius_sixty_plant(self, api):
        return fx.build_plant_with_assets(
            api, clock=None, plant_overrides={"market_radius_miles": 60}
        )

    def test_sixty_miles_is_inside_the_radius_and_sixty_one_is_not(self, api, clock):
        """
        A jobsite exactly 60 miles out is servable; 61 miles empties the pool.

        Section 3.5: the radius boundary is inclusive, and "If the eligible pool is
        empty, the assignment is rejected with ERR_NO_PLANT_IN_MARKET_RADIUS and
        nothing is written."

        Design: Difficulty/boundary_precision_check/market_radius_inclusive_at_sixty_miles_and_rejects_sixty_one
        """
        env = self._radius_sixty_plant(api)
        on_edge = fx.create_order(api, jobsite_grid_x=30, jobsite_grid_y=30)
        past_edge = fx.create_order(api, jobsite_grid_x=30, jobsite_grid_y=31)

        assigned = validate_success(api.assign_plant(on_edge["id"], SALES_REP))
        assert assigned["plant_id"] == env["plant"]["id"]
        assert assigned["distance_miles"] == 60
        assert assigned["fulfillment_status"] == "ASSIGNED"
        assert assigned["freight_status"] == "ESTIMATED"
        assert assigned["estimated_billable_tons"] == 21.60
        assert assigned["estimated_base_freight_cents"] == 54432
        assert assigned["estimated_fuel_surcharge_cents"] == 2449
        assert assigned["estimated_freight_cents"] == 56881

        validate_error(
            api.assign_plant(past_edge["id"], SALES_REP),
            ERR_NO_PLANT_IN_MARKET_RADIUS,
            422,
        )
        untouched = validate_success(api.get_order(past_edge["id"], SALES_REP))
        assert untouched["fulfillment_status"] == "DRAFT"
        assert untouched["freight_status"] == "UNQUOTED"
        assert untouched["plant_id"] is None
        assert untouched["distance_miles"] is None
        assert untouched["estimated_freight_cents"] is None
        assert untouched["version"] == past_edge["version"]

    def test_the_radius_is_measured_rectilinearly_not_as_the_crow_flies(self, api, clock):
        """
        A jobsite 80 rectilinear miles out is refused even though it is 58 as the crow flies.

        Section 3.5: "Haul distance on the freight grid is rectilinear - the
        absolute difference of the x coordinates plus the absolute difference of the
        y coordinates - never a straight-line or Euclidean distance, and
        distance_miles is stored as an exact integer with no rounding." A jobsite at
        (50,30) is 80 miles by that measure, outside a 60-mile radius, while (60,0)
        is exactly 60 and inside it.

        Design: Difficulty/boundary_precision_check/market_radius_inclusive_at_sixty_miles_and_rejects_sixty_one
        """
        self._radius_sixty_plant(api)
        straight_line = fx.create_order(api, jobsite_grid_x=50, jobsite_grid_y=30)
        validate_error(
            api.assign_plant(straight_line["id"], SALES_REP),
            ERR_NO_PLANT_IN_MARKET_RADIUS,
            422,
        )

        axis_aligned = fx.create_order(api, jobsite_grid_x=60, jobsite_grid_y=0)
        assigned = validate_success(api.assign_plant(axis_aligned["id"], SALES_REP))
        assert assigned["distance_miles"] == 60
        assert assigned["estimated_freight_cents"] == 56881

        negative_side = fx.create_order(api, jobsite_grid_x=-30, jobsite_grid_y=-30)
        assigned_negative = validate_success(api.assign_plant(negative_side["id"], SALES_REP))
        assert assigned_negative["distance_miles"] == 60
