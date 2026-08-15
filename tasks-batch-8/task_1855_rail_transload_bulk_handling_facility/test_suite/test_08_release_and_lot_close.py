"""Release gating (derail, unpaid invoice, state-vs-fiscal priority), lot
close guards with the final SIT charge, and the spot-cancel compensation
invariant."""
from test_helpers import (
    ApiErrorId,
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
    create_invoice_for,
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
    list_all_charges,
    schedule_spot_order,
    set_clock,
    setup_ready_for_release_car,
    setup_spotted_car,
)


class TestLotClose:
    def test_lot_close_guards_then_success(self, api):
        """PRD §3.2: "Closing a lot is a `FacilityAdmin` action with two
        preconditions: `quantity_on_hand_tons` must be exactly zero (else
        `ERR_LOT_NOT_EMPTY`), and no linked railcar may be in any placement
        state other than `RELEASED` or `DEPARTED` (else
        `ERR_LOT_HAS_ACTIVE_CARS`). On close, `close_timestamp` is stamped from
        the logical clock, the final SIT accrual is computed with the close
        timestamp as its end, and a `ChargeEntry` of `charge_type`
        `STORAGE_IN_TRANSIT` is created in `ACCRUED` status with the lot's
        `customer_id`, a null `railcar_id` (it is a lot-level charge),
        `quantity` equal to the final billable days, and `amount_cents` equal
        to the final amount — this charge is created even when the final
        amount is zero."
        PRD §2.9: "5. State — the entity is in a from-state that lists this
        trigger (`ERR_INVALID_STATE`, 409); this also covers acting on terminal
        states."

        Design: Corner/state_machines/lot_close_guards_then_success
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-S13")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=1)
        eq = create_equipment(name="CONV-1", equipment_type="CONVEYOR")
        car = create_railcar(cust["id"], prod["id"], lot["id"],
                             car_number="96801", quantity_loaded_tons=10.0)
        car = arrive_car(car["id"])

        # on_hand is 10.0 after arrival -> ERR_LOT_NOT_EMPTY
        validate_error(api.close_lot(lot["id"], ADMIN), ApiErrorId.ERR_LOT_NOT_EMPTY)

        so = create_spot_order_for_car(car["id"], trk["id"], 1)
        schedule_spot_order(so["id"])
        set_clock("2026-08-03T02:00:00Z")
        execute_spot_order(so["id"])
        to = create_transfer_for(car["id"], eq["id"], 10.0)
        get_success_data(api.activate_transfer_order(to["id"], OPERATOR))
        wt = create_draft_ticket(to["id"], gross_weight_tons=24.0,
                                 tare_weight_tons=14.0, truck_max_payload_tons=40.0)
        certify_ticket(wt["id"])

        # on_hand is 0 now, but the car is READY_FOR_RELEASE, not RELEASED
        validate_error(api.close_lot(lot["id"], ADMIN),
                       ApiErrorId.ERR_LOT_HAS_ACTIVE_CARS)

        get_success_data(api.release_railcar(car["id"], YARD))
        set_clock("2026-08-06T00:00:00Z")
        closed = validate_success(api.close_lot(lot["id"], ADMIN))
        assert closed["status"] == "CLOSED"
        assert closed["close_timestamp"][:19] == "2026-08-06T00:00:00"
        # custody 08-03T00:00 + 2 free days -> window 08-05; close 08-06 -> 1 day
        assert closed["sit_billable_days"] == 1
        assert closed["sit_accrued_cents"] == 5000

        # CLOSED is terminal
        validate_error(api.close_lot(lot["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_STATE)

        sit = [c for c in list_all_charges()
               if c["charge_type"] == "STORAGE_IN_TRANSIT"]
        assert len(sit) == 1
        assert sit[0]["quantity"] == 1
        assert sit[0]["amount_cents"] == 5000
        assert sit[0]["railcar_id"] is None
        assert sit[0]["status"] == "ACCRUED"


class TestReleaseBlocked:
    def _derail_and_invoice_setup(self, api):
        """READY_FOR_RELEASE car (full-clean product, washed once with
        DETERGENT) sitting on a track whose derail device is ENGAGED."""
        ctx = setup_ready_for_release_car(
            requires_full_clean=True, wash_type="DETERGENT",
            quantity_loaded_tons=10.0, car_number="91002",
            product_overrides={"name": "Flour", "hazard_class": "FOOD_GRADE",
                               "segregation_group": "FOOD_GRAIN"},
        )
        get_success_data(api.engage_derail(ctx["track"]["id"], SAFETY))
        return ctx

    def test_release_blocked_by_engaged_derail(self, api):
        """PRD §3.7: "Release is a `YardMaster` action moving the car from
        `READY_FOR_RELEASE` to `RELEASED`, gated by four checks: the car's
        `hold_status` must be `NONE` (`ERR_CAR_HELD`); the facility must not
        be `SUSPENDED` (`ERR_FACILITY_SUSPENDED`); the track the car sits on
        must have `derail_protection` `DISENGAGED` (`ERR_DERAIL_ENGAGED`); and
        the customer must have no invoice in `ISSUED` status — an unpaid
        issued invoice blocks release with `ERR_UNPAID_CHARGES` (HTTP 402)."

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_derail_and_invoice
        """
        ctx = self._derail_and_invoice_setup(api)
        validate_error(api.release_railcar(ctx["car"]["id"], YARD),
                       ApiErrorId.ERR_DERAIL_ENGAGED)
        assert get_railcar(ctx["car"]["id"])["placement_status"] == (
            "READY_FOR_RELEASE"
        )

    def test_release_blocked_by_issued_invoice_then_paid(self, api):
        """PRD §3.7: "Release is a `YardMaster` action moving the car from
        `READY_FOR_RELEASE` to `RELEASED`, gated by four checks: the car's
        `hold_status` must be `NONE` (`ERR_CAR_HELD`); the facility must not
        be `SUSPENDED` (`ERR_FACILITY_SUSPENDED`); the track the car sits on
        must have `derail_protection` `DISENGAGED` (`ERR_DERAIL_ENGAGED`); and
        the customer must have no invoice in `ISSUED` status — an unpaid
        issued invoice blocks release with `ERR_UNPAID_CHARGES` (HTTP 402)."
        PRD §3.7: "`released_timestamp` is stamped from the logical clock"

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_derail_and_invoice
        """
        ctx = self._derail_and_invoice_setup(api)
        # Clear the derail; an ISSUED invoice still blocks the release
        get_success_data(api.disengage_derail(ctx["track"]["id"], SAFETY))
        inv = create_invoice_for(ctx["customer"]["id"])
        get_success_data(api.issue_invoice(inv["id"], BILLING))

        validate_error(api.release_railcar(ctx["car"]["id"], YARD),
                       ApiErrorId.ERR_UNPAID_CHARGES)

        get_success_data(api.pay_invoice(inv["id"], BILLING))
        released = validate_success(api.release_railcar(ctx["car"]["id"], YARD))
        assert released["placement_status"] == "RELEASED"
        # clock was never advanced past the 02:00 execute time
        assert released["released_timestamp"][:19] == "2026-08-03T02:00:00"


class TestStateBeatsFiscal:
    def _spotted_with_issued_invoice(self, api):
        """A SPOTTED (not READY_FOR_RELEASE) car whose customer has an ISSUED
        unpaid invoice covering the scheduling switching charge."""
        ctx = setup_spotted_car(quantity_loaded_tons=40.0, car_number="80001")
        inv = create_invoice_for(ctx["customer"]["id"])
        get_success_data(api.issue_invoice(inv["id"], BILLING))
        ctx["invoice"] = inv
        return ctx

    def test_release_wrong_state_reports_invalid_state_not_unpaid(self, api):
        """PRD §2.9: "Every endpoint evaluates its checks in a fixed priority
        order, and when several checks fail the earliest one wins:" with
        "5. State — the entity is in a from-state that lists this trigger
        (`ERR_INVALID_STATE`, 409); this also covers acting on terminal
        states." listed ahead of "13. Unpaid invoice on release
        (`ERR_UNPAID_CHARGES`, 402)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_release
        """
        ctx = self._spotted_with_issued_invoice(api)
        resp = api.release_railcar(ctx["car"]["id"], YARD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, (
            "the state check wins over the fiscal check (which would be 402)"
        )

    def test_release_state_failure_leaves_invoice_untouched(self, api):
        """PRD §2.9: "5. State — the entity is in a from-state that lists this
        trigger (`ERR_INVALID_STATE`, 409); this also covers acting on terminal
        states."
        PRD §3.7: "Release is a `YardMaster` action moving the car from
        `READY_FOR_RELEASE` to `RELEASED`" — a rejected release performs none
        of the release side effects.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_release
        """
        ctx = self._spotted_with_issued_invoice(api)
        validate_error(api.release_railcar(ctx["car"]["id"], YARD),
                       ApiErrorId.ERR_INVALID_STATE)
        assert get_railcar(ctx["car"]["id"])["placement_status"] == "SPOTTED"
        inv = get_success_data(api.get_invoice(ctx["invoice"]["id"], BILLING))
        assert inv["status"] == "ISSUED", "no side effects fired"


class TestSpotCancelInvariant:
    def _scheduled_setup(self, api):
        """One ARRIVED car with a SCHEDULED spot order on a cap-2 track
        (reserved 1, one 18500-cent SWITCHING charge ACCRUED)."""
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-I2")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        car = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="94002")["id"]
        )
        so = create_spot_order_for_car(car["id"], trk["id"], 1,
                                       "2026-08-03T10:00:00Z",
                                       "2026-08-03T12:00:00Z")
        so = schedule_spot_order(so["id"])
        return {"customer": cust, "track": trk, "car": car,
                "spot_order": so, "switch_order_id": so["switch_order_id"]}

    def test_schedule_reserves_spot_and_accrued_charge(self, api):
        """PRD §3.4: "On success, the system creates a `SwitchOrder` of
        `move_type` `SPOT` for this window — computing its `sequence_number`
        and `fee_cents` per the switching-fee rule and creating an `ACCRUED`
        `ChargeEntry` of `charge_type` `SWITCHING` for the fee — sets the spot
        order's `switch_order_id`, and bumps `SpotOrder.version`."
        PRD §3.1: "`reserved_spots` is the count of spot orders in `REQUESTED`
        or `SCHEDULED` on the track."

        Design: Difficulty/compensating_invariant/spot_cancel_reservation_and_charge_invariant
        """
        ctx = self._scheduled_setup(api)
        track = get_track(ctx["track"]["id"])
        assert track["occupied_spots"] == 0
        assert track["reserved_spots"] == 1

        sw = validate_success(api.get_switch_order(ctx["switch_order_id"], YARD))
        assert sw["status"] == "SCHEDULED"
        charges = [c for c in list_all_charges()
                   if c["charge_type"] == "SWITCHING"]
        assert len(charges) == 1
        assert charges[0]["status"] == "ACCRUED"
        assert charges[0]["amount_cents"] == 18500, (
            "no free allowance configured; first move pays the SPOT base fee"
        )

    def test_cancel_releases_reservation_and_voids_charge(self, api):
        """PRD §3.4: "Cancelling releases the reservation
        (`Track.reserved_spots` decreases by one); cancelling a `SCHEDULED`
        order additionally cancels its linked switch order (`SCHEDULED` to
        `CANCELLED`) and voids that move's `SWITCHING` charge entry
        (`ACCRUED` to `VOIDED`) as compensation."

        Design: Difficulty/compensating_invariant/spot_cancel_reservation_and_charge_invariant
        """
        ctx = self._scheduled_setup(api)
        cancelled = validate_success(
            api.cancel_spot_order(ctx["spot_order"]["id"], YARD)
        )
        assert cancelled["status"] == "CANCELLED"

        track = get_track(ctx["track"]["id"])
        assert track["occupied_spots"] == 0
        assert track["reserved_spots"] == 0, "reservation released"

        sw = validate_success(api.get_switch_order(ctx["switch_order_id"], YARD))
        assert sw["status"] == "CANCELLED"

        charges = [c for c in list_all_charges()
                   if c["charge_type"] == "SWITCHING"]
        assert len(charges) == 1
        assert charges[0]["status"] == "VOIDED"
        assert charges[0]["amount_cents"] == 18500
        accrued = [c for c in list_all_charges() if c["status"] == "ACCRUED"]
        assert accrued == [], "customer's ACCRUED switching total back to 0"
