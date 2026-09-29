"""
Formulas whose answer depends on the order the steps are taken in: the two-level
clay split with its residual, and the surcharge tier keyed on the rounded base.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_clay_reserve_conserved,
    expected_clay_commitment,
    expected_estimated_freight,
)
from test_helpers.test_users import PLANT_ADMIN, SALES_REP


def _three_pit_plant(api, shares):
    """A plant whose qualified body draws on three pits in the given share order."""
    plant = fx.create_plant(api)
    pit_one = fx.create_clay_pit(
        api, plant["id"], iron_oxide_pct=6.000, lime_pct=1.000, proven_reserve_tons=5000.00
    )
    pit_two = fx.create_clay_pit(
        api, plant["id"], iron_oxide_pct=6.000, lime_pct=1.000, proven_reserve_tons=5000.00
    )
    pit_three = fx.create_shale_pit(
        api, plant["id"], iron_oxide_pct=6.000, lime_pct=1.000, proven_reserve_tons=5000.00
    )
    pits = [pit_one, pit_two, pit_three]
    formulation = fx.build_qualified_formulation(
        api,
        plant["id"],
        list(zip([p["id"] for p in pits], shares)),
        clay_tons_per_thousand_units=3.20,
    )
    car = fx.create_kiln_car(api, plant["id"])
    return {"plant": plant, "pits": pits, "formulation": formulation, "kiln_car": car}


class TestClayTonnagePerPitResidual:
    """
    Section 3.3 fixes the two-level split and where the residual lands: "The
    residual is the run total minus the accumulated sum of per-pit amounts,
    rounded half up to two decimal places, and it lands entirely on the last
    component in that append order."
    """

    def test_thirty_three_thirds_put_the_negative_residual_on_the_last_pit(
        self, api, clock
    ):
        """
        Three pits at 33.33 / 33.33 / 33.34 of a 32.00-ton run take 10.67 / 10.67 / 10.66.

        Section 3.3: "three pits holding 33.33, 33.33 and 33.34 percent of a
        32.00-ton run receive 10.67, 10.67 and 10.66 tons respectively - not
        10.66, 10.67, 10.67 and not 10.67, 10.67, 10.67."

        Design: Difficulty/combinatorial_formula/clay_tonnage_per_pit_rounding_residual_mode_b
        """
        env = _three_pit_plant(api, [33.33, 33.33, 33.34])
        assert env["formulation"]["absorption_index"] == 9.63
        assert env["formulation"]["computed_durability_grade"] == "MW"

        run = validate_success(
            api.create_production_run(
                F.production_run_payload(
                    env["plant"]["id"],
                    env["formulation"]["id"],
                    env["kiln_car"]["id"],
                    green_units_set=10000,
                ),
                fx.make_plant_operator_headers(env["plant"]["id"]),
            ),
            201,
        )
        assert run["clay_tons_committed"] == 32.00

        pits = validate_success(api.list_clay_pits(env["plant"]["id"], PLANT_ADMIN))
        assert [p["committed_tons"] for p in pits] == [10.67, 10.67, 10.66]
        assert round(sum(p["committed_tons"] for p in pits), 2) == 32.00
        assert [p["available_tons"] for p in pits] == [4989.33, 4989.33, 4989.34]
        for pit in pits:
            assert_clay_reserve_conserved(pit)

        after = validate_success(api.get_formulation(env["formulation"]["id"], PLANT_ADMIN))
        assert after["absorption_index"] == 9.63
        assert after["computed_durability_grade"] == "MW"

    def test_a_positive_residual_also_lands_on_the_last_appended_component(
        self, api, clock
    ):
        """
        Shares of 16.67 / 16.67 / 66.66 leave a positive residual for the last pit.

        Section 3.3: each per-pit amount comes from "the already-rounded run
        total", and the residual "is never spread across pits, never dropped, and
        never assigned by id". Here 5.33 plus 5.33 leaves 21.34 for the last
        component, one hundredth above its own rounded share of 21.33.

        Design: Difficulty/combinatorial_formula/clay_tonnage_per_pit_rounding_residual_mode_b
        """
        env = _three_pit_plant(api, [16.67, 16.67, 66.66])
        run = validate_success(
            api.create_production_run(
                F.production_run_payload(
                    env["plant"]["id"],
                    env["formulation"]["id"],
                    env["kiln_car"]["id"],
                    green_units_set=10000,
                ),
                fx.make_plant_operator_headers(env["plant"]["id"]),
            ),
            201,
        )
        expected = expected_clay_commitment(10000, 3.20, [16.67, 16.67, 66.66])
        assert run["clay_tons_committed"] == expected["total_tons"] == 32.00

        pits = validate_success(api.list_clay_pits(env["plant"]["id"], PLANT_ADMIN))
        assert [p["committed_tons"] for p in pits] == expected["per_pit_tons"]
        assert [p["committed_tons"] for p in pits] == [5.33, 5.33, 21.34]
        assert round(sum(p["committed_tons"] for p in pits), 2) == 32.00
        for pit in pits:
            assert_clay_reserve_conserved(pit)


class TestFreightSurchargeTierKeyedOnBase:
    """
    Section 3.5 states the surcharge is "a whole-bill rate selected from the
    rounded base - not a marginal rate applied bracket by bracket - and the three
    arms are evaluated in exactly this order. A base below 50000 cents carries 6.5
    percent. Otherwise a base below 150000 cents carries 4.5 percent. Otherwise
    the base carries 3.0 percent."
    """

    def _plant_for(self, api, rate_cents=40):
        return fx.build_plant_with_assets(
            api,
            clock=None,
            plant_overrides={
                "grid_x": 0,
                "grid_y": 0,
                "market_radius_miles": 300,
                "freight_rate_cents_per_ton_mile": rate_cents,
                "base_capacity_green_units_per_day": 40000,
            },
        )

    def test_five_extra_bricks_cross_the_first_tier_and_lower_the_bill(self, api, clock):
        """
        11111 units total 52250 cents while 11106 units total 53229.

        Section 3.5: "Hauling 50 miles at 40 cents per ton-mile, 11106 units bills
        24.99 tons for a base of 49980 cents, which sits in the first tier at 6.5
        percent and totals 53229 cents; 11111 units bills exactly 25.00 tons for a
        base of 50000 cents, which just reaches the second tier at 4.5 percent and
        totals only 52250 cents. Shipping five more bricks lowers the bill."

        Design: Difficulty/combinatorial_formula/freight_surcharge_tier_keyed_on_base_mode_c
        """
        env = self._plant_for(api)
        order_x = fx.create_order(
            api, requested_units=11111, jobsite_grid_x=25, jobsite_grid_y=25
        )
        order_y = fx.create_order(
            api, requested_units=11106, jobsite_grid_x=25, jobsite_grid_y=25
        )

        assigned_x = validate_success(api.assign_plant(order_x["id"], SALES_REP))
        assigned_y = validate_success(api.assign_plant(order_y["id"], SALES_REP))

        assert assigned_x["estimated_billable_tons"] == 25.00
        assert assigned_x["estimated_base_freight_cents"] == 50000
        assert assigned_x["estimated_fuel_surcharge_cents"] == 2250
        assert assigned_x["estimated_freight_cents"] == 52250

        assert assigned_y["estimated_billable_tons"] == 24.99
        assert assigned_y["estimated_base_freight_cents"] == 49980
        assert assigned_y["estimated_fuel_surcharge_cents"] == 3249
        assert assigned_y["estimated_freight_cents"] == 53229

        assert assigned_y["estimated_freight_cents"] > assigned_x["estimated_freight_cents"]
        assert assigned_x["distance_miles"] == assigned_y["distance_miles"] == 50
        assert assigned_x["plant_id"] == assigned_y["plant_id"] == env["plant"]["id"]

    def test_a_base_of_exactly_one_hundred_fifty_thousand_takes_the_third_arm(
        self, api, clock
    ):
        """
        A base of exactly 150000 cents is not below 150000, so it carries 3.0 percent.

        Section 3.5 evaluates the arms in order: "Otherwise a base below 150000
        cents carries 4.5 percent. Otherwise the base carries 3.0 percent." At 150
        miles and 40 cents a ton-mile, 11111 units bill 25.00 tons for a base of
        exactly 150000 cents.

        Design: Difficulty/combinatorial_formula/freight_surcharge_tier_keyed_on_base_mode_c
        """
        self._plant_for(api)
        order = fx.create_order(
            api, requested_units=11111, jobsite_grid_x=75, jobsite_grid_y=75
        )
        assigned = validate_success(api.assign_plant(order["id"], SALES_REP))
        expected = expected_estimated_freight(11111, 150, 40)
        assert assigned["distance_miles"] == 150
        assert assigned["estimated_base_freight_cents"] == 150000
        assert assigned["estimated_fuel_surcharge_cents"] == 4500
        assert assigned["estimated_freight_cents"] == 154500
        assert assigned["estimated_freight_cents"] == expected["estimated_freight_cents"]
