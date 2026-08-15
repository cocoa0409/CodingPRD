"""Return, cleaning-turn gating, and final settlement: the two settlement
variants, line-by-line rounding, and the deposit waterfall conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_booking,
    assert_charge,
    assert_deposit_invariants,
    charge_amounts,
    checkout_booking,
    create_booking,
    create_qualified_renter,
    create_vessel,
    create_season_rate,
    create_geo_zone,
    find_charge,
    get_booking,
    get_single_turn,
    inspect_turn,
    inspect_turn_and_settle,
    list_charges,
    put_itinerary,
    report_incident,
    resolve_incident,
    return_booking,
    set_clock,
    setup_checked_out_booking,
    setup_confirmed_booking,
    setup_returned_booking,
    sign_all_orientation_items,
    countersign_orientation,
    validate_error,
    validate_success,
    waypoint,
)

DS = TEST_USERS["dock_staff_headers"]


class TestSettleStateGate:
    def test_settle_from_checked_out_rejected(self, api):
        """PRD §3.8: "Settlement closes the charter and is allowed only from
        `RETURNED`, and only once this booking's own cleaning turn is
        `COMPLETED` (`ERR_CLEANING_TURN_INCOMPLETE` otherwise)."
        PRD §2.11: "Generic transition state — the resource is not in a state
        that permits the requested transition (confirm on a non-`HELD` booking,
        checkout on a non-`CONFIRMED` booking, settle on a non-`RETURNED`
        booking, sign-item on a `COUNTERSIGNED` orientation, inspect on a turn
        that is not `IN_PROGRESS`, a decision on a non-`SUBMITTED` certificate,
        a resolve on a non-`REPORTED` incident): `ERR_INVALID_STATE`."

        Design: Corner/state_machines/settle_from_checked_out_rejected
        """
        ctx = setup_checked_out_booking(start_date="2026-08-20",
                                        end_date="2026-08-22",
                                        zone_code="ZP-SETTLE")
        booking = ctx["booking"]
        assert booking["status"] == "CHECKED_OUT"

        resp = api.settle_booking(booking["id"], DS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        after = get_booking(booking["id"])
        assert after["status"] == "CHECKED_OUT"
        charges = list_charges(booking["id"])
        assert [c["line_type"] for c in charges] == ["RENTAL"], (
            f"no settlement lines may be posted, got {[c['line_type'] for c in charges]}"
        )


class TestCleaningTurnGate:
    def test_settle_blocked_until_cleaning_turn_completes(self, api):
        """PRD §3.8: "Settlement closes the charter and is allowed only from
        `RETURNED`, and only once this booking's own cleaning turn is
        `COMPLETED` (`ERR_CLEANING_TURN_INCOMPLETE` otherwise)."
        PRD §3.8: "**Cleaning.** The 25,000-cent cleaning fee is always
        charged."

        Design: Difficulty/cross_entity_state_dependency/settle_requires_cleaning_turn_completed
        """
        ctx = setup_returned_booking(start_date="2026-08-20",
                                     end_date="2026-08-22",
                                     zone_code="ZP-OWL")
        booking = ctx["booking"]
        assert booking["status"] == "RETURNED"
        assert ctx["turn"]["status"] == "IN_PROGRESS"

        resp = api.settle_booking(booking["id"], DS)
        validate_error(resp, ApiErrorId.ERR_CLEANING_TURN_INCOMPLETE, 409)

        inspect_turn(ctx["turn"]["id"], True)
        settled = validate_success(api.settle_booking(booking["id"], DS), 200)
        assert settled["status"] == "CLOSED"
        assert settled["settlement_status"] == "FINALIZED"
        # equal gauges (0 fuel), pump-out done both ways (0), on-time return:
        # the net is the always-charged cleaning fee alone.
        assert settled["final_settlement_cents"] == 25000
        assert settled["deposit_applied_cents"] == 25000
        assert settled["deposit_released_cents"] == 125000
        assert settled["deposit_status"] == "PARTIALLY_APPLIED"
        assert_deposit_invariants(settled)

    def test_failed_inspection_loops_and_still_blocks_settle(self, api):
        """PRD §3.8: "a pass moves it `IN_PROGRESS` → `COMPLETED`; a fail keeps
        it `IN_PROGRESS` in a self-loop and bumps `re_clean_count` by 1 for the
        re-clean"
        PRD §3.8: "Settlement closes the charter and is allowed only from
        `RETURNED`, and only once this booking's own cleaning turn is
        `COMPLETED` (`ERR_CLEANING_TURN_INCOMPLETE` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/settle_requires_cleaning_turn_completed
        """
        ctx = setup_returned_booking(start_date="2026-08-20",
                                     end_date="2026-08-22",
                                     zone_code="ZP-RECLEAN")
        turn = inspect_turn(ctx["turn"]["id"], False)
        assert turn["status"] == "IN_PROGRESS", "failed inspection self-loops"
        assert turn["re_clean_count"] == 1

        resp = api.settle_booking(ctx["booking"]["id"], DS)
        validate_error(resp, ApiErrorId.ERR_CLEANING_TURN_INCOMPLETE, 409)

        turn = inspect_turn(ctx["turn"]["id"], True)
        assert turn["status"] == "COMPLETED"
        settled = validate_success(api.settle_booking(ctx["booking"]["id"], DS), 200)
        assert settled["status"] == "CLOSED"


class TestSettlementVariantsDiverge:
    def _setup_luxe_checked_out(self):
        ctx = setup_confirmed_booking(
            size_class="LUXE_56", tank=300, berth=8, vessel_name="Luxe One",
            rates=[("PEAK", "2026-06-01", "2026-08-31", 90000, 10),
                   ("SHOULDER", "2026-09-01", "2026-10-31", 65000, 10)],
            start_date="2026-08-28", end_date="2026-09-12", party_size=4,
            renter_name="Rae Dual", renter_email="rae@x.com",
            with_itinerary=True, zone_code="ZP-RAINBOW",
            itinerary_night="2026-08-28", countersign=True)
        set_clock("2026-08-28T09:00:00Z")
        ctx["booking"] = checkout_booking(ctx["booking"]["id"],
                                          fuel_gauge_percent=100,
                                          pump_out_done=True)
        return ctx

    def test_provisional_estimate_at_checkout_uses_burn_estimate(self, api):
        """PRD §3.6: "fuel is estimated at a 50% burn of the tank — half of
        `fuel_tank_capacity_gallons`, rounded half up to one decimal place,
        priced at 700 cents per gallon; the pump-out fee of 15,000 cents is
        assumed due; the cleaning fee of 25,000 cents is included; and
        late-return, damage, grounding and mechanical-refund components are all
        zero."
        PRD §2.10: "The estimate fields obey their defining moments:
        `provisional_estimate_cents` is unset until checkout computes it, and
        `final_settlement_cents` is unset until settlement finalizes it."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge
        """
        ctx = self._setup_luxe_checked_out()
        booking = ctx["booking"]
        assert booking["status"] == "CHECKED_OUT"
        assert booking["settlement_status"] == "PROVISIONAL"
        # 300 gal tank x 50% = 150.0 gal x 700 = 105000 + 15000 + 25000
        assert booking["provisional_estimate_cents"] == 145000, (
            f"PROVISIONAL variant must price the 50% burn estimate, got "
            f"{booking['provisional_estimate_cents']}"
        )
        assert booking.get("final_settlement_cents") is None, (
            "final settlement is unset until settlement finalizes it"
        )

    def test_final_settlement_diverges_from_provisional(self, api):
        """PRD §3.8: "**Fuel.** The gauge delta is the checkout gauge minus the
        return gauge, floored at zero — returning with more fuel than checkout
        earns no credit. Gallons owed are that delta times
        `fuel_tank_capacity_gallons` divided by 100, rounded half up to one
        decimal place, priced at 700 cents per gallon."
        PRD §3.8: "**Late return.** The return deadline is 10:00:00Z on the
        booking's `end_date`. When `actual_return_at` passes the deadline, the
        excess is rounded up to whole hours and billed at 5,000 cents per hour;
        an on-time return owes nothing."
        PRD §2.7: "One rounding discipline is pinned across every
        settlement-style computation: each charge line is computed and rounded
        to whole cents first, and any total is then the plain sum of those
        already-rounded lines."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge
        """
        ctx = self._setup_luxe_checked_out()
        booking = ctx["booking"]

        returned = return_booking(booking["id"], "2026-09-12T13:00:00Z",
                                  fuel_gauge_percent=62, pump_out_done=False)
        assert returned["status"] == "RETURNED"
        ctx["turn"] = get_single_turn(booking["id"])
        settled, charges = inspect_turn_and_settle(ctx)

        # FINAL: fuel (100-62) x 300/100 = 114.0 gal x 700 = 79800;
        # pump-out 15000; cleaning 25000; late 3h x 5000 = 15000 -> 134800.
        assert settled["final_settlement_cents"] == 134800
        assert settled["provisional_estimate_cents"] == 145000, (
            "the provisional snapshot is not overwritten by the final"
        )
        assert settled["final_settlement_cents"] != settled["provisional_estimate_cents"]
        assert settled["deposit_applied_cents"] == 134800
        assert settled["deposit_released_cents"] == 115200  # 250000 held - 134800
        assert settled["deposit_status"] == "PARTIALLY_APPLIED"
        assert settled["settlement_status"] == "FINALIZED"
        assert settled["status"] == "CLOSED"
        assert_deposit_invariants(settled)

        for line_type, amount in (("FUEL", 79800), ("PUMP_OUT", 15000),
                                  ("CLEANING_FEE", 25000), ("LATE_RETURN", 15000)):
            line = find_charge(charges, line_type)
            assert_charge(line)
            assert line["amount_cents"] == amount
            assert line["status"] == "APPLIED_TO_DEPOSIT", (
                f"{line_type} is consumed by the deposit"
            )


class TestDepositWaterfall:
    def test_deposit_conservation_partial_application(self, api):
        """PRD §2.10: "A hard invariant holds at every terminal state of this
        dimension: `deposit_applied_cents` plus `deposit_released_cents` always
        equals `deposit_held_cents`."
        PRD §3.8: "When the net is zero or positive, `deposit_applied_cents`
        becomes the smaller of the net and `deposit_held_cents`,
        `deposit_released_cents` becomes the remainder of the held amount, and
        the renter separately owes whatever the net exceeds the deposit by; the
        deposit dimension lands at `RELEASED` when nothing was applied,
        `PARTIALLY_APPLIED` when the applied portion is positive but below the
        held amount, or `FULLY_APPLIED` when the entire deposit was consumed."
        PRD §3.8: "Ledger hygiene follows: positive incident and operational
        lines consumed by the deposit are marked `APPLIED_TO_DEPOSIT`, and
        negative refund lines are marked `REFUNDED`."

        Design: Difficulty/compensating_invariant/deposit_conservation_through_settlement
        """
        ctx = setup_checked_out_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard Fifteen",
            start_date="2026-08-10", end_date="2026-08-15",
            zone_code="ZP-GUNSIGHT", checkout_fuel=80, checkout_pump=True)
        booking = ctx["booking"]
        assert booking["deposit_held_cents"] == 200000, "captured at confirm"

        returned = return_booking(booking["id"], "2026-08-15T12:00:00Z",
                                  fuel_gauge_percent=60, pump_out_done=False)
        assert returned["status"] == "RETURNED"
        ctx["turn"] = get_single_turn(booking["id"])
        settled, charges = inspect_turn_and_settle(ctx)

        # fuel (80-60) x 200/100 = 40.0 gal x 700 = 28000; pump-out 15000;
        # cleaning 25000; late 2h x 5000 = 10000 -> net 78000.
        assert settled["final_settlement_cents"] == 78000
        assert settled["deposit_applied_cents"] == 78000
        assert settled["deposit_released_cents"] == 122000
        assert (settled["deposit_applied_cents"] + settled["deposit_released_cents"]
                == settled["deposit_held_cents"] == 200000)
        assert settled["deposit_status"] == "PARTIALLY_APPLIED"
        assert settled["settlement_status"] == "FINALIZED"
        assert settled["status"] == "CLOSED"
        assert_deposit_invariants(settled)

        for line_type in ("FUEL", "PUMP_OUT", "CLEANING_FEE", "LATE_RETURN"):
            line = find_charge(charges, line_type)
            assert line["status"] == "APPLIED_TO_DEPOSIT", (
                f"{line_type} consumed by the deposit must be marked "
                f"APPLIED_TO_DEPOSIT, got {line['status']}"
            )

    def test_deposit_fully_applied_when_net_exceeds_deposit(self, api):
        """PRD §3.8: "the deposit dimension lands at `RELEASED` when nothing
        was applied, `PARTIALLY_APPLIED` when the applied portion is positive
        but below the held amount, or `FULLY_APPLIED` when the entire deposit
        was consumed."
        PRD §3.8: "Non-zero operational lines are posted to the ledger as
        `POSTED` charges (the cleaning fee is always posted, and zero-amount
        lines never are), and `final_settlement_cents` records the net."
        PRD §3.7: "`DAMAGE_ASSESSED` — a positive `DAMAGE` charge of
        `assessed_damage_cents` is posted on the booking."

        Design: Difficulty/compensating_invariant/deposit_conservation_through_settlement
        """
        ctx = setup_checked_out_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard Dmg",
            start_date="2026-08-10", end_date="2026-08-15",
            zone_code="ZP-DAMAGE")
        booking = ctx["booking"]

        set_clock("2026-08-12T12:00:00Z")
        incident = report_incident(booking["id"], ctx["renter_headers"],
                                   "DAMAGE", "2026-08-12T10:00:00Z")
        resolve_incident(incident["id"], "DAMAGE_ASSESSED",
                         assessed_damage_cents=500000)

        return_booking(booking["id"], "2026-08-15T09:00:00Z",
                       fuel_gauge_percent=100, pump_out_done=True)
        ctx["turn"] = get_single_turn(booking["id"])
        settled, charges = inspect_turn_and_settle(ctx)

        # cleaning 25000 + DAMAGE 500000 -> net 525000 exceeds the 200000 held.
        assert settled["final_settlement_cents"] == 525000
        assert settled["deposit_applied_cents"] == 200000
        assert settled["deposit_released_cents"] == 0
        assert settled["deposit_status"] == "FULLY_APPLIED"
        assert settled["status"] == "CLOSED"
        assert_deposit_invariants(settled)

        damage = find_charge(charges, "DAMAGE")
        assert damage["amount_cents"] == 500000


class TestLateReturnBoundary:
    def test_on_time_return_boundary_no_late_fee(self, api):
        """PRD §3.8: "**Late return.** The return deadline is 10:00:00Z on the
        booking's `end_date`. When `actual_return_at` passes the deadline, the
        excess is rounded up to whole hours and billed at 5,000 cents per hour;
        an on-time return owes nothing."
        PRD §2.10: "Lines whose computed amount is zero are never posted."

        Design: Corner/calculations/on_time_return_boundary_no_late_fee
        """
        ctx = setup_checked_out_booking(start_date="2026-08-20",
                                        end_date="2026-08-22",
                                        zone_code="ZP-LATE")
        # Return exactly at the deadline: not late.
        return_booking(ctx["booking"]["id"], "2026-08-22T10:00:00Z",
                       fuel_gauge_percent=100, pump_out_done=True)
        ctx["turn"] = get_single_turn(ctx["booking"]["id"])
        settled, charges = inspect_turn_and_settle(ctx)

        assert settled["final_settlement_cents"] == 25000, (
            "cleaning only; return exactly at the deadline is not late"
        )
        assert charge_amounts(charges, "LATE_RETURN") == [], (
            "no LATE_RETURN line may be posted for an on-time return"
        )
