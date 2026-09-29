"""
The two deep cascades: idling a plant, and cancelling an order. Each hop reads the
state the previous hop wrote, so the interesting assertions are on the far end.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_PLANT_IDLED
from test_helpers.assertions import (
    assert_clay_reserve_conserved,
    assert_fired_units_conserved,
)
from test_helpers.test_users import (
    ARCHITECT_REVIEWER,
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    PLANT_ADMIN,
    SALES_REP,
)


class TestPlantIdleCascade:
    """
    Section 3.9 fixes the hop order: pits go SUSPENDED, that de-qualifies the
    recipes containing them, that scraps the runs still SETTING on those recipes,
    and that releases their committed clay.
    """

    def test_idle_reaches_pit_recipe_run_and_clay_ledger_in_that_order(self, api, clock):
        """
        One idle call suspends the pits, drafts the body, scraps R1 and unwinds its clay.

        Section 3.9 Hop 2: a body is de-qualified because its pits were "suspended
        by hop 1 of this request". Hop 3 scraps only runs whose "status is SETTING"
        - "Runs already SET, HELD, LOADED or FIRED are not in scope". Hop 4 releases
        "the exact per-pit amount committed at run creation". Hop 3b aborts the
        SCHEDULED firing and hop 4b reverts the LOADED run to SET, clearing both
        kiln_run_id and kiln_position.

        Design: Difficulty/transitive_cascade/plant_idle_cascades_four_hops_to_pit_formulation_run_and_clay_ledger
        """
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        car_two = fx.create_kiln_car(api, plant_id)

        run_two = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], car_two["id"]
        )
        kiln_run = fx.create_kiln_run(
            api, plant_id, env["kiln"]["id"], env["formulation"]["id"]
        )
        kiln_run = fx.load_kiln_run(api, plant_id, kiln_run, run_two["id"], 3)
        assert kiln_run["status"] == "SCHEDULED"

        run_one = fx.create_production_run(
            api, plant_id, env["formulation"]["id"], env["kiln_car"]["id"]
        )
        assert run_one["status"] == "SETTING"
        assert run_one["clay_tons_committed"] == 32.00

        before = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["committed_tons"] for p in before] == [16.00, 16.00]
        assert [p["available_tons"] for p in before] == [4968.00, 4968.00]
        assert [p["consumed_tons"] for p in before] == [16.00, 16.00]

        idled = validate_success(api.idle_plant(plant_id, PLANT_ADMIN))
        assert idled["status"] == "IDLED"
        assert idled["idled_at"] == "2026-08-01T00:00:00Z"

        after = validate_success(api.list_clay_pits(plant_id, PLANT_ADMIN))
        assert [p["status"] for p in after] == ["SUSPENDED", "SUSPENDED"]
        assert [p["committed_tons"] for p in after] == [0.00, 0.00]
        assert [p["available_tons"] for p in after] == [4984.00, 4984.00]
        assert [p["consumed_tons"] for p in after] == [16.00, 16.00]
        for pit in after:
            assert_clay_reserve_conserved(pit)

        body = validate_success(api.get_formulation(env["formulation"]["id"], BODY_ENGINEER))
        assert body["status"] == "DRAFT"
        assert body["dequalified_count"] == 1
        assert body["qualified_at"] is None

        operator = env["operator"]
        scrapped = validate_success(api.get_production_run(run_one["id"], operator))
        assert scrapped["status"] == "SCRAPPED"

        aborted = validate_success(api.get_kiln_run(kiln_run["id"], operator))
        assert aborted["status"] == "ABORTED"

        reverted = validate_success(api.get_production_run(run_two["id"], operator))
        assert reverted["status"] == "SET"
        assert reverted["kiln_run_id"] is None
        assert reverted["kiln_position"] is None

        cars = validate_success(api.list_kiln_cars(plant_id, PLANT_ADMIN))
        assert [c["status"] for c in cars] == ["OUT_OF_SERVICE", "OUT_OF_SERVICE"]
        assert all(c["current_production_run_id"] is None for c in cars)

        kilns = validate_success(api.list_kilns(plant_id, PLANT_ADMIN))
        assert [k["status"] for k in kilns] == ["MAINTENANCE"]

    def test_idle_leaves_fired_inventory_and_assigned_orders_alone(self, api, clock):
        """
        Fired lots and assigned orders survive the cascade; a second idle is refused.

        Section 3.9: "Fired lots, orders, shipped blends, blend components and
        sample panels are not touched by this cascade: inventory already fired at
        the plant stays exactly as it was, and orders already assigned to the plant
        keep their assignment and their quote." The same section makes IDLED
        terminal, so "a second idle attempt on an already IDLED plant is rejected
        with ERR_PLANT_IDLED".

        Design: Difficulty/transitive_cascade/plant_idle_cascades_four_hops_to_pit_formulation_run_and_clay_ledger
        """
        env = fx.build_fired_lot(api, clock=None)
        plant_id = env["plant"]["id"]
        order = fx.build_assigned_order(api)
        lot_before = env["fired_lot"]

        validate_success(api.idle_plant(plant_id, PLANT_ADMIN))

        lot_after = validate_success(api.get_fired_lot(lot_before["id"], PLANT_ADMIN))
        assert lot_after["status"] == lot_before["status"] == "AVAILABLE"
        assert lot_after["available_units"] == lot_before["available_units"] == 9600
        assert lot_after["version"] == lot_before["version"]
        assert_fired_units_conserved(lot_after)

        order_after = validate_success(api.get_order(order["id"], SALES_REP))
        assert order_after["plant_id"] == plant_id
        assert order_after["fulfillment_status"] == "ASSIGNED"
        assert order_after["estimated_freight_cents"] == order["estimated_freight_cents"]
        assert order_after["version"] == order["version"]

        validate_error(api.idle_plant(plant_id, PLANT_ADMIN), ERR_PLANT_IDLED, 409)


class TestOrderCancelCascade:
    """
    Section 3.8: cancellation moves the order to CANCELLED and freight to WAIVED,
    then voids the blend, then voids its components, then returns the reserved
    units to the lots, with a separate branch that withdraws in-flight paperwork.
    """

    def test_cancel_voids_the_blend_and_returns_the_reserved_units(self, api, clock):
        """
        Cancelling a COMPOSED blend's order releases all 9600 reserved units.

        Section 3.8: the blend "moves to VOID from whichever of DRAFT, COMPOSED or
        CERTIFIED it held", "every ALLOCATED component of that blend moves to
        VOIDED and the blend's allocated_units returns to 0", and "every fired lot
        behind those components has the voided units moved out of reserved_units
        and back into available_units, and a lot whose reserved_units reaches 0
        moves RESERVED to AVAILABLE". The panel branch moves a SUBMITTED panel to
        WITHDRAWN.

        Design: Difficulty/transitive_cascade/order_cancel_cascades_four_hops_to_blend_components_and_lot_inventory
        """
        env = fx.build_fired_lot(api, clock=None)
        lot_id = env["fired_lot"]["id"]
        order = fx.build_assigned_order(api, requires_panel_approval=True)
        blend = fx.build_composed_blend(api, order, [(lot_id, 9600)])
        assert blend["status"] == "COMPOSED"
        assert blend["allocated_units"] == 9600

        panel = fx.create_sample_panel(
            api, order["id"], env["formulation"]["id"], lot_id, 52.18
        )
        panel = validate_success(api.submit_panel(panel["id"], BLEND_TECHNICIAN))
        assert panel["status"] == "SUBMITTED"

        reserved = validate_success(api.get_fired_lot(lot_id, BLEND_TECHNICIAN))
        assert reserved["status"] == "RESERVED"
        assert reserved["reserved_units"] == 9600
        assert reserved["available_units"] == 0

        cancelled = validate_success(
            api.cancel_order(
                order["id"],
                F.cancel_payload("Architect pulled the masonry package"),
                SALES_REP,
            )
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["freight_status"] == "WAIVED"

        voided_blend = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert voided_blend["status"] == "VOID"
        assert voided_blend["allocated_units"] == 0

        components = validate_success(api.list_blend_components(blend["id"], BLEND_TECHNICIAN))
        assert [c["status"] for c in components] == ["VOIDED"]
        assert components[0]["units"] == 9600

        released = validate_success(api.get_fired_lot(lot_id, BLEND_TECHNICIAN))
        assert released["status"] == "AVAILABLE"
        assert released["reserved_units"] == 0
        assert released["available_units"] == 9600
        assert released["consumed_units"] == 0
        assert released["fired_units"] == 9600
        assert_fired_units_conserved(released)

        withdrawn = validate_success(api.get_sample_panel(panel["id"], ARCHITECT_REVIEWER))
        assert withdrawn["status"] == "WITHDRAWN"

    def test_cancel_after_packaging_waives_freight_without_erasing_the_money(
        self, api, clock
    ):
        """
        A PACKAGED order cancels from FINALIZED to WAIVED and keeps every figure.

        Section 3.8: freight "moves to WAIVED from whichever of UNQUOTED, ESTIMATED
        or FINALIZED it held", and "Waiving freight does not erase the money" - the
        estimated and final figures and the variance "are all left exactly as they
        stood". The same section leaves panels "already APPROVED or EXPIRED" alone.

        Design: Difficulty/transitive_cascade/order_cancel_cascades_four_hops_to_blend_components_and_lot_inventory
        """
        env = fx.build_fired_lot(api, clock=None)
        lot_id = env["fired_lot"]["id"]
        order = fx.build_assigned_order(api, requires_panel_approval=True)
        panel = fx.build_approved_panel(
            api, order["id"], env["formulation"]["id"], lot_id, 52.18
        )
        blend = fx.build_certified_blend(api, order, [(lot_id, 9600)])
        packaged = fx.package_order(api, order["id"], 20, 40)
        assert packaged["freight_status"] == "FINALIZED"

        cancelled = validate_success(
            api.cancel_order(
                order["id"], F.cancel_payload("Jobsite shut down"), SALES_REP
            )
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["freight_status"] == "WAIVED"
        assert cancelled["estimated_freight_cents"] == packaged["estimated_freight_cents"]
        assert cancelled["final_billable_tons"] == packaged["final_billable_tons"]
        assert cancelled["final_freight_cents"] == packaged["final_freight_cents"]
        assert cancelled["freight_variance_cents"] == packaged["freight_variance_cents"]

        voided_blend = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert voided_blend["status"] == "VOID"
        assert voided_blend["allocated_units"] == 0

        released = validate_success(api.get_fired_lot(lot_id, BLEND_TECHNICIAN))
        assert released["status"] == "AVAILABLE"
        assert released["available_units"] == 9600
        assert released["reserved_units"] == 0
        assert_fired_units_conserved(released)

        untouched = validate_success(api.get_sample_panel(panel["id"], ARCHITECT_REVIEWER))
        assert untouched["status"] == "APPROVED"
        assert untouched["version"] == panel["version"]
