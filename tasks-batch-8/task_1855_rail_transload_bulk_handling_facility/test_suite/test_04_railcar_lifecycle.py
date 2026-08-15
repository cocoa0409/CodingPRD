"""Railcar lifecycle: the full placement chain, invalid and terminal
transitions, safety holds, derived-counter reconciliation, and immediate
consistency of mutation responses."""
from test_helpers import (
    ApiErrorId,
    assert_lot_quantity_invariant,
    assert_railcar,
    create_railcar_payload,
    create_spot_order_payload,
    create_transfer_order_payload,
    get_success_data,
    validate_error,
    validate_paginated,
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
    create_lot,
    create_product,
    create_railcar,
    create_spot_order_for_car,
    create_track,
    create_transfer_for,
    execute_spot_order,
    get_lot,
    get_railcar,
    get_track,
    list_all_switch_orders,
    schedule_spot_order,
    set_clock,
    setup_ready_for_release_car,
    setup_spotted_car,
)


class TestFullLifecycle:
    def test_railcar_full_lifecycle_happy_path(self, api):
        """PRD §3.3: "Arrival moves the car from `REGISTERED` to `ARRIVED`.
        The `arrival_timestamp` is stamped from the logical clock,
        `quantity_remaining_tons` is initialized to `quantity_loaded_tons`"
        PRD §3.4: "Execution drives the railcar from `ARRIVED` to `SPOTTED`:
        the car's `track_id` and `spot_number` are set from the order,
        `placed_timestamp` is stamped, the track's `occupied_spots` increases
        by one while its `reserved_spots` decreases by one (bumping
        `Track.version`), the linked switch order completes, and the spot
        order's version bumps."
        PRD §3.6: "if the car's remaining quantity has reached exactly zero,
        the car moves from `IN_TRANSFER` to `EMPTY_AWAITING_CLEANING` —
        continuing to `READY_FOR_RELEASE` at the same instant when the product
        does not require a full clean."
        PRD §3.7: "Departure — again a `YardMaster` action — moves the car
        from `RELEASED` to `DEPARTED`, its terminal state. The
        `departed_timestamp` is stamped, the release's `PULL` switch order
        completes, and `Railcar.version` increments one last time."
        PRD §3.4: "Later, when the placed car is released, the executed spot
        order that placed it — if still open — closes (`EXECUTED` to
        `CLOSED`)."

        Design: Corner/state_machines/railcar_full_lifecycle_happy_path
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-S1")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Flour", hazard_class="FOOD_GRADE",
                              segregation_group="FOOD_GRAIN",
                              requires_full_clean=True)
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=1)
        eq = create_equipment(name="CONV-1", equipment_type="CONVEYOR")
        car = create_railcar(cust["id"], prod["id"], lot["id"],
                             car_number="96001", quantity_loaded_tons=10.0)
        assert car["placement_status"] == "REGISTERED"

        car = validate_success(api.arrive_railcar(car["id"], YARD))
        assert car["placement_status"] == "ARRIVED"
        assert car["arrival_timestamp"][:19] == "2026-08-03T00:00:00"
        assert car["quantity_remaining_tons"] == 10.0

        so = create_spot_order_for_car(car["id"], trk["id"], 1,
                                       "2026-08-03T01:00:00Z",
                                       "2026-08-03T05:00:00Z")
        assert so["status"] == "REQUESTED"
        so = schedule_spot_order(so["id"])
        assert so["status"] == "SCHEDULED"
        set_clock("2026-08-03T02:00:00Z")
        so = validate_success(api.execute_spot_order(so["id"], YARD))
        assert so["status"] == "EXECUTED"

        car = get_railcar(car["id"])
        assert car["placement_status"] == "SPOTTED"
        assert car["placed_timestamp"][:19] == "2026-08-03T02:00:00"
        assert car["track_id"] == trk["id"]
        assert car["spot_number"] == 1

        to = create_transfer_for(car["id"], eq["id"], 10.0)
        to = validate_success(api.activate_transfer_order(to["id"], OPERATOR))
        assert to["status"] == "ACTIVE"
        wt = create_draft_ticket(to["id"], gross_weight_tons=24.0,
                                 tare_weight_tons=14.0, truck_max_payload_tons=40.0)
        validate_success(api.certify_weight_ticket(wt["id"], OPERATOR))

        car = get_railcar(car["id"])
        assert car["placement_status"] == "EMPTY_AWAITING_CLEANING", (
            "clean required, so the emptied car must NOT auto-advance"
        )

        cleaning = validate_success(
            api.start_railcar_cleaning(car["id"], "DETERGENT", OPERATOR)
        )
        assert cleaning["placement_status"] == "CLEANING"
        passed = validate_success(api.pass_railcar_cleaning(car["id"], OPERATOR))
        assert passed["placement_status"] == "READY_FOR_RELEASE"

        set_clock("2026-08-03T06:00:00Z")
        released = validate_success(api.release_railcar(car["id"], YARD))
        assert released["placement_status"] == "RELEASED"
        assert released["released_timestamp"][:19] == "2026-08-03T06:00:00"

        set_clock("2026-08-03T07:00:00Z")
        departed = validate_success(api.depart_railcar(car["id"], YARD))
        assert departed["placement_status"] == "DEPARTED"
        assert departed["departed_timestamp"][:19] == "2026-08-03T07:00:00"

        so_final = validate_success(api.get_spot_order(so["id"], YARD))
        assert so_final["status"] == "CLOSED"

        switches = list_all_switch_orders()
        spot_move = [s for s in switches if s["move_type"] == "SPOT"]
        pull_move = [s for s in switches if s["move_type"] == "PULL"]
        assert len(spot_move) == 1 and spot_move[0]["status"] == "COMPLETED"
        assert len(pull_move) == 1 and pull_move[0]["status"] == "COMPLETED"


class TestInvalidTransitions:
    def test_railcar_invalid_transitions_rejected(self, api):
        """PRD §2.9: "5. State — the entity is in a from-state that lists this
        trigger (`ERR_INVALID_STATE`, 409); this also covers acting on terminal
        states."
        PRD §3.3: a `SafetyOfficer` "may later lift the hold back to `NONE`" —
        lifting a car whose hold_status is already `NONE` matches no
        from-state.

        Design: Corner/state_machines/railcar_invalid_transitions_rejected
        """
        create_facility(name="FT-S2")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        create_track(name="T1", spot_capacity=1)
        car = create_railcar(cust["id"], prod["id"], lot["id"], car_number="96002")

        # REGISTERED car: depart, release, start-cleaning, pass-cleaning
        validate_error(api.depart_railcar(car["id"], YARD),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.release_railcar(car["id"], YARD),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.start_railcar_cleaning(car["id"], "RINSE", OPERATOR),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.pass_railcar_cleaning(car["id"], OPERATOR),
                       ApiErrorId.ERR_INVALID_STATE)

        arrived = validate_success(api.arrive_railcar(car["id"], YARD))
        assert arrived["placement_status"] == "ARRIVED"

        # Second arrive: ARRIVED is not a from-state for arrive
        validate_error(api.arrive_railcar(car["id"], YARD),
                       ApiErrorId.ERR_INVALID_STATE)

        # lift-hold while hold_status == NONE
        validate_error(api.lift_hold(car["id"], SAFETY),
                       ApiErrorId.ERR_INVALID_STATE)


class TestTerminalLockdown:
    def test_railcar_terminal_lockdown_rejected(self, api):
        """PRD §3.7: "Departure — again a `YardMaster` action — moves the car
        from `RELEASED` to `DEPARTED`, its terminal state."
        PRD §2.9: "5. State — the entity is in a from-state that lists this
        trigger (`ERR_INVALID_STATE`, 409); this also covers acting on terminal
        states."
        PRD §3.4: "Creation requires the car to be in `REGISTERED`, `ARRIVED`,
        or `SPOTTED` placement — any other state is `ERR_INVALID_STATE`,
        evaluated at priority 5, before the OCC check at priority 16"
        PRD §3.3: "A `SafetyOfficer` may place a hold on any car that has not
        yet departed"

        Design: Corner/state_machines/railcar_terminal_lockdown_rejected
        """
        ctx = setup_ready_for_release_car(quantity_loaded_tons=5.0,
                                          car_number="96003")
        car_id = ctx["car"]["id"]
        get_success_data(api.release_railcar(car_id, YARD))
        departed = validate_success(api.depart_railcar(car_id, YARD))
        assert departed["placement_status"] == "DEPARTED"

        validate_error(api.arrive_railcar(car_id, YARD),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.release_railcar(car_id, YARD),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.place_hold(car_id, "x", SAFETY),
                       ApiErrorId.ERR_INVALID_STATE)

        current = get_railcar(car_id)
        validate_error(
            api.create_spot_order(
                car_id,
                create_spot_order_payload(
                    expected_railcar_version=current["version"],
                    track_id=ctx["track"]["id"],
                    spot_number=1,
                    window_start="2026-08-04T01:00:00Z",
                    window_end="2026-08-04T05:00:00Z",
                ),
                YARD,
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )


class TestHoldGating:
    def test_hold_gating_and_release_cycle(self, api):
        """PRD §3.3: "A `SafetyOfficer` may place a hold on any car that has
        not yet departed, moving `hold_status` from `NONE` to `SAFETY_HOLD`
        (the request carries a `reason`), and may later lift the hold back to
        `NONE`. A held car cannot be transfer-activated and cannot be released
        — both attempts are rejected with `ERR_CAR_HELD`."

        Design: Corner/state_machines/hold_gating_and_release_cycle
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-S4")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        eq = create_equipment(name="CONV-1", equipment_type="CONVEYOR")
        car1 = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                         car_number="96004")["id"])
        car2 = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                         car_number="96005",
                                         quantity_loaded_tons=5.0)["id"])
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

        to1 = create_transfer_for(car1["id"], eq["id"], 10.0)
        # Drive car2 to READY_FOR_RELEASE via a full 5-ton transfer
        to2 = create_transfer_for(car2["id"], eq["id"], 5.0)
        get_success_data(api.activate_transfer_order(to2["id"], OPERATOR))
        wt2 = create_draft_ticket(to2["id"], gross_weight_tons=19.0,
                                  tare_weight_tons=14.0, truck_max_payload_tons=40.0)
        certify_ticket(wt2["id"])
        assert get_railcar(car2["id"])["placement_status"] == "READY_FOR_RELEASE"

        held1 = validate_success(api.place_hold(car1["id"], "leak", SAFETY))
        assert held1["hold_status"] == "SAFETY_HOLD"
        validate_error(api.activate_transfer_order(to1["id"], OPERATOR),
                       ApiErrorId.ERR_CAR_HELD)

        held2 = validate_success(api.place_hold(car2["id"], "inspection", SAFETY))
        assert held2["hold_status"] == "SAFETY_HOLD"
        validate_error(api.release_railcar(car2["id"], YARD),
                       ApiErrorId.ERR_CAR_HELD)

        lifted1 = validate_success(api.lift_hold(car1["id"], SAFETY))
        assert lifted1["hold_status"] == "NONE"
        validate_success(api.lift_hold(car2["id"], SAFETY))

        activated = validate_success(api.activate_transfer_order(to1["id"], OPERATOR))
        assert activated["status"] == "ACTIVE"
        released = validate_success(api.release_railcar(car2["id"], YARD))
        assert released["placement_status"] == "RELEASED"


class TestDerivedCounters:
    def test_derived_counters_reconciliation(self, api):
        """PRD §3.1: "`occupied_spots` is the count of railcars currently
        `SPOTTED` on the track; `reserved_spots` is the count of spot orders in
        `REQUESTED` or `SCHEDULED` on the track."
        PRD §3.3: "the linked inventory lot absorbs the lading: the lot's
        `quantity_received_tons` increases by `quantity_loaded_tons`, its
        `quantity_on_hand_tons` is recomputed"
        PRD §3.6: "the car's `quantity_remaining_tons` decreases by the net
        (bumping `Railcar.version`), and the lot's `quantity_shipped_tons`
        increases by the net with `quantity_on_hand_tons` recomputed"
        PRD §3.2: "`quantity_on_hand_tons` is always the received quantity
        minus the shipped quantity minus the rejected quantity."
        PRD §3.7: "the track's `occupied_spots` decreases by one (bumping
        `Track.version`)"

        Design: Corner/cross_cutting_layers/derived_counters_reconciliation
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-L4")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=1)
        eq = create_equipment(name="CONV-1", equipment_type="CONVEYOR")
        car = create_railcar(cust["id"], prod["id"], lot["id"],
                             car_number="97421", quantity_loaded_tons=40.0)
        car = arrive_car(car["id"])

        lot_now = get_lot(lot["id"])
        assert lot_now["quantity_received_tons"] == 40.0
        assert lot_now["quantity_on_hand_tons"] == 40.0

        so = create_spot_order_for_car(car["id"], trk["id"], 1)
        track = get_track(trk["id"])
        assert (track["occupied_spots"], track["reserved_spots"]) == (0, 1)

        schedule_spot_order(so["id"])
        track = get_track(trk["id"])
        assert (track["occupied_spots"], track["reserved_spots"]) == (0, 1), (
            "the reservation was already counted at create"
        )

        set_clock("2026-08-03T02:00:00Z")
        execute_spot_order(so["id"])
        track = get_track(trk["id"])
        assert (track["occupied_spots"], track["reserved_spots"]) == (1, 0)

        to = create_transfer_for(car["id"], eq["id"], 40.0)
        get_success_data(api.activate_transfer_order(to["id"], OPERATOR))
        wt = create_draft_ticket(to["id"], gross_weight_tons=39.0,
                                 tare_weight_tons=14.0, truck_max_payload_tons=40.0)
        certify_ticket(wt["id"])

        car_mid = get_railcar(car["id"])
        assert car_mid["quantity_remaining_tons"] == 15.0
        lot_mid = get_lot(lot["id"])
        assert lot_mid["quantity_shipped_tons"] == 25.0
        assert lot_mid["quantity_on_hand_tons"] == 15.0
        assert_lot_quantity_invariant(lot_mid)

        wt2 = create_draft_ticket(to["id"], gross_weight_tons=29.0,
                                  tare_weight_tons=14.0, truck_max_payload_tons=40.0,
                                  truck_reference="TRK-2")
        certify_ticket(wt2["id"])
        get_success_data(api.release_railcar(car["id"], YARD))
        track = get_track(trk["id"])
        assert (track["occupied_spots"], track["reserved_spots"]) == (0, 0)


class TestImmediateConsistency:
    def test_immediate_consistency_in_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.3: "The `arrival_timestamp` is stamped from the logical clock,
        `quantity_remaining_tons` is initialized to `quantity_loaded_tons`"
        PRD §3.6: "The ticket's `net_weight_tons` is computed immediately as
        gross minus tare, rounded half-up to three decimals, and the ticket
        starts in `DRAFT`."

        Design: Corner/consistency_model/immediate_consistency_in_response
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-M1")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=1)
        eq = create_equipment(name="CONV-1", equipment_type="CONVEYOR")
        car = create_railcar(cust["id"], prod["id"], lot["id"], car_number="97501")

        arrived = validate_success(api.arrive_railcar(car["id"], YARD))
        assert_railcar(arrived)
        assert arrived["placement_status"] == "ARRIVED"
        assert arrived["arrival_timestamp"][:19] == "2026-08-03T00:00:00"
        assert arrived["quantity_remaining_tons"] == 40.0

        patched = validate_success(
            api.patch_customer(cust["id"], {"demurrage_basis": "ACTUAL"}, ADMIN)
        )
        assert patched["demurrage_basis"] == "ACTUAL"
        assert patched["version"] == cust["version"] + 1

        so = create_spot_order_for_car(car["id"], trk["id"], 1)
        scheduled = validate_success(api.schedule_spot_order(so["id"], YARD))
        assert scheduled["status"] == "SCHEDULED"
        set_clock("2026-08-03T02:00:00Z")
        executed = validate_success(api.execute_spot_order(so["id"], YARD))
        assert executed["status"] == "EXECUTED"

        to = create_transfer_for(car["id"], eq["id"], 10.0)
        get_success_data(api.activate_transfer_order(to["id"], OPERATOR))
        wt = validate_success(
            api.create_weight_ticket(
                to["id"],
                {
                    "truck_reference": "TRK-1",
                    "gross_weight_tons": 24.0,
                    "tare_weight_tons": 14.0,
                    "truck_max_payload_tons": 40.0,
                },
                OPERATOR,
            ),
            201,
        )
        assert wt["net_weight_tons"] == 10.0, "net computed at creation"
        assert wt["status"] == "DRAFT"

        certified = validate_success(api.certify_weight_ticket(wt["id"], OPERATOR))
        assert certified["status"] == "CERTIFIED"
