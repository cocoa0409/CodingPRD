"""
The two places where one formula is evaluated twice with different inputs:
green-handling yield on a production run, and freight on an order.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    expected_actual_green_yield,
    expected_estimated_freight,
    expected_final_freight,
    expected_projected_net_green_units,
)
from test_helpers.test_users import LOGISTICS_COORDINATOR, PLANT_ADMIN


class TestGreenYieldProjectedVersusActual:
    """
    Section 3.3 states the projected loss is "350 basis points - 3.5 percent - of
    green_units_set, rounded up to a whole unit, plus a flat allowance of 12 units
    for the setting operation itself", while the close-out writes net_green_units
    as "green_units_set minus the reported green_loss_units" and
    green_loss_variance_units as "the signed gap net_green_units minus
    projected_net_green_units".
    """

    def test_close_green_writes_the_actual_variant_beside_the_projection(
        self, api, plant_env
    ):
        """
        A 10000-unit run losing 400 units projects 9638 and actually nets 9600.

        Section 3.3: "For a run of 10000 units set that loses 400, the projection
        netted 9638 while the actual nets 9600, so the variance is -38 on
        identical run data." The same section fixes the fork at "6.00 or less"
        and holds clay_tons_committed at the figure computed at creation.

        Design: Difficulty/dual_variant_calc/green_yield_projected_versus_actual_on_close_green
        """
        operator = plant_env["operator"]
        created = validate_success(
            api.create_production_run(
                F.production_run_payload(
                    plant_env["plant"]["id"],
                    plant_env["formulation"]["id"],
                    plant_env["kiln_car"]["id"],
                    green_units_set=10000,
                ),
                operator,
            ),
            201,
        )
        assert created["projected_net_green_units"] == 9638
        assert created["clay_tons_committed"] == 32.00
        assert created["net_green_units"] is None
        assert created["green_loss_variance_units"] is None

        closed = validate_success(
            api.close_green(created["id"], F.close_green_payload(400), operator)
        )
        assert closed["net_green_units"] == 9600
        assert closed["green_loss_pct"] == 4.00
        assert closed["green_loss_variance_units"] == -38
        assert closed["status"] == "SET"
        assert closed["projected_net_green_units"] == 9638
        assert closed["clay_tons_committed"] == 32.00

    def test_projection_ignores_the_reported_loss_on_the_held_branch(
        self, api, plant_env
    ):
        """
        The projection reads only the units set, so a run that goes to HELD keeps it.

        Section 3.3: the projection "reads nothing but the units set and the two
        constants: it never consults green_loss_units", and "When green_loss_pct
        is greater than 6.00, the run moves SETTING to HELD".

        Design: Difficulty/dual_variant_calc/green_yield_projected_versus_actual_on_close_green
        """
        operator = plant_env["operator"]
        created = validate_success(
            api.create_production_run(
                F.production_run_payload(
                    plant_env["plant"]["id"],
                    plant_env["formulation"]["id"],
                    plant_env["kiln_car"]["id"],
                    green_units_set=10000,
                ),
                operator,
            ),
            201,
        )
        assert created["projected_net_green_units"] == expected_projected_net_green_units(
            10000
        )

        closed = validate_success(
            api.close_green(created["id"], F.close_green_payload(700), operator)
        )
        actual = expected_actual_green_yield(10000, 700)
        assert closed["net_green_units"] == actual["net_green_units"] == 9300
        assert closed["green_loss_pct"] == actual["green_loss_pct"] == 7.00
        assert closed["status"] == "HELD"
        assert (
            closed["green_loss_variance_units"]
            == actual["green_loss_variance_units"]
            == -338
        )
        assert closed["projected_net_green_units"] == 9638

    def test_projected_loss_rounds_the_percentage_up_never_to_nearest(
        self, api, plant_env
    ):
        """
        A 10001-unit set loses 350.035 modelled units, which rounds up to 351.

        Section 3.3: "The percentage part always rounds up, never to the nearest
        and never down, so the projection is never optimistic."

        Design: Difficulty/dual_variant_calc/green_yield_projected_versus_actual_on_close_green
        """
        created = validate_success(
            api.create_production_run(
                F.production_run_payload(
                    plant_env["plant"]["id"],
                    plant_env["formulation"]["id"],
                    plant_env["kiln_car"]["id"],
                    green_units_set=10001,
                ),
                plant_env["operator"],
            ),
            201,
        )
        # 10001 - (ceil(350.035) = 351) - 12
        assert created["projected_net_green_units"] == 9638
        assert created["projected_net_green_units"] == (
            expected_projected_net_green_units(10001)
        )


class TestOrderFreightEstimatedVersusFinal:
    """
    Section 3.8 states the final variant "never reads requested_units at all; it
    bills what is actually on the truck", and that freight_variance_cents is
    "final_freight_cents minus estimated_freight_cents".
    """

    def _twelve_thousand_unit_certified_order(self, api, banding_type="STEEL"):
        env = fx.build_two_fired_lots(api)
        order = fx.build_assigned_order(
            api, requested_units=12000, banding_type=banding_type
        )
        blend = fx.build_certified_blend(
            api,
            order,
            [(env["lot_one"]["id"], 5000), (env["lot_two"]["id"], 7000)],
            target_color_index_min=48.00,
            target_color_index_max=54.00,
        )
        env["order"] = validate_success(api.get_order(order["id"], PLANT_ADMIN))
        env["blend"] = blend
        return env

    def test_packaging_re_quotes_on_real_weight_and_records_the_variance(self, api, clock):
        """
        The estimate bills 27.00 tons for 71102 cents; the truck bills 27.79 for 73182.

        Section 3.8: "For a 12000-unit order hauled 60 miles at 42 cents per
        ton-mile, the estimate billed 27.00 tons for 71102 cents while the final
        bill, on 24 pallets and 48 steel bands, bills 27.79 tons for 73182 cents
        - a variance of 2080 cents on identical order data."

        Design: Difficulty/dual_variant_calc/order_freight_estimated_versus_final_on_package
        """
        env = self._twelve_thousand_unit_certified_order(api)
        order = env["order"]
        assert order["estimated_billable_tons"] == 27.00
        assert order["estimated_base_freight_cents"] == 68040
        assert order["estimated_fuel_surcharge_cents"] == 3062
        assert order["estimated_freight_cents"] == 71102

        packaged = validate_success(
            api.package_order(order["id"], F.package_payload(24, 48), LOGISTICS_COORDINATOR)
        )
        assert packaged["final_billable_tons"] == 27.79
        assert packaged["final_base_freight_cents"] == 70031
        assert packaged["final_fuel_surcharge_cents"] == 3151
        assert packaged["final_freight_cents"] == 73182
        assert packaged["freight_variance_cents"] == 2080
        assert packaged["estimated_freight_cents"] == 71102
        assert packaged["fulfillment_status"] == "PACKAGED"
        assert packaged["freight_status"] == "FINALIZED"

    def test_banding_material_moves_the_final_bill_but_never_the_estimate(
        self, api, clock
    ):
        """
        Poly bands weigh 1.2 pounds against steel's 3.0, so only the final tons move.

        Section 3.8: the final weight adds "the banding weight for each band - a
        steel band weighs 3.0 pounds and a poly band weighs 1.2 pounds, selected
        by the order's banding_type". Section 3.5 computes the estimate from
        requested_units alone, so banding cannot reach it.

        Design: Difficulty/dual_variant_calc/order_freight_estimated_versus_final_on_package
        """
        env = self._twelve_thousand_unit_certified_order(api, banding_type="POLY")
        order = env["order"]
        estimate = expected_estimated_freight(12000, 60, 42)
        assert order["estimated_billable_tons"] == estimate["estimated_billable_tons"]
        assert order["estimated_freight_cents"] == estimate["estimated_freight_cents"] == 71102

        packaged = validate_success(
            api.package_order(order["id"], F.package_payload(24, 48), LOGISTICS_COORDINATOR)
        )
        final = expected_final_freight(12000, 24, 48, "POLY", 60, 42)
        assert packaged["final_billable_tons"] == final["final_billable_tons"]
        assert packaged["final_base_freight_cents"] == final["final_base_freight_cents"]
        assert packaged["final_fuel_surcharge_cents"] == final["final_fuel_surcharge_cents"]
        assert packaged["final_freight_cents"] == final["final_freight_cents"]
        assert packaged["freight_variance_cents"] == (
            final["final_freight_cents"] - estimate["estimated_freight_cents"]
        )
        assert packaged["final_billable_tons"] != 27.79
