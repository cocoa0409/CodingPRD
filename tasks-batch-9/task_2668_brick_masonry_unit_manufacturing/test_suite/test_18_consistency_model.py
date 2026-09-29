"""
Immediate consistency: every derived value is correct in the response of the
request that caused it and in the very next read, whichever role does the reading.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ARCHITECT_REVIEWER,
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    LOGISTICS_COORDINATOR,
    PLANT_ADMIN,
    QUALITY_MANAGER,
    SALES_REP,
)


class TestGradingIsCompleteInItsOwnResponse:
    """
    Grading writes the firing arithmetic, mints a lot, closes the run, frees the car
    and touches the plant's scrap counter - all inside one request.
    """

    def test_the_grade_response_and_four_later_reads_all_agree(self, api, clock):
        """
        20.68, 1.00 and 9600 come back from grade; four roles then read the fallout.

        Section 3.4 puts a 1040 C firing soaked three hours at a base CDI of 20.68 with
        a firing curve deviation of 1.00, mints `lot_code` as "the run's run_code
        followed by a hyphen, the letter P and the kiln_position" and `dye_lot_code` as
        "the body's formulation_code, a hyphen, the kiln run's run_code, a hyphen, the
        letter P and the kiln_position", and grades the centre position ON_COLOR at
        colour index 52.18 since "position 3 of 5" carries no temperature offset.
        Nothing here is re-read hoping a field has caught up.

        Design: Corner/consistency_model/grading_returns_every_derived_value_in_its_own_response_and_the_next_read_agrees
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        operator = env["operator"]
        run = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        kiln_run = fx.create_kiln_run(
            api, plant_id, env["kiln"]["id"], env["formulation"]["id"]
        )
        kiln_run = fx.load_kiln_run(api, plant_id, kiln_run, run["id"], 3)
        firing = fx.start_kiln_run(api, plant_id, kiln_run["id"])
        assert firing["status"] == "FIRING"

        graded = validate_success(
            api.grade_kiln_run(kiln_run["id"], F.grade_payload(1040, 3.0), operator)
        )
        assert graded["status"] == "GRADED"
        assert graded["base_cdi"] == 20.68
        assert graded["firing_curve_deviation"] == 1.00
        assert graded["loaded_units"] == 9600
        assert graded["graded_by_user_id"] == plant_id

        lots, lots_meta = validate_paginated(
            api.list_fired_lots(QUALITY_MANAGER, params={"production_run_id": run["id"]})
        )
        assert lots_meta["total_count"] == 1
        lot = lots[0]
        assert lot["lot_code"] == "{0}-P3".format(run["run_code"])
        assert lot["dye_lot_code"] == "{0}-{1}-P3".format(
            env["formulation"]["formulation_code"], kiln_run["run_code"]
        )
        assert lot["fired_units"] == 9600
        assert lot["available_units"] == 9600
        assert lot["grade"] == "ON_COLOR"
        assert lot["status"] == "AVAILABLE"
        assert lot["position_cdi"] == 20.68
        assert lot["color_index"] == 52.18
        assert lot["color_family"] == "RED"
        assert lot["texture"] == "WIRE_CUT"
        assert lot["durability_grade"] == "SW"

        run_read = validate_success(
            api.get_production_run(run["id"], LOGISTICS_COORDINATOR)
        )
        assert run_read["status"] == "FIRED"
        assert run_read["net_green_units"] == 9600
        assert run_read["kiln_position"] == 3
        assert run_read["scrap_units"] == 0

        cars = validate_success(api.list_kiln_cars(plant_id, BODY_ENGINEER))
        assert cars[0]["status"] == "IDLE"
        assert cars[0]["current_production_run_id"] is None

        plant_read = validate_success(api.get_plant(plant_id, SALES_REP))
        assert plant_read["fired_scrap_units"] == 0
        assert plant_read["status"] == "ACTIVE"


class TestReservationAndReleaseAreVisibleAtOnce:
    """
    The lot ledger, the order's two lifecycles and the freight bill are all readable
    by the next caller of any role, with no settling step anywhere.
    """

    def test_five_roles_observe_five_writes_each_on_its_first_read(self, api, clock):
        """
        Allocation, composition, certification, packaging and delivery, read by five roles.

        Section 3.7 moves the lot's units from `available_units` to `reserved_units` in
        the allocation request itself and computes the colour profile in the compose
        request; section 3.8 bills 22.23 tons for 58541 cents on 20 pallets and 20 steel
        bands against the 56881-cent estimate, and delivery "converts the reservation to
        consumption" so the lot lands CONSUMED with 9600 consumed units and the section
        2.9 identity still reconciling.

        Design: Corner/consistency_model/every_downstream_reservation_and_release_is_visible_to_the_next_reader_of_any_role
        """
        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        order = fx.build_assigned_order(api, requested_units=9600)
        assert order["estimated_freight_cents"] == 56881
        blend = fx.create_blend(api, order["id"], 9600)

        allocated = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 9600, blend["version"]),
                BLEND_TECHNICIAN,
            )
        )
        assert allocated["allocated_units"] == 9600

        reserved = validate_success(api.get_fired_lot(lot["id"], QUALITY_MANAGER))
        assert reserved["reserved_units"] == 9600
        assert reserved["available_units"] == 0
        assert reserved["consumed_units"] == 0
        assert reserved["status"] == "RESERVED"

        composed = validate_success(
            api.compose_blend(blend["id"], F.compose_payload(False), BLEND_TECHNICIAN)
        )
        assert composed["weighted_color_index"] == 52.18
        assert composed["color_range_span"] == 0.00

        order_read = validate_success(api.get_order(order["id"], ARCHITECT_REVIEWER))
        assert order_read["fulfillment_status"] == "IN_BLENDING"

        certified = validate_success(api.certify_blend(blend["id"], QUALITY_MANAGER))
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_at"] == "2026-08-01T00:00:00Z"

        components = validate_success(
            api.list_blend_components(blend["id"], LOGISTICS_COORDINATOR)
        )
        assert components[0]["status"] == "ALLOCATED"
        assert components[0]["units"] == 9600
        assert components[0]["color_index_at_allocation"] == 52.18

        packaged = validate_success(
            api.package_order(order["id"], F.package_payload(20, 20), LOGISTICS_COORDINATOR)
        )
        assert packaged["final_billable_tons"] == 22.23
        assert packaged["final_freight_cents"] == 58541
        assert packaged["freight_variance_cents"] == 1660
        assert packaged["freight_status"] == "FINALIZED"

        delivered = validate_success(
            api.deliver_order(
                order["id"],
                F.deliver_payload("TRUCK_MOUNTED_FORKLIFT"),
                LOGISTICS_COORDINATOR,
            )
        )
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["delivered_at"] == "2026-08-01T00:00:00Z"

        consumed = validate_success(
            api.get_fired_lot(lot["id"], fx.make_plant_operator_headers(env["plant"]["id"]))
        )
        assert consumed["reserved_units"] == 0
        assert consumed["consumed_units"] == 9600
        assert consumed["available_units"] == 0
        assert consumed["status"] == "CONSUMED"
        assert validate_success(api.get_plant(env["plant"]["id"], PLANT_ADMIN))["status"] == "ACTIVE"
