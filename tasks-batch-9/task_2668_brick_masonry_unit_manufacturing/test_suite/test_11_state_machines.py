"""
Lifecycle behaviour: the transitions that are allowed, the ones that are refused,
the initial states, the branch points and the side effects each hop carries.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_FORMULATION_NOT_DRAFT,
    ERR_KILN_CAR_NOT_IDLE,
    ERR_LOT_QUARANTINED,
    ERR_ORDER_STATE_INVALID,
    ERR_PRODUCTION_RUN_STATE_INVALID,
)
from test_helpers.assertions import assert_fired_units_conserved
from test_helpers.test_users import (
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    LOGISTICS_COORDINATOR,
    PLANT_ADMIN,
    QUALITY_MANAGER,
    SALES_REP,
)


def _car_by_id(api, plant_id, car_id):
    cars = validate_success(api.list_kiln_cars(plant_id, PLANT_ADMIN))
    return [c for c in cars if c["id"] == car_id][0]


class TestKilnRunLifecycle:
    """
    Section 3.4 walks a kiln run SCHEDULED -> FIRING -> GRADED, with the loading
    side effects landing on three different records.
    """

    def test_lighting_off_moves_scheduled_to_firing_and_changes_nothing_else(
        self, api, clock
    ):
        """
        Start advances the status and leaves the charge and the curve alone.

        Section 3.4: "The operator starts a kiln run, moving it SCHEDULED to FIRING
        and incrementing its version by 1", while the realised curve figures are
        written only at grading, and neither the loaded production run nor the car it
        rides on is named among the transition's effects.

        Design: Corner/state_machines/kiln_run_start_moves_scheduled_to_firing
        """
        env = fx.build_plant_with_assets(api, clock=None)
        run = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        kiln_run = fx.create_kiln_run(
            api, env["plant"]["id"], env["kiln"]["id"], env["formulation"]["id"]
        )
        assert kiln_run["status"] == "SCHEDULED"
        kiln_run = fx.load_kiln_run(api, env["plant"]["id"], kiln_run, run["id"], 3)
        assert kiln_run["loaded_units"] == 9600

        started = validate_success(
            api.start_kiln_run(kiln_run["id"], env["operator"]), 200
        )
        assert started["status"] == "FIRING"
        assert started["loaded_units"] == 9600
        assert started["actual_peak_temp_c"] is None
        assert started["actual_soak_hours"] is None
        assert started["base_cdi"] is None
        assert started["firing_curve_deviation"] is None
        assert started["graded_by_user_id"] is None
        assert started["version"] == kiln_run["version"] + 1

        still_loaded = validate_success(
            api.get_production_run(run["id"], env["operator"])
        )
        assert still_loaded["status"] == "LOADED"
        assert _car_by_id(api, env["plant"]["id"], env["kiln_car"]["id"])["status"] == (
            "IN_KILN"
        )

    def test_each_load_accumulates_the_charge_and_bumps_one_version(self, api, clock):
        """
        Two loads take loaded_units 0 -> 9600 -> 14400 and the version 1 -> 2 -> 3.

        Section 3.4: "A successful load moves the production run SET to LOADED and
        writes its kiln_run_id and kiln_position; moves the car SET to IN_KILN;
        recomputes the kiln run's loaded_units as the sum of net_green_units over
        every production run pointing at it; and increments the kiln run's version by
        1." The kiln run itself stays SCHEDULED until it is lit off.

        Design: Corner/state_machines/kiln_run_load_applies_all_declared_side_effects
        """
        env = fx.build_plant_with_assets(api, clock=None)
        operator = env["operator"]
        car_two = fx.create_kiln_car(api, env["plant"]["id"])
        run_one = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        run_two = fx.build_set_production_run(
            api,
            env["plant"],
            env["formulation"]["id"],
            car_two["id"],
            green_units_set=5000,
            green_loss_units=200,
        )
        assert run_one["net_green_units"] == 9600
        assert run_two["net_green_units"] == 4800

        kiln_run = fx.create_kiln_run(
            api, env["plant"]["id"], env["kiln"]["id"], env["formulation"]["id"]
        )
        assert kiln_run["loaded_units"] == 0
        assert kiln_run["version"] == 1

        after_first = validate_success(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(run_one["id"], 3, kiln_run["version"]),
                operator,
            )
        )
        assert after_first["loaded_units"] == 9600
        assert after_first["version"] == 2
        assert after_first["status"] == "SCHEDULED"

        loaded_run = validate_success(api.get_production_run(run_one["id"], operator))
        assert loaded_run["status"] == "LOADED"
        assert loaded_run["kiln_position"] == 3
        assert loaded_run["kiln_run_id"] == kiln_run["id"]
        assert _car_by_id(api, env["plant"]["id"], env["kiln_car"]["id"])["status"] == (
            "IN_KILN"
        )

        after_second = validate_success(
            api.load_kiln_run(
                kiln_run["id"],
                F.kiln_load_payload(run_two["id"], 1, after_first["version"]),
                operator,
            )
        )
        assert after_second["loaded_units"] == 14400
        assert after_second["version"] == 3
        assert after_second["status"] == "SCHEDULED"

    def test_grading_forks_into_overfire_and_underfire_on_the_same_kiln(
        self, api, clock
    ):
        """
        A 1140 C firing scraps hot at colour 100.00; a 960 C firing scraps cold at 10.70.

        Section 3.4: base_cdi is "0.62 multiplied by the quantity actual_peak_temp_c
        minus 900 divided by 10, plus 4.0 multiplied by actual_soak_hours", the grade
        is OVERFIRE_SCRAP when position_cdi is "strictly greater than the target plus
        6.00" and UNDERFIRE_SCRAP when "strictly less than the target minus 6.00",
        colour is "50.0 plus 3.2 multiplied by the signed difference ... clamped to
        the closed range 0.00 to 100.00", and a scrap lot "is created directly in
        SCRAP" while "the production run's scrap_units is set to that lot's
        fired_units, and the owning plant's fired_scrap_units running total is
        increased by the same amount".

        Design: Corner/state_machines/grading_forks_into_overfire_and_underfire_scrap_on_the_same_kiln
        """
        env = fx.build_plant_with_assets(api, clock=None)
        operator = env["operator"]
        car_two = fx.create_kiln_car(api, env["plant"]["id"])
        run_hot = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        run_cold = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], car_two["id"]
        )

        hot = fx.create_kiln_run(
            api, env["plant"]["id"], env["kiln"]["id"], env["formulation"]["id"]
        )
        hot = fx.load_kiln_run(api, env["plant"]["id"], hot, run_hot["id"], 3)
        fx.start_kiln_run(api, env["plant"]["id"], hot["id"])
        graded_hot = validate_success(
            api.grade_kiln_run(hot["id"], F.grade_payload(1140, 6.0), operator)
        )
        assert graded_hot["base_cdi"] == 38.88
        assert graded_hot["firing_curve_deviation"] == 12.00
        assert graded_hot["status"] == "GRADED"

        lot_hot = fx.fired_lots_of_run(api, run_hot["id"])[0]
        assert lot_hot["position_cdi"] == 38.88
        assert lot_hot["grade"] == "OVERFIRE_SCRAP"
        assert lot_hot["color_index"] == 100.00
        assert lot_hot["status"] == "SCRAP"
        # Section 3.4 opens every minted lot with "available_units equal to
        # fired_units", and section 2.9 keeps available + reserved + consumed equal
        # to fired_units at every observable moment, scrap grade included.
        assert lot_hot["available_units"] == lot_hot["fired_units"]
        assert_fired_units_conserved(lot_hot)

        cold = fx.create_kiln_run(
            api,
            env["plant"]["id"],
            env["kiln"]["id"],
            env["formulation"]["id"],
            start_at="2026-08-07T07:00:00Z",
            end_at="2026-08-09T00:00:00Z",
        )
        cold = fx.load_kiln_run(api, env["plant"]["id"], cold, run_cold["id"], 3)
        fx.start_kiln_run(api, env["plant"]["id"], cold["id"])
        graded_cold = validate_success(
            api.grade_kiln_run(cold["id"], F.grade_payload(960, 1.0), operator)
        )
        assert graded_cold["base_cdi"] == 7.72
        assert graded_cold["firing_curve_deviation"] == 11.00

        lot_cold = fx.fired_lots_of_run(api, run_cold["id"])[0]
        assert lot_cold["position_cdi"] == 7.72
        assert lot_cold["grade"] == "UNDERFIRE_SCRAP"
        assert lot_cold["color_index"] == 10.70
        assert lot_cold["status"] == "SCRAP"

        plant = validate_success(api.get_plant(env["plant"]["id"], PLANT_ADMIN))
        assert plant["fired_scrap_units"] == 19200

        fired = validate_success(api.get_production_run(run_hot["id"], operator))
        assert fired["status"] == "FIRED"
        assert fired["scrap_units"] == 9600


class TestRefusedTransitionsWriteNothing:
    """
    A precondition failure leaves every record - and every ledger - exactly as it
    stood, including the version counter.
    """

    def test_a_second_run_on_a_car_that_is_already_set_is_refused(self, api, clock):
        """
        The car still belongs to the first run and no further clay is committed.

        Section 3.3: "The named car must be IDLE and must carry no
        current_production_run_id; a car that is SET, IN_KILN or OUT_OF_SERVICE, or
        one that already names a run, is rejected with ERR_KILN_CAR_NOT_IDLE", and a
        successful run is the only thing that commits clay against the pits.

        Design: Corner/state_machines/production_run_on_occupied_car_returns_kiln_car_not_idle
        """
        env = fx.build_plant_with_assets(api, clock=None)
        operator = env["operator"]
        first = fx.create_production_run(
            api, env["plant"]["id"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        assert first["status"] == "SETTING"
        occupied = _car_by_id(api, env["plant"]["id"], env["kiln_car"]["id"])
        assert occupied["status"] == "SET"
        assert occupied["current_production_run_id"] == first["id"]

        validate_error(
            api.create_production_run(
                F.production_run_payload(
                    env["plant"]["id"],
                    env["formulation"]["id"],
                    env["kiln_car"]["id"],
                    green_units_set=5000,
                ),
                operator,
            ),
            ERR_KILN_CAR_NOT_IDLE,
            409,
        )

        pits = validate_success(api.list_clay_pits(env["plant"]["id"], PLANT_ADMIN))
        assert [p["committed_tons"] for p in pits] == [16.00, 16.00]
        still_first = _car_by_id(api, env["plant"]["id"], env["kiln_car"]["id"])
        assert still_first["status"] == "SET"
        assert still_first["current_production_run_id"] == first["id"]

        runs, meta = validate_paginated(
            api.list_production_runs(
                PLANT_ADMIN, params={"plant_id": env["plant"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert runs[0]["id"] == first["id"]

    def test_closing_green_twice_neither_reapplies_the_loss_nor_the_clay(
        self, api, clock
    ):
        """
        A second close-out on a SET run is refused and the run is bit-for-bit unchanged.

        Section 3.3: "The run must be SETTING; closing out a run in any other status
        is rejected with ERR_PRODUCTION_RUN_STATE_INVALID", and the first close-out
        already moved "the committed clay into consumption: each contributing pit has
        its exact per-pit amount ... subtracted from committed_tons and added to
        consumed_tons".

        Design: Corner/state_machines/second_close_green_returns_production_run_state_invalid
        """
        env = fx.build_plant_with_assets(api, clock=None)
        operator = env["operator"]
        run = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        assert run["status"] == "SET"
        assert run["net_green_units"] == 9600
        assert run["green_loss_pct"] == 4.00

        validate_error(
            api.close_green(run["id"], F.close_green_payload(900), operator),
            ERR_PRODUCTION_RUN_STATE_INVALID,
            409,
        )

        after = validate_success(api.get_production_run(run["id"], operator))
        assert after["status"] == "SET"
        assert after["net_green_units"] == 9600
        assert after["green_loss_units"] == 400
        assert after["green_loss_pct"] == 4.00
        assert after["version"] == run["version"]

        pits = validate_success(api.list_clay_pits(env["plant"]["id"], PLANT_ADMIN))
        assert [p["consumed_tons"] for p in pits] == [16.00, 16.00]
        assert [p["committed_tons"] for p in pits] == [0.00, 0.00]

    def test_qualifying_an_already_qualified_body_does_not_restamp_the_date(
        self, api, clock
    ):
        """
        Qualification is not idempotent: the second call is refused, not absorbed.

        Section 3.2: "Qualification of a formulation that is already QUALIFIED or has
        been RETIRED is rejected with ERR_FORMULATION_NOT_DRAFT", and de-qualification
        "is never a direct operator action: it happens only through the plant-idle
        cascade of section 3.9, which clears qualified_at and increments
        dequalified_count by 1 each time it fires." The clock has moved a day on, so a
        re-stamped qualified_at would be visible.

        Design: Corner/state_machines/qualify_on_already_qualified_formulation_returns_formulation_not_draft
        """
        env = fx.build_plant_with_assets(api, clock=None)
        body = env["formulation"]
        assert body["status"] == "QUALIFIED"
        assert body["qualified_at"] == "2026-08-01T00:00:00Z"

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        validate_error(
            api.qualify_formulation(body["id"], BODY_ENGINEER),
            ERR_FORMULATION_NOT_DRAFT,
            409,
        )

        after = validate_success(api.get_formulation(body["id"], BODY_ENGINEER))
        assert after["status"] == "QUALIFIED"
        assert after["qualified_at"] == "2026-08-01T00:00:00Z"
        assert after["version"] == body["version"]
        assert after["dequalified_count"] == 0


class TestBlendLifecycleAndItsLedger:
    """
    A shipped blend opens empty, each draw moves units on two records at once, and
    a quality hold on a lot does not reach into the components already drawn.
    """

    def test_a_new_shipped_blend_opens_in_draft_with_nothing_allocated(
        self, api, clock
    ):
        """
        Only the midpoint is computed at creation; the colour profile waits for compose.

        Section 3.7: "The blend is created DRAFT with allocated_units at 0,
        dye_lot_count at 0, rejection_count at 0, and weighted_color_index,
        color_range_span, panel_delta_e, composed_by_user_id, certified_by_user_id,
        certified_at and rejection_reason all null", with
        target_color_index_midpoint "the mean of the two window bounds". "Opening the
        blend advances the order ASSIGNED to IN_BLENDING ...; the order's
        freight_status is deliberately untouched."

        Design: Corner/state_machines/new_shipped_blend_starts_in_draft_with_zero_allocation
        """
        fx.build_plant_with_assets(api, clock=None)
        order = fx.build_assigned_order(api, requested_units=12000)
        assert order["fulfillment_status"] == "ASSIGNED"
        assert order["freight_status"] == "ESTIMATED"

        blend = validate_success(
            api.create_blend(
                order["id"],
                F.blend_payload(12000, target_color_index_min=48.00, target_color_index_max=54.00),
                BLEND_TECHNICIAN,
            ),
            201,
        )
        assert blend["status"] == "DRAFT"
        assert blend["allocated_units"] == 0
        assert blend["rejection_count"] == 0
        assert blend["dye_lot_count"] == 0
        assert blend["weighted_color_index"] is None
        assert blend["color_range_span"] is None
        assert blend["panel_delta_e"] is None
        assert blend["composed_by_user_id"] is None
        assert blend["certified_by_user_id"] is None
        assert blend["certified_at"] is None
        assert blend["rejection_reason"] is None
        assert blend["target_color_index_midpoint"] == 51.00
        assert blend["version"] == 1

        moved = validate_success(api.get_order(order["id"], SALES_REP))
        assert moved["fulfillment_status"] == "IN_BLENDING"
        assert moved["freight_status"] == "ESTIMATED"

    def test_one_draw_moves_the_blend_ledger_and_the_lot_ledger_together(
        self, api, clock
    ):
        """
        4000 units leave available_units and appear in reserved_units in one request.

        Section 3.7: "The drawn units move out of the lot's available_units into its
        reserved_units, moving the lot AVAILABLE to RESERVED; the blend's
        allocated_units is recomputed as the sum of units over its ALLOCATED
        components; and the blend's version is incremented by 1", with
        color_index_at_allocation snapshotting the lot's colour and
        contribution_index being that colour "multiplied by units".

        Design: Corner/state_machines/blend_component_add_syncs_blend_allocated_units_and_lot_reservation
        """
        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        assert lot["available_units"] == 9600
        assert lot["reserved_units"] == 0
        assert lot["status"] == "AVAILABLE"

        order = fx.build_assigned_order(api, requested_units=9600)
        blend = fx.create_blend(api, order["id"], 9600)
        assert blend["version"] == 1

        after = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 4000, blend["version"]),
                BLEND_TECHNICIAN,
            )
        )
        assert after["allocated_units"] == 4000
        assert after["version"] == 2

        lot_after = validate_success(api.get_fired_lot(lot["id"], BLEND_TECHNICIAN))
        assert lot_after["reserved_units"] == 4000
        assert lot_after["available_units"] == 5600
        assert lot_after["consumed_units"] == 0
        assert lot_after["status"] == "RESERVED"

        components = validate_success(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert len(components) == 1
        assert components[0]["status"] == "ALLOCATED"
        assert components[0]["units"] == 4000
        assert components[0]["source"] == "MANUAL"
        assert components[0]["color_index_at_allocation"] == 52.18
        assert components[0]["contribution_index"] == 208720.00

    def test_a_quality_hold_freezes_the_reservation_and_only_bites_at_certify(
        self, api, clock
    ):
        """
        Quarantine leaves the components ALLOCATED and the blend COMPOSED, then blocks certify.

        Section 3.4: "Quarantining a RESERVED lot leaves its existing ALLOCATED
        components untouched - the units stay reserved - but the blend holding them
        can no longer be certified", and "any attempt to draw on it, compose or
        certify a blend that holds it, or approve a panel built from it is rejected
        with ERR_LOT_QUARANTINED."

        Design: Corner/state_machines/quarantining_a_reserved_lot_leaves_its_components_allocated
        """
        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        order = fx.build_assigned_order(api, requested_units=9600)
        blend = fx.build_composed_blend(api, order, [(lot["id"], 9600)])
        assert blend["status"] == "COMPOSED"
        assert blend["allocated_units"] == 9600

        reason = "Efflorescence found on the top course of the sample panel"
        held = validate_success(
            api.quarantine_fired_lot(
                lot["id"], F.quarantine_payload(reason), QUALITY_MANAGER
            )
        )
        assert held["status"] == "QUARANTINED"
        assert held["quarantine_reason"] == reason
        assert held["reserved_units"] == 9600
        assert held["available_units"] == 0

        components = validate_success(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert [c["status"] for c in components] == ["ALLOCATED"]
        assert components[0]["units"] == 9600

        unchanged = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert unchanged["status"] == "COMPOSED"
        assert unchanged["allocated_units"] == 9600

        validate_error(
            api.certify_blend(blend["id"], QUALITY_MANAGER),
            ERR_LOT_QUARANTINED,
            409,
        )


class TestTerminalStatesAreLockedDown:
    """
    Section 3.8 makes DELIVERED and INVOICED terminal, and cancellation is legal
    only "at any point before delivery".
    """

    def test_a_delivered_order_refuses_cancellation_and_records_no_reason(
        self, api, clock
    ):
        """
        Delivery consumes the inventory; the cancel that follows changes nothing.

        Section 3.8: delivery "stamps delivered_at and invoiced_at from the logical
        clock, advances fulfillment_status PACKAGED to DELIVERED and freight_status
        FINALIZED to INVOICED in the same request", moving "the shipped blend
        CERTIFIED to RELEASED, which moves every ALLOCATED blend component to
        CONSUMED, which in turn shifts each referenced lot's units out of
        reserved_units and into consumed_units". "Cancelling a DELIVERED or already
        CANCELLED order is rejected with ERR_ORDER_STATE_INVALID."

        Design: Corner/state_machines/delivered_order_cannot_be_cancelled
        """
        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        order = fx.build_assigned_order(api, requested_units=9600)
        blend = fx.build_certified_blend(api, order, [(lot["id"], 9600)])
        assert blend["status"] == "CERTIFIED"

        packaged = fx.package_order(api, order["id"], 20, 40)
        assert packaged["fulfillment_status"] == "PACKAGED"
        assert packaged["estimated_freight_cents"] == 56881
        assert packaged["final_freight_cents"] == 58619
        assert packaged["freight_variance_cents"] == 1738

        delivered = validate_success(
            api.deliver_order(order["id"], F.deliver_payload(), LOGISTICS_COORDINATOR)
        )
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["freight_status"] == "INVOICED"
        assert delivered["delivered_at"] == "2026-08-01T00:00:00Z"
        assert delivered["invoiced_at"] == "2026-08-01T00:00:00Z"

        released = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert released["status"] == "RELEASED"
        components = validate_success(
            api.list_blend_components(blend["id"], BLEND_TECHNICIAN)
        )
        assert [c["status"] for c in components] == ["CONSUMED"]

        consumed_lot = validate_success(api.get_fired_lot(lot["id"], BLEND_TECHNICIAN))
        assert consumed_lot["status"] == "CONSUMED"
        assert consumed_lot["consumed_units"] == 9600
        assert consumed_lot["reserved_units"] == 0
        assert consumed_lot["available_units"] == 0

        validate_error(
            api.cancel_order(order["id"], F.cancel_payload("Elevation changed"), SALES_REP),
            ERR_ORDER_STATE_INVALID,
            409,
        )
        after = validate_success(api.get_order(order["id"], SALES_REP))
        assert after["fulfillment_status"] == "DELIVERED"
        assert after["freight_status"] == "INVOICED"
        assert after["cancellation_reason"] is None
