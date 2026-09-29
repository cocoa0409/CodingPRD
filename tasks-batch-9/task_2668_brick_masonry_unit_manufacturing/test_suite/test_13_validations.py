"""
Rejections: the order they are reported in, the invariants they protect, and the
cases where the same rule accepts instead of refusing.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BLEND_OVER_ALLOCATION,
    ERR_CLAY_RESERVE_INSUFFICIENT,
    ERR_DURABILITY_GRADE_NOT_MET,
    ERR_INVALID_REQUEST,
    ERR_MISSING_AUTH_HEADERS,
    ERR_PANEL_NOT_APPROVED,
    ERR_PANEL_STATE_INVALID,
    ERR_ROLE_NOT_PERMITTED,
    ERR_UNKNOWN_ROLE,
    ERR_UNLOADING_EQUIPMENT_MISMATCH,
    ERR_UNLOADING_EQUIPMENT_UNAVAILABLE,
)
from test_helpers.test_users import (
    ARCHITECT_REVIEWER,
    BLEND_TECHNICIAN,
    LOGISTICS_COORDINATOR,
    NO_AUTH,
    PLANT_ADMIN,
    QUALITY_MANAGER,
    SALES_REP,
    UNKNOWN_ROLE,
)


class TestTheRejectionLadder:
    """
    Section 2.5 ranks authentication above authorisation and both above payload
    validation, so one malformed request reports four different errors depending
    only on who sends it.
    """

    def test_the_same_bad_payload_reports_auth_then_role_then_the_payload(
        self, api, clock
    ):
        """
        Missing headers, then an unknown role, then a forbidden role, then the 400.

        Section 2.3 and section 5: ERR_MISSING_AUTH_HEADERS and ERR_UNKNOWN_ROLE are
        401, ERR_ROLE_NOT_PERMITTED is 403 and ERR_INVALID_REQUEST is 400; section
        2.5 puts the authentication rules first, the role check next and the payload
        check after both, so the payload error only surfaces for the authorised role.

        Design: Corner/validations/auth_then_role_then_payload_ladder_rejects_missing_auth_and_invalid_role_before_invalid_request
        """
        payload = F.plant_payload(market_radius_miles=None)

        validate_error(api.create_plant(payload, NO_AUTH), ERR_MISSING_AUTH_HEADERS, 401)
        validate_error(api.create_plant(payload, UNKNOWN_ROLE), ERR_UNKNOWN_ROLE, 401)
        validate_error(api.create_plant(payload, SALES_REP), ERR_ROLE_NOT_PERMITTED, 403)
        final = validate_error(
            api.create_plant(payload, PLANT_ADMIN), ERR_INVALID_REQUEST, 400
        )
        assert isinstance(final["message"], str) and final["message"]

        rows, meta = validate_paginated(api.list_plants(PLANT_ADMIN))
        assert meta["total_count"] == 0
        assert rows == []


class TestLedgerGuardsAreAllOrNothing:
    """
    Section 3.3 checks every pit before it debits any pit, and section 3.7 checks
    the aggregate ceiling rather than only the increment in front of it.
    """

    def test_one_short_pit_stops_the_run_and_leaves_the_other_pit_whole(
        self, api, clock
    ):
        """
        A shale pit holding 10.00 tons blocks a run that needs 16.00 from each pit.

        Section 3.3: "Before a single pit is written, the commitment checks that every
        contributing pit's available_tons is at least its own per-pit share. If any
        one pit falls short, the whole run is rejected with
        ERR_CLAY_RESERVE_INSUFFICIENT and no pit is mutated." Qualification itself
        never looks at reserve size, only at pit status and the share total.

        Design: Corner/validations/clay_reserve_check_covers_every_pit_before_any_pit_is_mutated
        """
        plant = fx.create_plant(api)
        clay = fx.create_clay_pit(api, plant["id"], proven_reserve_tons=5000.00)
        shale = fx.create_shale_pit(api, plant["id"], proven_reserve_tons=10.00)
        car = fx.create_kiln_car(api, plant["id"])
        body = fx.build_qualified_formulation(
            api, plant["id"], [(clay["id"], 50.00), (shale["id"], 50.00)]
        )
        assert body["status"] == "QUALIFIED"
        operator = fx.make_plant_operator_headers(plant["id"])

        validate_error(
            api.create_production_run(
                F.production_run_payload(plant["id"], body["id"], car["id"]),
                operator,
            ),
            ERR_CLAY_RESERVE_INSUFFICIENT,
            422,
        )

        pits = validate_success(api.list_clay_pits(plant["id"], PLANT_ADMIN))
        by_type = {p["material_type"]: p for p in pits}
        assert by_type["CLAY"]["available_tons"] == 5000.00
        assert by_type["CLAY"]["committed_tons"] == 0.00
        assert by_type["CLAY"]["status"] == "OPEN"
        assert by_type["SHALE"]["available_tons"] == 10.00
        assert by_type["SHALE"]["committed_tons"] == 0.00

        cars = validate_success(api.list_kiln_cars(plant["id"], PLANT_ADMIN))
        assert cars[0]["status"] == "IDLE"
        assert cars[0]["current_production_run_id"] is None

        runs, meta = validate_paginated(
            api.list_production_runs(PLANT_ADMIN, params={"plant_id": plant["id"]})
        )
        assert meta["total_count"] == 0

    def test_two_legal_draws_that_together_overshoot_the_request_are_refused(
        self, api, clock
    ):
        """
        5000 then 5000 busts a 9600-unit request; 5000 then 4600 fills it exactly.

        Section 3.7: "the resulting allocated_units must not exceed the blend's
        requested_units, or the allocation is rejected with
        ERR_BLEND_OVER_ALLOCATION", so the ceiling is on the running total and is
        inclusive at requested_units. A rejected add neither reserves units nor
        increments the blend's version.

        Design: Corner/validations/individually_valid_component_adds_that_collectively_overshoot_are_rejected
        """
        # Two lots of 9600 units each, so the refused draw is short of nothing but
        # the blend's own ceiling: rule 16 of the ladder (ERR_FIRED_LOT_UNAVAILABLE,
        # "at least as many available_units as the units requested") precedes rule 41,
        # so a draw larger than the lot would mask the over-allocation rule entirely.
        env = fx.build_two_fired_lots(api, clock=None)
        lot = env["lot_one"]
        other = env["lot_two"]
        order = fx.build_assigned_order(api, requested_units=9600)
        blend = fx.create_blend(api, order["id"], 9600)

        first = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 5000, blend["version"]),
                BLEND_TECHNICIAN,
            )
        )
        assert first["allocated_units"] == 5000

        validate_error(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(other["id"], 5000, first["version"]),
                BLEND_TECHNICIAN,
            ),
            ERR_BLEND_OVER_ALLOCATION,
            422,
        )

        after = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert after["allocated_units"] == 5000
        assert after["version"] == first["version"]
        assert after["status"] == "DRAFT"

        held = validate_success(api.get_fired_lot(lot["id"], BLEND_TECHNICIAN))
        assert held["reserved_units"] == 5000
        assert held["available_units"] == 4600

        untouched = validate_success(api.get_fired_lot(other["id"], BLEND_TECHNICIAN))
        assert untouched["reserved_units"] == 0
        assert untouched["available_units"] == 9600

        exact = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(other["id"], 4600, after["version"]),
                BLEND_TECHNICIAN,
            )
        )
        assert exact["allocated_units"] == 9600


class TestDurabilityRankIsAFloor:
    """
    Section 3.5 makes the order's durability_grade "the minimum acceptable"
    weathering grade, which section 3.7 enforces per lot at allocation time.
    """

    def test_an_mw_lot_cannot_serve_an_sw_order(self, api, clock):
        """
        The plant is eligible on its SW body, yet the MW lot itself is refused.

        Section 3.7: "The lot's durability_grade must rank at least as high as the
        order's required durability_grade, or the allocation is rejected with
        ERR_DURABILITY_GRADE_NOT_MET." Section 3.2 puts a body of pure high-iron clay
        at an absorption index of 10.80, which "otherwise an index of 14.00 or less
        grades MW".

        Design: Corner/validations/allocating_an_mw_lot_to_an_sw_order_returns_durability_grade_not_met
        """
        plant = fx.create_plant(api)
        clay = fx.create_clay_pit(api, plant["id"])
        shale = fx.create_shale_pit(api, plant["id"])
        severe = fx.build_qualified_formulation(
            api, plant["id"], [(clay["id"], 50.00), (shale["id"], 50.00)]
        )
        assert severe["absorption_index"] == 8.00
        assert severe["computed_durability_grade"] == "SW"

        moderate = fx.build_qualified_formulation(api, plant["id"], [(clay["id"], 100.00)])
        assert moderate["absorption_index"] == 10.80
        assert moderate["computed_durability_grade"] == "MW"

        kiln = fx.create_kiln(api, plant["id"])
        car = fx.create_kiln_car(api, plant["id"])
        run = fx.build_set_production_run(api, plant, moderate["id"], car["id"])
        kiln_run = fx.create_kiln_run(api, plant["id"], kiln["id"], moderate["id"])
        kiln_run = fx.load_kiln_run(api, plant["id"], kiln_run, run["id"], 3)
        fx.start_kiln_run(api, plant["id"], kiln_run["id"])
        fx.grade_kiln_run(api, plant["id"], kiln_run["id"], 1040, 3.0)
        lot = fx.fired_lots_of_run(api, run["id"])[0]
        assert lot["durability_grade"] == "MW"
        assert lot["color_family"] == "RED"
        assert lot["texture"] == "WIRE_CUT"
        assert lot["color_index"] == 52.18

        order = fx.build_assigned_order(api, requested_units=9600, durability_grade="SW")
        assert order["plant_id"] == plant["id"]
        blend = fx.create_blend(
            api,
            order["id"],
            9600,
            target_color_index_min=48.00,
            target_color_index_max=54.00,
        )

        validate_error(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 9600, blend["version"]),
                BLEND_TECHNICIAN,
            ),
            ERR_DURABILITY_GRADE_NOT_MET,
            422,
        )

        after = validate_success(api.get_blend(blend["id"], BLEND_TECHNICIAN))
        assert after["allocated_units"] == 0
        assert after["version"] == blend["version"]
        untouched = validate_success(api.get_fired_lot(lot["id"], BLEND_TECHNICIAN))
        assert untouched["reserved_units"] == 0
        assert untouched["status"] == "AVAILABLE"

    def test_an_sw_lot_serves_an_mw_order_without_complaint(self, api, clock):
        """
        A grade one rank above the requirement satisfies the floor.

        Section 3.5: "a higher-ranked grade always satisfies a lower-ranked
        requirement, so an SW body can serve an MW order but an MW body cannot serve
        an SW order", and section 3.7 tests rank rather than equality.

        Design: Corner/validations/allocating_an_sw_lot_to_an_mw_order_is_accepted_because_rank_is_a_floor_not_an_equality
        """
        env = fx.build_fired_lot(api, clock=None)
        lot = env["fired_lot"]
        assert env["formulation"]["computed_durability_grade"] == "SW"
        assert lot["durability_grade"] == "SW"

        order = fx.build_assigned_order(api, requested_units=9600, durability_grade="MW")
        blend = fx.create_blend(
            api,
            order["id"],
            9600,
            target_color_index_min=48.00,
            target_color_index_max=54.00,
        )
        allocated = validate_success(
            api.add_blend_component(
                blend["id"],
                F.blend_component_payload(lot["id"], 9600, blend["version"]),
                BLEND_TECHNICIAN,
            )
        )
        assert allocated["allocated_units"] == 9600
        assert allocated["version"] > blend["version"]

        composed = validate_success(
            api.compose_blend(blend["id"], F.compose_payload(False), BLEND_TECHNICIAN)
        )
        assert composed["status"] == "COMPOSED"
        assert composed["weighted_color_index"] == 52.18
        assert composed["color_range_span"] == 0.00
        assert composed["dye_lot_count"] == 1


class TestDeliveryEquipmentChecksAreOrdered:
    """
    Section 3.7 and section 5 give delivery two equipment rules with the fleet
    check ahead of the order-requirement check, so one value can fail either.
    """

    def test_equipment_the_plant_does_not_own_is_reported_before_the_mismatch(
        self, api, clock
    ):
        """
        CUSTOMER_FORKLIFT is unavailable; CRANE is available but mismatched.

        Section 3.8: "Two equipment checks apply in order: the reported equipment
        must be one the assigned plant actually operates ... or the request is
        rejected with ERR_UNLOADING_EQUIPMENT_UNAVAILABLE; and it must equal the
        order's unloading_equipment_required, or the request is rejected with
        ERR_UNLOADING_EQUIPMENT_MISMATCH. Sending a crane to a jobsite that asked
        for a truck-mounted forklift is a failed delivery even when the plant owns
        both." CUSTOMER_FORKLIFT is both absent from the fleet and wrong for the
        order, and the first rule is the one that reports.

        Design: Corner/validations/deliver_reports_equipment_unavailable_before_equipment_mismatch
        """
        env = fx.build_fired_lot(
            api,
            clock=None,
            plant_overrides={
                "unloading_equipment_available": ["TRUCK_MOUNTED_FORKLIFT", "CRANE"]
            },
        )
        lot = env["fired_lot"]
        order = fx.build_assigned_order(
            api, requested_units=9600, unloading_equipment_required="TRUCK_MOUNTED_FORKLIFT"
        )
        assert order["plant_id"] == env["plant"]["id"]
        fx.build_certified_blend(api, order, [(lot["id"], 9600)])

        packaged = validate_success(
            api.package_order(order["id"], F.package_payload(20, 40), LOGISTICS_COORDINATOR)
        )
        assert packaged["fulfillment_status"] == "PACKAGED"
        assert packaged["freight_status"] == "FINALIZED"
        assert packaged["final_freight_cents"] == 58619

        validate_error(
            api.deliver_order(
                order["id"], F.deliver_payload("CUSTOMER_FORKLIFT"), LOGISTICS_COORDINATOR
            ),
            ERR_UNLOADING_EQUIPMENT_UNAVAILABLE,
            422,
        )
        validate_error(
            api.deliver_order(order["id"], F.deliver_payload("CRANE"), LOGISTICS_COORDINATOR),
            ERR_UNLOADING_EQUIPMENT_MISMATCH,
            422,
        )

        midway = validate_success(api.get_order(order["id"], LOGISTICS_COORDINATOR))
        assert midway["fulfillment_status"] == "PACKAGED"
        assert midway["delivered_at"] is None

        delivered = validate_success(
            api.deliver_order(
                order["id"],
                F.deliver_payload("TRUCK_MOUNTED_FORKLIFT"),
                LOGISTICS_COORDINATOR,
            )
        )
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["freight_status"] == "INVOICED"
        assert delivered["delivered_at"] == "2026-08-01T00:00:00Z"

        consumed = validate_success(api.get_fired_lot(lot["id"], BLEND_TECHNICIAN))
        assert consumed["status"] == "CONSUMED"
        assert consumed["consumed_units"] == 9600
        assert consumed["reserved_units"] == 0


class TestPanelApprovalIsConditionalOnTheOrderFlag:
    """
    Section 3.6 and section 3.7 make the panel gate a property of the order, not
    of the blend: the same lot certifies with and without a panel.
    """

    def test_only_the_flagged_order_needs_an_approved_panel(self, api, clock):
        """
        One 11600-unit lot feeds a panel-gated 9600-unit order and a plain 2000-unit one.

        Section 3.7: "If the order's requires_panel_approval is true, the order must
        have a sample panel in status APPROVED (ERR_PANEL_NOT_APPROVED)", and
        panel_delta_e is written only in that case - "when the order did not require
        panel approval, panel_delta_e stays null". Section 3.6 admits submission only
        "from DRAFT or REVISION_REQUESTED" (ERR_PANEL_STATE_INVALID) and pins the
        formulation version, the dye lot code and a 180-day window at approval.
        Section 3.5 adds 7 days to a panel-gated promise: 14 + 7 + ceil(9600/40000)
        is 22 days.

        Design: Corner/validations/panel_approval_rule_applies_only_to_orders_that_request_it
        """
        env = fx.build_fired_lot(api, clock=None, green_units_set=12000, green_loss_units=400)
        lot = env["fired_lot"]
        assert env["production_run"]["net_green_units"] == 11600
        assert lot["fired_units"] == 11600
        assert lot["color_index"] == 52.18

        flagged = fx.build_assigned_order(
            api, requested_units=9600, requires_panel_approval=True
        )
        assert flagged["requires_panel_approval"] is True
        assert flagged["lead_time_days"] == 22

        panel = fx.create_sample_panel(
            api,
            flagged["id"],
            env["formulation"]["id"],
            lot["id"],
            52.00,
            tolerance_delta_e=2.00,
        )
        assert panel["status"] == "DRAFT"
        submitted = validate_success(api.submit_panel(panel["id"], BLEND_TECHNICIAN))
        assert submitted["status"] == "SUBMITTED"

        gated_blend = fx.build_composed_blend(api, flagged, [(lot["id"], 9600)])
        assert gated_blend["status"] == "COMPOSED"
        assert gated_blend["weighted_color_index"] == 52.18
        validate_error(
            api.certify_blend(gated_blend["id"], QUALITY_MANAGER),
            ERR_PANEL_NOT_APPROVED,
            422,
        )

        approved = validate_success(api.approve_panel(panel["id"], ARCHITECT_REVIEWER))
        assert approved["status"] == "APPROVED"
        assert approved["pinned_formulation_version"] == env["formulation"]["version"]
        assert approved["pinned_dye_lot_code"] == lot["dye_lot_code"]
        assert approved["approved_color_index"] == 52.00
        assert approved["expires_at"] == "2027-01-28T00:00:00Z"

        validate_error(
            api.submit_panel(panel["id"], BLEND_TECHNICIAN), ERR_PANEL_STATE_INVALID, 409
        )

        certified = validate_success(
            api.certify_blend(gated_blend["id"], QUALITY_MANAGER)
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["panel_delta_e"] == 0.18
        assert certified["certified_at"] == "2026-08-01T00:00:00Z"

        plain = fx.build_assigned_order(api, requested_units=2000)
        assert plain["requires_panel_approval"] is False
        plain_blend = fx.build_certified_blend(api, plain, [(lot["id"], 2000)])
        assert plain_blend["status"] == "CERTIFIED"
        assert plain_blend["panel_delta_e"] is None
