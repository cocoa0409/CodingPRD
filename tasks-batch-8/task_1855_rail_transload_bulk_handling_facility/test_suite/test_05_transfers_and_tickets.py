"""Transfer orders: activation gates, pause/resume cycles, equipment
provenance, contamination scoring, weight-ticket certify/void gates and the
auto-complete cascade."""
from test_helpers import (
    ApiErrorId,
    assert_lot_quantity_invariant,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    BILLING,
    OPERATOR,
    SAFETY,
    YARD,
    arrive_car,
    certify_ticket,
    create_customer,
    create_draft_ticket,
    create_equipment,
    create_facility,
    create_incident,
    create_lot,
    create_product,
    create_railcar,
    create_spot_order_for_car,
    create_track,
    create_transfer_for,
    execute_spot_order,
    get_equipment,
    get_lot,
    get_railcar,
    get_transfer_order,
    schedule_spot_order,
    set_clock,
    setup_active_transfer,
    setup_spotted_car,
)


def _spotted_with_planned_transfer(api, *, planned=10.0, loaded=40.0,
                                   car_number="96401"):
    """Facility + spotted car + PLANNED transfer order on one equipment."""
    ctx = setup_spotted_car(quantity_loaded_tons=loaded, car_number=car_number)
    eq = create_equipment(name="CONV-1", equipment_type="CONVEYOR")
    to = create_transfer_for(ctx["car"]["id"], eq["id"], planned)
    ctx["equipment"] = eq
    ctx["transfer"] = to
    return ctx


class TestTransferOrderEdges:
    def test_transfer_order_edges_rejected(self, api):
        """PRD §3.5: "Pausing moves an `ACTIVE` order to `PAUSED`" and
        "Cancellation applies from `PLANNED` or `PAUSED` and moves the order to
        `CANCELLED`, bumping its version."
        PRD §3.5: "A manual complete requires `quantity_completed_tons` greater
        than zero (`ERR_NOTHING_TO_COMPLETE`)."
        PRD §2.9: "5. State — the entity is in a from-state that lists this
        trigger (`ERR_INVALID_STATE`, 409); this also covers acting on terminal
        states."

        Design: Corner/state_machines/transfer_order_edges_rejected
        """
        ctx = _spotted_with_planned_transfer(api)
        to_id = ctx["transfer"]["id"]

        # pause from PLANNED
        validate_error(api.pause_transfer_order(to_id, OPERATOR),
                       ApiErrorId.ERR_INVALID_STATE)

        activated = validate_success(api.activate_transfer_order(to_id, OPERATOR))
        assert activated["status"] == "ACTIVE"

        # cancel from ACTIVE
        validate_error(api.cancel_transfer_order(to_id, OPERATOR),
                       ApiErrorId.ERR_INVALID_STATE)

        paused = validate_success(api.pause_transfer_order(to_id, OPERATOR))
        assert paused["status"] == "PAUSED"

        # manual complete with zero certified quantity
        validate_error(api.complete_transfer_order(to_id, OPERATOR),
                       ApiErrorId.ERR_NOTHING_TO_COMPLETE)

        cancelled = validate_success(api.cancel_transfer_order(to_id, OPERATOR))
        assert cancelled["status"] == "CANCELLED"

        # CANCELLED is terminal for activate
        validate_error(api.activate_transfer_order(to_id, OPERATOR),
                       ApiErrorId.ERR_INVALID_STATE)


class TestActivationGates:
    def test_transfer_activation_gates_rejected(self, api):
        """PRD §3.5: "The gates: the car's `placement_status` must be `SPOTTED`
        or `IN_TRANSFER` (`ERR_CAR_NOT_SPOTTED`); the car's `hold_status` must
        be `NONE` (`ERR_CAR_HELD`); the facility must not be `SUSPENDED`
        (`ERR_FACILITY_SUSPENDED`); if the facility is `ELEVATED` and the
        lading product is `HAZARDOUS`, activation is blocked
        (`ERR_POSTURE_ELEVATED_HAZMAT`); the equipment must be `AVAILABLE`
        (`ERR_EQUIPMENT_NOT_AVAILABLE`); no other transfer order may be
        `ACTIVE` on the same railcar (`ERR_CAR_BUSY`); no other `ACTIVE`
        transfer order may be using the same equipment
        (`ERR_EQUIPMENT_NOT_AVAILABLE`); the contamination risk score must be
        below the block threshold (`ERR_CONTAMINATION_RISK`); and the
        customer's `credit_standing` must not be `CREDIT_HOLD`
        (`ERR_CREDIT_HOLD`)."
        PRD §2.6: "While `ELEVATED`, activating a transfer whose lading product
        has `hazard_class` `HAZARDOUS` is blocked with
        `ERR_POSTURE_ELEVATED_HAZMAT`."

        Design: Corner/state_machines/transfer_activation_gates_rejected
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-S10")
        cust = create_customer(name="C1", allocated_car_spots=6)
        prod = create_product(name="Acid", hazard_class="HAZARDOUS",
                              segregation_group="CHEMICAL",
                              requires_full_clean=False)
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        eq1 = create_equipment(name="PUMP-1", equipment_type="PUMP")
        eq2 = create_equipment(name="PUMP-2", equipment_type="PUMP")
        car1 = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                         car_number="96501")["id"])
        car2 = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                         car_number="96502")["id"])
        so1 = create_spot_order_for_car(car1["id"], trk["id"], 1,
                                        "2026-08-03T01:00:00Z",
                                        "2026-08-03T02:00:00Z")
        so2 = create_spot_order_for_car(car2["id"], trk["id"], 2,
                                        "2026-08-03T02:30:00Z",
                                        "2026-08-03T03:30:00Z")
        schedule_spot_order(so1["id"])
        schedule_spot_order(so2["id"])
        set_clock("2026-08-03T01:30:00Z")
        execute_spot_order(so1["id"])
        set_clock("2026-08-03T03:00:00Z")
        execute_spot_order(so2["id"])

        to1 = create_transfer_for(car1["id"], eq1["id"], 10.0)
        to2 = create_transfer_for(car1["id"], eq2["id"], 5.0)
        to3 = create_transfer_for(car2["id"], eq1["id"], 5.0)
        get_success_data(api.activate_transfer_order(to1["id"], OPERATOR))

        # Second ACTIVE order on the same car
        validate_error(api.activate_transfer_order(to2["id"], OPERATOR),
                       ApiErrorId.ERR_CAR_BUSY)
        # Equipment already IN_USE by TO1
        validate_error(api.activate_transfer_order(to3["id"], OPERATOR),
                       ApiErrorId.ERR_EQUIPMENT_NOT_AVAILABLE)

        # Free the car, then take EQ2 into CLEANING: still not AVAILABLE
        get_success_data(api.pause_transfer_order(to1["id"], OPERATOR))
        get_success_data(api.start_equipment_cleaning(eq2["id"], OPERATOR))
        validate_error(api.activate_transfer_order(to2["id"], OPERATOR),
                       ApiErrorId.ERR_EQUIPMENT_NOT_AVAILABLE)
        get_success_data(api.finish_equipment_cleaning(eq2["id"], OPERATOR))

        # ELEVATED posture (one open MINOR incident) blocks HAZARDOUS lading
        inc = create_incident(severity="MINOR", description="spill")
        validate_error(api.activate_transfer_order(to2["id"], OPERATOR),
                       ApiErrorId.ERR_POSTURE_ELEVATED_HAZMAT)
        get_success_data(api.resolve_incident(inc["id"], SAFETY))

        # CREDIT_HOLD blocks activation
        get_success_data(
            api.patch_customer(cust["id"], {"credit_standing": "CREDIT_HOLD"}, ADMIN)
        )
        validate_error(api.activate_transfer_order(to2["id"], OPERATOR),
                       ApiErrorId.ERR_CREDIT_HOLD)

        # Restored credit: activation succeeds
        get_success_data(
            api.patch_customer(cust["id"], {"credit_standing": "GOOD_STANDING"}, ADMIN)
        )
        ok = validate_success(api.activate_transfer_order(to2["id"], OPERATOR))
        assert ok["status"] == "ACTIVE"


class TestCertifyGates:
    def test_ticket_certify_gates_rejected(self, api):
        """PRD §3.6: "Certification is the moment money and material move, and
        it is gated in this order: the parent transfer order must be `ACTIVE`
        (`ERR_INVALID_STATE`); the `tare_weight_tons` must be strictly less
        than the `gross_weight_tons` (`ERR_SCALE_TOLERANCE`); the
        `net_weight_tons` must not exceed `truck_max_payload_tons`
        (`ERR_PAYLOAD_EXCEEDED`); the order's `quantity_completed_tons` plus
        this net must not exceed `quantity_planned_tons` (`ERR_OVER_DELIVERY`);
        and the railcar's `quantity_remaining_tons` must be at least the net
        (`ERR_OVER_DELIVERY`)."
        PRD §3.6: "Voiding reverses a certification exactly, and is allowed
        only while the parent order is `ACTIVE` or `PAUSED` (else
        `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/ticket_certify_gates_rejected
        """
        ctx = setup_active_transfer(quantity_planned_tons=50.0,
                                    quantity_loaded_tons=40.0,
                                    car_number="96601")
        to_id = ctx["transfer"]["id"]

        wt_a = create_draft_ticket(to_id, 25.0, 14.0, 40.0, "TRK-A")   # net 11
        wt_b = create_draft_ticket(to_id, 44.0, 14.0, 40.0, "TRK-B")   # net 30
        wt_c = create_draft_ticket(to_id, 10.0, 15.0, 40.0, "TRK-C")   # tare>gross
        wt_d = create_draft_ticket(to_id, 65.0, 14.0, 60.0, "TRK-D")   # net 51

        # A DRAFT ticket cannot be voided (only CERTIFIED tickets void)
        validate_error(api.void_weight_ticket(wt_c["id"], OPERATOR),
                       ApiErrorId.ERR_INVALID_STATE)

        # tare >= gross
        validate_error(api.certify_weight_ticket(wt_c["id"], OPERATOR),
                       ApiErrorId.ERR_SCALE_TOLERANCE)

        # completed (0) + net (51) > planned (50)
        validate_error(api.certify_weight_ticket(wt_d["id"], OPERATOR),
                       ApiErrorId.ERR_OVER_DELIVERY)

        ok = validate_success(api.certify_weight_ticket(wt_a["id"], OPERATOR))
        assert ok["status"] == "CERTIFIED"
        assert get_transfer_order(to_id)["quantity_completed_tons"] == 11.0
        assert get_railcar(ctx["car"]["id"])["quantity_remaining_tons"] == 29.0

        # net (30) exceeds the car's remaining (29)
        validate_error(api.certify_weight_ticket(wt_b["id"], OPERATOR),
                       ApiErrorId.ERR_OVER_DELIVERY)

        # certify requires the order ACTIVE — paused order rejects
        get_success_data(api.pause_transfer_order(to_id, OPERATOR))
        validate_error(api.certify_weight_ticket(wt_b["id"], OPERATOR),
                       ApiErrorId.ERR_INVALID_STATE)


class TestPayloadBoundary:
    def test_certify_net_equal_to_payload_accepted(self, api):
        """PRD §3.6: "the `net_weight_tons` must not exceed
        `truck_max_payload_tons` (`ERR_PAYLOAD_EXCEEDED`)" — net exactly equal
        to the limit does not exceed it.

        Design: Difficulty/boundary_precision_check/payload_exact_vs_over
        """
        ctx = setup_active_transfer(quantity_planned_tons=60.0,
                                    quantity_loaded_tons=60.0,
                                    car_number="90003")
        wt = create_draft_ticket(ctx["transfer"]["id"], gross_weight_tons=40.0,
                                 tare_weight_tons=15.0, truck_max_payload_tons=25.0)
        assert wt["net_weight_tons"] == 25.0
        certified = validate_success(api.certify_weight_ticket(wt["id"], OPERATOR))
        assert certified["status"] == "CERTIFIED"
        assert get_transfer_order(ctx["transfer"]["id"])[
            "quantity_completed_tons"] == 25.0

    def test_certify_net_over_payload_by_millitonne_rejected(self, api):
        """PRD §3.6: "the `net_weight_tons` must not exceed
        `truck_max_payload_tons` (`ERR_PAYLOAD_EXCEEDED`)"
        PRD §2.5: "The net weight of a ticket is its gross weight minus its
        tare weight, rounded to three decimal places with round-half-up."

        Design: Difficulty/boundary_precision_check/payload_exact_vs_over
        """
        ctx = setup_active_transfer(quantity_planned_tons=60.0,
                                    quantity_loaded_tons=60.0,
                                    car_number="90003")
        wt = create_draft_ticket(ctx["transfer"]["id"], gross_weight_tons=40.001,
                                 tare_weight_tons=15.0, truck_max_payload_tons=25.0)
        assert wt["net_weight_tons"] == 25.001
        validate_error(api.certify_weight_ticket(wt["id"], OPERATOR),
                       ApiErrorId.ERR_PAYLOAD_EXCEEDED)
        assert get_transfer_order(ctx["transfer"]["id"])[
            "quantity_completed_tons"] == 0.0, "rejected certify moves nothing"


class TestSpotTransferCycle:
    def test_railcar_cycles_spotted_in_transfer_on_pause(self, api):
        """PRD §3.5: "On successful activation the equipment moves from
        `AVAILABLE` to `IN_USE` and its `last_product_id` is set to the car's
        lading product (bumping `Equipment.version`), a car that was `SPOTTED`
        moves to `IN_TRANSFER` (a resumed car is already `IN_TRANSFER`), and
        `TransferOrder.version` increments."
        PRD §3.5: "Pausing moves an `ACTIVE` order to `PAUSED`: the equipment
        returns to `AVAILABLE` (keeping its provenance `last_product_id`) and
        the railcar returns from `IN_TRANSFER` to `SPOTTED`, both versions
        bumping alongside the order's."

        Design: Difficulty/non_linear_state_machine/railcar_spot_transfer_cycle
        """
        ctx = _spotted_with_planned_transfer(api, planned=40.0, loaded=80.0,
                                             car_number="60001")
        to_id = ctx["transfer"]["id"]
        eq = ctx["equipment"]

        activated = validate_success(api.activate_transfer_order(to_id, OPERATOR))
        assert activated["status"] == "ACTIVE"
        assert get_railcar(ctx["car"]["id"])["placement_status"] == "IN_TRANSFER"

        paused = validate_success(api.pause_transfer_order(to_id, OPERATOR))
        assert paused["status"] == "PAUSED"
        assert get_railcar(ctx["car"]["id"])["placement_status"] == "SPOTTED"
        assert get_equipment(eq["id"])["status"] == "AVAILABLE"

    def test_railcar_resume_returns_to_in_transfer(self, api):
        """PRD §3.5: "Activation — moving the order from `PLANNED` to
        `ACTIVE`, and likewise resuming from `PAUSED` to `ACTIVE` with the same
        gate set and the same side effects — is the contamination-controlled
        moment."

        Design: Difficulty/non_linear_state_machine/railcar_spot_transfer_cycle
        """
        ctx = _spotted_with_planned_transfer(api, planned=40.0, loaded=80.0,
                                             car_number="60001")
        to_id = ctx["transfer"]["id"]
        get_success_data(api.activate_transfer_order(to_id, OPERATOR))
        get_success_data(api.pause_transfer_order(to_id, OPERATOR))

        resumed = validate_success(api.activate_transfer_order(to_id, OPERATOR))
        assert resumed["status"] == "ACTIVE", "PAUSED -> ACTIVE resume"
        assert get_railcar(ctx["car"]["id"])["placement_status"] == "IN_TRANSFER"
        assert get_equipment(ctx["equipment"]["id"])["status"] == "IN_USE"


class TestEquipmentCycle:
    def test_equipment_provenance_persists_while_idle(self, api):
        """PRD §3.1: "The `last_product_id` is a provenance pointer to the
        last commodity the line handled: it is stamped when a transfer
        activates, persists while the line sits idle, and is cleared only when
        the line finishes a cleaning."

        Design: Difficulty/non_linear_state_machine/equipment_use_clean_cycle
        """
        ctx = _spotted_with_planned_transfer(api, car_number="60002")
        eq = ctx["equipment"]
        prod = ctx["product"]

        get_success_data(api.activate_transfer_order(ctx["transfer"]["id"], OPERATOR))
        in_use = get_equipment(eq["id"])
        assert in_use["status"] == "IN_USE"
        assert in_use["last_product_id"] == prod["id"]

        get_success_data(api.pause_transfer_order(ctx["transfer"]["id"], OPERATOR))
        idle = get_equipment(eq["id"])
        assert idle["status"] == "AVAILABLE"
        assert idle["last_product_id"] == prod["id"], "provenance persists while idle"

    def test_equipment_cleaning_clears_provenance(self, api):
        """PRD §3.1: "A `TransferOperator` may start cleaning on an
        `AVAILABLE` line (moving it to `CLEANING`) and finish cleaning
        (returning it to `AVAILABLE` and nulling `last_product_id`)."

        Design: Difficulty/non_linear_state_machine/equipment_use_clean_cycle
        """
        ctx = _spotted_with_planned_transfer(api, car_number="60002")
        eq = ctx["equipment"]

        get_success_data(api.activate_transfer_order(ctx["transfer"]["id"], OPERATOR))
        get_success_data(api.pause_transfer_order(ctx["transfer"]["id"], OPERATOR))

        cleaning = validate_success(api.start_equipment_cleaning(eq["id"], OPERATOR))
        assert cleaning["status"] == "CLEANING"

        finished = validate_success(api.finish_equipment_cleaning(eq["id"], OPERATOR))
        assert finished["status"] == "AVAILABLE"
        assert finished["last_product_id"] is None, "cleaning clears provenance"


class TestActivateRequiresSpotted:
    def test_activate_rejected_while_car_arrived(self, api):
        """PRD §3.5: "The gates: the car's `placement_status` must be
        `SPOTTED` or `IN_TRANSFER` (`ERR_CAR_NOT_SPOTTED`)"

        Design: Difficulty/cross_entity_state_dependency/activate_requires_car_spotted
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-X1")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=1)
        eq = create_equipment(name="PUMP-1", equipment_type="PUMP")
        car = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="91001")["id"]
        )
        so = create_spot_order_for_car(car["id"], trk["id"], 1,
                                       "2026-08-03T01:00:00Z",
                                       "2026-08-03T05:00:00Z")
        schedule_spot_order(so["id"])
        set_clock("2026-08-03T02:00:00Z")
        to = create_transfer_for(car["id"], eq["id"], 10.0)

        validate_error(api.activate_transfer_order(to["id"], OPERATOR),
                       ApiErrorId.ERR_CAR_NOT_SPOTTED)
        assert get_transfer_order(to["id"])["status"] == "PLANNED"
        assert get_equipment(eq["id"])["status"] == "AVAILABLE", (
            "rejected activation must not acquire equipment"
        )

    def test_activate_succeeds_after_spot_execution(self, api):
        """PRD §3.4: "Execution drives the railcar from `ARRIVED` to
        `SPOTTED`"
        PRD §3.5: "The gates: the car's `placement_status` must be `SPOTTED`
        or `IN_TRANSFER` (`ERR_CAR_NOT_SPOTTED`)" and "On successful activation
        the equipment moves from `AVAILABLE` to `IN_USE` and its
        `last_product_id` is set to the car's lading product (bumping
        `Equipment.version`), a car that was `SPOTTED` moves to `IN_TRANSFER`
        (a resumed car is already `IN_TRANSFER`), and `TransferOrder.version`
        increments."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_car_spotted
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-X1")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=1)
        eq = create_equipment(name="PUMP-1", equipment_type="PUMP")
        car = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="91001")["id"]
        )
        so = create_spot_order_for_car(car["id"], trk["id"], 1,
                                       "2026-08-03T01:00:00Z",
                                       "2026-08-03T05:00:00Z")
        schedule_spot_order(so["id"])
        set_clock("2026-08-03T02:00:00Z")
        to = create_transfer_for(car["id"], eq["id"], 10.0)

        execute_spot_order(so["id"])
        assert get_railcar(car["id"])["placement_status"] == "SPOTTED"

        activated = validate_success(api.activate_transfer_order(to["id"], OPERATOR))
        assert activated["status"] == "ACTIVE"
        assert get_railcar(car["id"])["placement_status"] == "IN_TRANSFER"


class TestContaminationVariants:
    def _contamination_setup(self, api):
        """Car1 (CHEMICAL group) and car2 (PETROLEUM group) spotted; the
        shared pump's provenance is the CHEMICAL product. Returns context."""
        set_clock("2026-08-03T00:00:00Z")
        fac = create_facility(name="FT-CT")
        cust = create_customer(name="C1", allocated_car_spots=10)
        prod_chem = create_product(name="Solvent", hazard_class="NON_HAZARDOUS",
                                   segregation_group="CHEMICAL",
                                   requires_full_clean=False)
        prod_petr = create_product(name="LubeOil", hazard_class="NON_HAZARDOUS",
                                   segregation_group="PETROLEUM",
                                   requires_full_clean=False)
        lot1 = create_lot(cust["id"], prod_chem["id"])
        lot2 = create_lot(cust["id"], prod_petr["id"])
        trk = create_track(name="T1", spot_capacity=2)
        eq = create_equipment(name="PUMP-1", equipment_type="PUMP")
        car1 = arrive_car(create_railcar(cust["id"], prod_chem["id"], lot1["id"],
                                         car_number="20001",
                                         quantity_loaded_tons=60.0)["id"])
        car2 = arrive_car(create_railcar(cust["id"], prod_petr["id"], lot2["id"],
                                         car_number="20002",
                                         quantity_loaded_tons=60.0)["id"])
        so1 = create_spot_order_for_car(car1["id"], trk["id"], 1,
                                        "2026-08-03T01:00:00Z",
                                        "2026-08-03T02:00:00Z")
        so2 = create_spot_order_for_car(car2["id"], trk["id"], 2,
                                        "2026-08-03T02:30:00Z",
                                        "2026-08-03T03:30:00Z")
        schedule_spot_order(so1["id"])
        schedule_spot_order(so2["id"])
        set_clock("2026-08-03T01:30:00Z")
        execute_spot_order(so1["id"])
        set_clock("2026-08-03T03:00:00Z")
        execute_spot_order(so2["id"])
        to1 = create_transfer_for(car1["id"], eq["id"], 30.0)
        get_success_data(api.activate_transfer_order(to1["id"], OPERATOR))
        get_success_data(api.pause_transfer_order(to1["id"], OPERATOR))
        to2 = create_transfer_for(car2["id"], eq["id"], 30.0)
        return {"facility": fac, "car2": car2, "equipment": eq, "to2": to2}

    def test_contamination_strict_matrix_blocks_group_mismatch(self, api):
        """PRD §3.5: "Under the facility's `STRICT_MATRIX` policy, any group
        mismatch scores 100; no mismatch scores 0." and "Activation is allowed
        exactly when the score is strictly below the block threshold of 100; a
        score of 100 or more is rejected with `ERR_CONTAMINATION_RISK`."

        Design: Difficulty/dual_variant_calc/contamination_strict_vs_weighted_policy
        """
        ctx = self._contamination_setup(api)
        validate_error(api.activate_transfer_order(ctx["to2"]["id"], OPERATOR),
                       ApiErrorId.ERR_CONTAMINATION_RISK)
        assert get_transfer_order(ctx["to2"]["id"])["status"] == "PLANNED"

    def test_contamination_weighted_score_allows_below_threshold(self, api):
        """PRD §3.5: "Under the `WEIGHTED_SCORE` policy, the score is 60 times
        the group-mismatch signal plus 25 times the hazard-escalation signal
        plus 15 times the food-involvement signal — so, for example, a
        `CHEMICAL` line feeding a `PETROLEUM` car (non-food, non-hazardous on
        both sides) scores 60." and "Activation is allowed exactly when the
        score is strictly below the block threshold of 100"
        PRD §3.5: "The contamination risk score is computed at activation
        against the equipment's `last_product_id` and the incoming car's lading
        product, and stored on the order as `risk_score` (an integer from 0 to
        100)."

        Design: Difficulty/dual_variant_calc/contamination_strict_vs_weighted_policy
        """
        ctx = self._contamination_setup(api)
        # Same mismatch is allowed once the facility uses WEIGHTED_SCORE
        get_success_data(
            api.patch_facility(ctx["facility"]["id"],
                               {"contamination_policy": "WEIGHTED_SCORE"}, ADMIN)
        )
        activated = validate_success(
            api.activate_transfer_order(ctx["to2"]["id"], OPERATOR)
        )
        assert activated["status"] == "ACTIVE"
        assert activated["risk_score"] == 60, (
            "60*1 group mismatch + 25*0 hazard + 15*0 food"
        )
        assert get_equipment(ctx["equipment"]["id"])["status"] == "IN_USE"
        assert get_railcar(ctx["car2"]["id"])["placement_status"] == "IN_TRANSFER"


class TestCertifyAutoCompleteCascade:
    def _autocomplete_setup(self, api):
        ctx = setup_active_transfer(quantity_planned_tons=20.0,
                                    quantity_loaded_tons=20.0,
                                    car_number="70002")
        wt = create_draft_ticket(ctx["transfer"]["id"], gross_weight_tons=34.0,
                                 tare_weight_tons=14.0, truck_max_payload_tons=40.0)
        ctx["ticket"] = wt
        return ctx

    def test_certify_auto_completes_order_at_planned(self, api):
        """PRD §3.6: "if the order's completed quantity has reached the
        planned quantity, the order auto-completes with all the completion side
        effects of §3.5"
        PRD §3.5: "Completing from `ACTIVE` releases the equipment (`IN_USE`
        to `AVAILABLE`)"

        Design: Difficulty/transitive_cascade/certify_autocomplete_cascade_depth3
        """
        ctx = self._autocomplete_setup(api)
        certified = validate_success(api.certify_weight_ticket(ctx["ticket"]["id"],
                                                               OPERATOR))
        assert certified["status"] == "CERTIFIED"

        to = get_transfer_order(ctx["transfer"]["id"])
        assert to["status"] == "COMPLETED", "auto-completed at planned quantity"
        assert to["quantity_completed_tons"] == 20.0
        assert get_equipment(ctx["equipment"]["id"])["status"] == "AVAILABLE", (
            "equipment released by the auto-completion"
        )

    def test_certify_empty_car_advances_to_ready_for_release(self, api):
        """PRD §3.6: "and if the car's remaining quantity has reached exactly
        zero, the car moves from `IN_TRANSFER` to `EMPTY_AWAITING_CLEANING` —
        continuing to `READY_FOR_RELEASE` at the same instant when the product
        does not require a full clean."
        PRD §3.6: "the lot's `quantity_shipped_tons` increases by the net with
        `quantity_on_hand_tons` recomputed"

        Design: Difficulty/transitive_cascade/certify_autocomplete_cascade_depth3
        """
        ctx = self._autocomplete_setup(api)
        validate_success(api.certify_weight_ticket(ctx["ticket"]["id"], OPERATOR))

        car = get_railcar(ctx["car"]["id"])
        assert car["quantity_remaining_tons"] == 0.0
        assert car["placement_status"] == "READY_FOR_RELEASE", (
            "EMPTY_AWAITING_CLEANING auto-advanced: product needs no full clean"
        )
        lot = get_lot(ctx["lot"]["id"])
        assert lot["quantity_shipped_tons"] == 20.0
        assert lot["quantity_on_hand_tons"] == 0.0
        assert_lot_quantity_invariant(lot)


class TestCertifyVoidInvariant:
    def _certified_setup(self, api):
        ctx = setup_active_transfer(quantity_planned_tons=40.0,
                                    quantity_loaded_tons=80.0,
                                    car_number="94001")
        wt = create_draft_ticket(ctx["transfer"]["id"], gross_weight_tons=24.0,
                                 tare_weight_tons=14.0, truck_max_payload_tons=40.0)
        ctx["ticket"] = wt
        return ctx

    def test_certify_moves_tonnage_to_shipped(self, api):
        """PRD §3.6: "On certification, three quantity ledgers move together:
        the order's `quantity_completed_tons` increases by the net (bumping
        `TransferOrder.version`), the car's `quantity_remaining_tons` decreases
        by the net (bumping `Railcar.version`), and the lot's
        `quantity_shipped_tons` increases by the net with `quantity_on_hand_tons`
        recomputed (bumping `InventoryLot.version`)."
        PRD §3.2: "`quantity_on_hand_tons` is always the received quantity
        minus the shipped quantity minus the rejected quantity."

        Design: Difficulty/compensating_invariant/ticket_certify_void_inventory_invariant
        """
        ctx = self._certified_setup(api)
        certify_ticket(ctx["ticket"]["id"])

        lot = get_lot(ctx["lot"]["id"])
        assert lot["quantity_received_tons"] == 80.0
        assert lot["quantity_shipped_tons"] == 10.0
        assert lot["quantity_on_hand_tons"] == 70.0
        assert_lot_quantity_invariant(lot)
        assert get_railcar(ctx["car"]["id"])["quantity_remaining_tons"] == 70.0
        assert get_transfer_order(ctx["transfer"]["id"])[
            "quantity_completed_tons"] == 10.0

    def test_void_restores_all_quantity_ledgers(self, api):
        """PRD §3.6: "The order's completed quantity decreases by the voided
        net, the car's remaining quantity increases by it, and the lot's
        shipped quantity decreases by it with on-hand recomputed — certify plus
        void restores all three quantities exactly. The ticket moves from
        `CERTIFIED` to `VOIDED`, bumping its version."

        Design: Difficulty/compensating_invariant/ticket_certify_void_inventory_invariant
        """
        ctx = self._certified_setup(api)
        certify_ticket(ctx["ticket"]["id"])

        voided = validate_success(api.void_weight_ticket(ctx["ticket"]["id"], OPERATOR))
        assert voided["status"] == "VOIDED"

        lot = get_lot(ctx["lot"]["id"])
        assert lot["quantity_received_tons"] == 80.0
        assert lot["quantity_shipped_tons"] == 0.0
        assert lot["quantity_on_hand_tons"] == 80.0
        assert lot["quantity_rejected_tons"] == 0.0
        assert_lot_quantity_invariant(lot)
        assert get_railcar(ctx["car"]["id"])["quantity_remaining_tons"] == 80.0
        assert get_transfer_order(ctx["transfer"]["id"])[
            "quantity_completed_tons"] == 0.0
