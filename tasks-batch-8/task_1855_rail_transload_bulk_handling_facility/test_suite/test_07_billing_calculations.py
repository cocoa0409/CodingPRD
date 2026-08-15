"""Billing engines: demurrage basis variants and tier straddle, the free
allowance boundary, SIT calendar/business variants and free-window boundary,
switching-fee sequencing, invoice line rounding, and cleaning fees."""
from test_helpers import (
    ApiErrorId,
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
    list_all_charges,
    list_all_switch_orders,
    schedule_spot_order,
    set_clock,
    setup_active_transfer,
    setup_ready_for_release_car,
)


def _constructive_car(api, *, number, clock_arrive="2026-08-03T00:00:00Z"):
    """Customer (CONSTRUCTIVE) + car arrived at clock_arrive, never spotted."""
    cust = create_customer(name=f"CONS-{number}", allocated_car_spots=5,
                           demurrage_basis="CONSTRUCTIVE")
    prod = create_product(name=f"Urea-{number}", hazard_class="NON_HAZARDOUS",
                          segregation_group="FERTILIZER",
                          requires_full_clean=False)
    lot = create_lot(cust["id"], prod["id"])
    car = create_railcar(cust["id"], prod["id"], lot["id"], car_number=number)
    return arrive_car(car["id"])


class TestDemurrageBasisVariants:
    def _basis_setup(self, api):
        """Two identical cars spotted at the same instant; one customer's
        demurrage clock started at arrival, the other's at placement."""
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-DV")
        cust_cons = create_customer(name="CONS", allocated_car_spots=5,
                                    demurrage_basis="CONSTRUCTIVE")
        cust_act = create_customer(name="ACT", allocated_car_spots=5,
                                   demurrage_basis="ACTUAL")
        prod = create_product(name="Urea", hazard_class="NON_HAZARDOUS",
                              segregation_group="FERTILIZER",
                              requires_full_clean=False)
        lot_cons = create_lot(cust_cons["id"], prod["id"])
        lot_act = create_lot(cust_act["id"], prod["id"])
        t1 = create_track(name="T1", spot_capacity=1)
        t2 = create_track(name="T2", spot_capacity=1)
        car1 = arrive_car(create_railcar(cust_cons["id"], prod["id"],
                                         lot_cons["id"], car_number="10001",
                                         quantity_loaded_tons=50.0)["id"])
        car2 = arrive_car(create_railcar(cust_act["id"], prod["id"],
                                         lot_act["id"], car_number="10002",
                                         quantity_loaded_tons=50.0)["id"])
        so1 = create_spot_order_for_car(car1["id"], t1["id"], 1,
                                        "2026-08-05T11:00:00Z",
                                        "2026-08-05T13:00:00Z")
        so2 = create_spot_order_for_car(car2["id"], t2["id"], 1,
                                        "2026-08-05T11:00:00Z",
                                        "2026-08-05T13:00:00Z")
        schedule_spot_order(so1["id"])
        schedule_spot_order(so2["id"])
        set_clock("2026-08-05T12:00:00Z")
        execute_spot_order(so1["id"])
        execute_spot_order(so2["id"])
        set_clock("2026-08-07T06:00:00Z")
        return car1["id"], car2["id"]

    def test_demurrage_constructive_basis_counts_from_arrival(self, api):
        """PRD §3.3: "under `CONSTRUCTIVE` it starts at `arrival_timestamp`
        even if the car sits unspotted" and "billable time is the elapsed
        minutes beyond that allowance, never below zero, and billable days are
        the billable minutes divided by a full day of 1440 minutes, rounded
        up."
        PRD §3.3: "The first 3 billable days are charged at a tier-1 rate of
        7500 cents per day"
        PRD §3.3: "Reads of the railcar expose the provisional
        `demurrage_billable_days` and `demurrage_accrued_cents` computed
        against the current logical clock"

        Design: Difficulty/dual_variant_calc/demurrage_constructive_vs_actual_basis
        """
        car1_id, _car2_id = self._basis_setup(api)
        car1 = get_railcar(car1_id)
        # arrival 2026-08-03T00:00Z -> observe 2026-08-07T06:00Z = 6120 min;
        # 6120 - 2880 free = 3240 -> ceil(3240/1440) = 3 days at 7500
        assert car1["arrival_timestamp"][:19] == "2026-08-03T00:00:00"
        assert car1["placed_timestamp"][:19] == "2026-08-05T12:00:00"
        assert car1["demurrage_billable_days"] == 3
        assert car1["demurrage_accrued_cents"] == 22500

    def test_demurrage_actual_basis_counts_from_placement(self, api):
        """PRD §3.3: "under `ACTUAL` it starts at `placed_timestamp`, so while
        the car is unspotted the accrual is zero."
        PRD §3.3: "billable time is the elapsed minutes beyond that allowance,
        never below zero, and billable days are the billable minutes divided by
        a full day of 1440 minutes, rounded up."

        Design: Difficulty/dual_variant_calc/demurrage_constructive_vs_actual_basis
        """
        _car1_id, car2_id = self._basis_setup(api)
        car2 = get_railcar(car2_id)
        # placed 2026-08-05T12:00Z -> observe 2026-08-07T06:00Z = 2520 min,
        # inside the 2880-minute free allowance
        assert car2["arrival_timestamp"][:19] == "2026-08-03T00:00:00"
        assert car2["placed_timestamp"][:19] == "2026-08-05T12:00:00"
        assert car2["demurrage_billable_days"] == 0
        assert car2["demurrage_accrued_cents"] == 0


class TestDemurrageFreeBoundary:
    def test_demurrage_exactly_free_allowance_bills_zero(self, api):
        """PRD §3.3: "billable time is the elapsed minutes beyond that
        allowance, never below zero, and billable days are the billable
        minutes divided by a full day of 1440 minutes, rounded up."
        PRD §2.6: "`free_demurrage_hours` (default 48, must be greater than
        0)"

        Design: Difficulty/boundary_precision_check/demurrage_free_minute_boundary
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-B1")
        car = _constructive_car(api, number="90001")
        set_clock("2026-08-05T00:00:00Z")  # exactly 2880 elapsed minutes
        car = get_railcar(car["id"])
        assert car["demurrage_billable_days"] == 0
        assert car["demurrage_accrued_cents"] == 0

    def test_demurrage_one_minute_past_allowance_bills_one_day(self, api):
        """PRD §3.3: "billable time is the elapsed minutes beyond that
        allowance, never below zero, and billable days are the billable
        minutes divided by a full day of 1440 minutes, rounded up."
        PRD §3.3: "The first 3 billable days are charged at a tier-1 rate of
        7500 cents per day"

        Design: Difficulty/boundary_precision_check/demurrage_free_minute_boundary
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-B1")
        car = _constructive_car(api, number="90002")
        set_clock("2026-08-05T00:01:00Z")  # 2881 elapsed -> 1 billable minute
        car = get_railcar(car["id"])
        assert car["demurrage_billable_days"] == 1
        assert car["demurrage_accrued_cents"] == 7500


class TestDemurrageTierStraddle:
    def _straddle_setup(self, api):
        """HAZARDOUS car, GOOD credit, released exactly 168h after a
        constructive arrival: 10080 - 2880 = 7200 billable minutes -> 5 days
        (3 at tier 1, 2 at tier 2)."""
        ctx = setup_ready_for_release_car(
            quantity_loaded_tons=5.0, car_number="50001",
            product_overrides={"name": "Benzene", "hazard_class": "HAZARDOUS",
                               "segregation_group": "CHEMICAL",
                               "requires_full_clean": False},
        )
        set_clock("2026-08-10T00:00:00Z")
        return ctx

    def test_demurrage_tier_straddle_marginal_rates(self, api):
        """PRD §3.3: "The first 3 billable days are charged at a tier-1 rate
        of 7500 cents per day; the next 4 billable days (days 4 through 7) at
        a tier-2 rate of 15000 cents per day; and every billable day beyond
        day 7 at a tier-3 rate of 25000 cents per day."
        PRD §3.3: "The tiered subtotal is then multiplied by a hazard factor —
        one and a half when the lading product's `hazard_class` is `HAZARDOUS`,
        otherwise one — and by a credit factor from the customer's
        `credit_standing`: one for `GOOD_STANDING`, one and a quarter for
        `CREDIT_WATCH`, and one and a half for `CREDIT_HOLD`."
        PRD §3.3: "the figures finalize at release."

        Design: Difficulty/combinatorial_formula/demurrage_tiered_hazard_credit_straddle
        """
        ctx = self._straddle_setup(api)
        released = validate_success(api.release_railcar(ctx["car"]["id"], YARD))
        # (3*7500 + 2*15000) * 1.5 hazard * 1.0 credit = 52500 * 1.5
        assert released["demurrage_billable_days"] == 5
        assert released["demurrage_accrued_cents"] == 78750

    def test_demurrage_hazard_multiplier_applied_once_on_charge(self, api):
        """PRD §3.7: "the final demurrage accrual is computed with the release
        timestamp as its end, and a `ChargeEntry` of `charge_type` `DEMURRAGE`
        is created in `ACCRUED` status with `quantity` equal to the final
        billable days and `amount_cents` equal to the final amount"
        PRD §3.3: "The final `amount_cents` is the tiered subtotal times both
        multipliers, rounded half-up to integer cents in a single rounding."

        Design: Difficulty/combinatorial_formula/demurrage_tiered_hazard_credit_straddle
        """
        ctx = self._straddle_setup(api)
        get_success_data(api.release_railcar(ctx["car"]["id"], YARD))
        dem = [c for c in list_all_charges()
               if c["charge_type"] == "DEMURRAGE"
               and c["railcar_id"] == ctx["car"]["id"]]
        assert len(dem) == 1
        assert dem[0]["quantity"] == 5
        assert dem[0]["amount_cents"] == 78750
        assert dem[0]["status"] == "ACCRUED"


class TestSitBasisVariants:
    def _sit_setup(self, api):
        set_clock("2026-08-03T00:00:00Z")  # a Monday
        create_facility(name="FT-SIT")  # sit_free_days default 2
        cust_cal = create_customer(name="CAL", allocated_car_spots=5,
                                   sit_day_basis="CALENDAR")
        cust_bus = create_customer(name="BUS", allocated_car_spots=5,
                                   sit_day_basis="BUSINESS")
        prod = create_product(name="Corn", hazard_class="FOOD_GRADE",
                              segregation_group="FOOD_GRAIN",
                              requires_full_clean=True)
        lot_cal = create_lot(cust_cal["id"], prod["id"], sit_daily_rate_cents=5000)
        lot_bus = create_lot(cust_bus["id"], prod["id"], sit_daily_rate_cents=5000)
        set_clock("2026-08-10T00:00:00Z")  # the following Monday
        return lot_cal["id"], lot_bus["id"]

    def test_sit_calendar_basis_counts_every_day(self, api):
        """PRD §3.2: "The free window ends at `sit_start_timestamp` plus
        `sit_free_days` whole days; the accrual end is `close_timestamp` once
        set, otherwise the current logical clock. The elapsed span after the
        free window is floored to whole 24-hour blocks and clamped at zero"
        and "Under the `CALENDAR` basis every whole block counts as billable."
        and "The accrued amount is the billable day count multiplied by
        `sit_daily_rate_cents`, an exact integer-cent product needing no
        rounding."

        Design: Difficulty/dual_variant_calc/sit_calendar_vs_business_days
        """
        lot_cal_id, _ = self._sit_setup(api)
        lot = get_lot(lot_cal_id)
        assert lot["sit_free_days"] == 2
        assert lot["sit_start_timestamp"][:19] == "2026-08-03T00:00:00"
        # blocks Aug 5, 6, 7, 8, 9 all count
        assert lot["sit_billable_days"] == 5
        assert lot["sit_accrued_cents"] == 25000

    def test_sit_business_basis_skips_weekends(self, api):
        """PRD §3.2: "Under the `BUSINESS` basis, only blocks whose starting
        UTC date falls Monday through Friday count — blocks starting on a
        Saturday or Sunday are free."

        Design: Difficulty/dual_variant_calc/sit_calendar_vs_business_days
        """
        _, lot_bus_id = self._sit_setup(api)
        lot = get_lot(lot_bus_id)
        assert lot["sit_free_days"] == 2
        assert lot["sit_start_timestamp"][:19] == "2026-08-03T00:00:00"
        # blocks Aug 5 (Wed), 6 (Thu), 7 (Fri) count; Aug 8-9 (Sat/Sun) free
        assert lot["sit_billable_days"] == 3
        assert lot["sit_accrued_cents"] == 15000


class TestSitFreeWindowBoundary:
    def test_sit_free_window_boundary(self, api):
        """PRD §3.2: "The free window ends at `sit_start_timestamp` plus
        `sit_free_days` whole days; the accrual end is `close_timestamp` once
        set, otherwise the current logical clock. The elapsed span after the
        free window is floored to whole 24-hour blocks and clamped at zero"

        Design: Corner/calculations/sit_free_window_boundary
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-C1")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"], sit_daily_rate_cents=5000)

        set_clock("2026-08-05T00:00:00Z")  # exactly the window end
        snap = get_lot(lot["id"])
        assert snap["sit_billable_days"] == 0
        assert snap["sit_accrued_cents"] == 0

        set_clock("2026-08-06T00:00:00Z")  # one whole 24h block later
        snap = get_lot(lot["id"])
        assert snap["sit_billable_days"] == 1
        assert snap["sit_accrued_cents"] == 5000


class TestSwitchingFeeSequence:
    def _switching_setup(self, api):
        """Facility with one free switch per period. Car A spotted then fully
        transferred (ready for release); car B scheduled behind it."""
        set_clock("2026-08-03T09:00:00Z")
        create_facility(name="FT-SW", free_switches_per_period=1)
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        eq = create_equipment(name="CONV-1", equipment_type="CONVEYOR")
        car_a = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                          car_number="40001",
                                          quantity_loaded_tons=10.0)["id"])
        car_b = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                          car_number="40002",
                                          quantity_loaded_tons=10.0)["id"])
        so_a = create_spot_order_for_car(car_a["id"], trk["id"], 1,
                                         "2026-08-03T10:00:00Z",
                                         "2026-08-03T11:00:00Z")
        so_a = schedule_spot_order(so_a["id"])
        so_b = create_spot_order_for_car(car_b["id"], trk["id"], 2,
                                         "2026-08-03T12:00:00Z",
                                         "2026-08-03T13:00:00Z")
        so_b = schedule_spot_order(so_b["id"])
        set_clock("2026-08-03T10:30:00Z")
        execute_spot_order(so_a["id"])
        to_a = create_transfer_for(car_a["id"], eq["id"], 10.0)
        get_success_data(api.activate_transfer_order(to_a["id"], OPERATOR))
        wt_a = create_draft_ticket(to_a["id"], gross_weight_tons=24.0,
                                   tare_weight_tons=14.0,
                                   truck_max_payload_tons=40.0)
        certify_ticket(wt_a["id"])
        set_clock("2026-08-03T13:30:00Z")
        return {
            "customer": cust, "track": trk, "car_a": car_a,
            "sw_a_id": so_a["switch_order_id"],
            "sw_b_id": so_b["switch_order_id"],
        }

    def test_switching_fee_free_allowance_first_move(self, api):
        """PRD §3.4: "First, count the customer's existing switch orders — any
        status, including `CANCELLED` — whose `window_start` falls in the same
        UTC calendar month as the new move's `window_start`; call that the
        prior count. The new move's `sequence_number` is the prior count plus
        one. If the `sequence_number` is within the facility's
        `free_switches_per_period`, the `fee_cents` is zero; otherwise it is
        the base fee for the move type — 18500 cents for a `SPOT` move, 20500
        cents for a `PULL` move."
        PRD §3.4: "a `SCHEDULED` switch order completes when its purpose is
        fulfilled (spot-order execution for `SPOT` moves, railcar departure
        for `PULL` moves)"

        Design: Difficulty/combinatorial_formula/switching_fee_allowance_sequence
        """
        ctx = self._switching_setup(api)
        sw_a = validate_success(api.get_switch_order(ctx["sw_a_id"], YARD))
        assert sw_a["sequence_number"] == 1, "first move of the month"
        assert sw_a["fee_cents"] == 0, "sequence 1 within the free allowance of 1"
        assert sw_a["status"] == "COMPLETED", "execute completed the SPOT move"

        sw_b = validate_success(api.get_switch_order(ctx["sw_b_id"], YARD))
        assert sw_b["sequence_number"] == 2
        assert sw_b["fee_cents"] == 18500, "second move pays the SPOT base fee"

    def test_switching_fee_sequence_and_pull_fee(self, api):
        """PRD §3.4: "First, count the customer's existing switch orders — any
        status, including `CANCELLED` — whose `window_start` falls in the same
        UTC calendar month as the new move's `window_start`; call that the
        prior count. The new move's `sequence_number` is the prior count plus
        one. If the `sequence_number` is within the facility's
        `free_switches_per_period`, the `fee_cents` is zero; otherwise it is
        the base fee for the move type — 18500 cents for a `SPOT` move, 20500
        cents for a `PULL` move."
        PRD §3.7: "a `SwitchOrder` of `move_type` `PULL` is created for the
        crew window starting at `released_timestamp` and ending 30 minutes
        later, with `sequence_number` and `fee_cents` computed per the
        switching-fee rule and an accompanying `ACCRUED` `SWITCHING` charge,
        the switch order starting `SCHEDULED`"

        Design: Difficulty/combinatorial_formula/switching_fee_allowance_sequence
        """
        ctx = self._switching_setup(api)
        released = validate_success(api.release_railcar(ctx["car_a"]["id"], YARD))
        assert released["placement_status"] == "RELEASED"

        pulls = [s for s in list_all_switch_orders() if s["move_type"] == "PULL"]
        assert len(pulls) == 1
        pull = pulls[0]
        assert pull["sequence_number"] == 3, (
            "the two earlier SPOT moves count; the PULL never counts itself"
        )
        assert pull["fee_cents"] == 20500, "PULL base fee"
        assert pull["status"] == "SCHEDULED"
        assert pull["window_start"][:19] == "2026-08-03T13:30:00"
        assert pull["window_end"][:19] == "2026-08-03T14:00:00"


class TestInvoiceRounding:
    def _invoice_rounding_setup(self, api):
        """Two HAZARDOUS cars of a CREDIT_WATCH customer, each accruing
        exactly one billable demurrage day: 7500 x 1.5 x 1.25 = 14062.5 cents
        per line before the per-line rounding."""
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-INV")
        cust = create_customer(name="WATCH", allocated_car_spots=10,
                               credit_standing="CREDIT_WATCH")
        prod = create_product(name="Acid", hazard_class="HAZARDOUS",
                              segregation_group="CHEMICAL",
                              requires_full_clean=False)
        cars = []
        for i, number in enumerate(("30001", "30002"), start=1):
            lot = create_lot(cust["id"], prod["id"])
            trk = create_track(name=f"T{i}", spot_capacity=1)
            eq = create_equipment(name=f"PUMP-{i}", equipment_type="PUMP")
            car = arrive_car(create_railcar(cust["id"], prod["id"], lot["id"],
                                            car_number=number,
                                            quantity_loaded_tons=20.0)["id"])
            so = create_spot_order_for_car(car["id"], trk["id"], 1,
                                           "2026-08-03T10:00:00Z",
                                           "2026-08-03T12:00:00Z")
            schedule_spot_order(so["id"])
            set_clock("2026-08-03T10:30:00Z")
            execute_spot_order(so["id"])
            to = create_transfer_for(car["id"], eq["id"], 20.0)
            get_success_data(api.activate_transfer_order(to["id"], OPERATOR))
            wt = create_draft_ticket(to["id"], gross_weight_tons=34.0,
                                     tare_weight_tons=14.0,
                                     truck_max_payload_tons=40.0,
                                     truck_reference=f"TRK-{i}")
            certify_ticket(wt["id"])
            cars.append(car["id"])
        # 64h after constructive arrival: 3840 - 2880 = 960 min -> 1 day
        set_clock("2026-08-05T16:00:00Z")
        for car_id in cars:
            get_success_data(api.release_railcar(car_id, YARD))
        inv = create_invoice_for(cust["id"])
        return cust, inv, cars

    def test_invoice_rounds_each_line_half_up(self, api):
        """PRD §2.5: "Whenever a calculation applies multipliers (as demurrage
        does), the rounding to integer cents happens exactly once,
        round-half-up, after all multipliers have been applied — charge lines
        are never re-rounded downstream."
        PRD §3.3: "The final `amount_cents` is the tiered subtotal times both
        multipliers, rounded half-up to integer cents in a single rounding."

        Design: Difficulty/combinatorial_formula/invoice_line_rounding_then_sum
        """
        _cust, _inv, cars = self._invoice_rounding_setup(api)
        dem = sorted(
            (c for c in list_all_charges() if c["charge_type"] == "DEMURRAGE"),
            key=lambda c: c["railcar_id"],
        )
        assert len(dem) == 2
        for line in dem:
            # 7500 x 1.5 x 1.25 = 14062.5 -> round-half-up per line
            assert line["amount_cents"] == 14063
            assert line["quantity"] == 1

    def test_invoice_total_sums_rounded_lines(self, api):
        """PRD §3.8: "Rounding order is pinned: each charge line was already
        rounded to integer cents when it was created, and the invoice never
        re-rounds a sum of unrounded values — it sums the line amounts as they
        stand."
        PRD §3.8: "Otherwise each swept charge moves from `ACCRUED` to
        `INVOICED` with `invoice_id` set to this invoice (bumping each charge's
        version), and the invoice's `charge_count` is set to the number swept
        while `total_cents` is the integer sum of the swept lines'
        `amount_cents`."

        Design: Difficulty/combinatorial_formula/invoice_line_rounding_then_sum
        """
        _cust, inv, _cars = self._invoice_rounding_setup(api)
        issued = validate_success(api.issue_invoice(inv["id"], BILLING))
        assert issued["status"] == "ISSUED"
        # 2x18500 spot-switch + 2x20500 pull-switch + 2x14063 demurrage
        assert issued["total_cents"] == 106126, (
            "sum of line-rounded amounts (28126 demurrage, not the 28125 a "
            "sum-then-round would give)"
        )
        assert issued["charge_count"] == 6


class TestCleaningLoop:
    def test_cleaning_loop_bills_each_attempt(self, api):
        """PRD §3.7: "Each start-cleaning — including every re-clean after a
        failed attempt — creates an `ACCRUED` `ChargeEntry` of `charge_type`
        `CLEANING` on the car's customer with `quantity` 1: 250000 cents for a
        rinse, 600000 cents for detergent, 1200000 cents for steam, with the
        line's `unit_rate_cents` equal to its `amount_cents`. The car moves to
        `CLEANING`. From there, failing the wash returns the car to
        `EMPTY_AWAITING_CLEANING` (the charge stands; the loop may repeat,
        adding another charge per attempt), and passing it moves the car to
        `READY_FOR_RELEASE`."

        Design: Corner/state_machines/cleaning_loop_fee_schedule
        """
        # Drive to EMPTY_AWAITING_CLEANING with a full-clean product (no
        # cleaning yet): certify the full load, stop before any wash.
        ctx = setup_active_transfer(
            quantity_planned_tons=5.0, quantity_loaded_tons=5.0,
            car_number="96701",
            product_overrides={"name": "Flour", "hazard_class": "FOOD_GRADE",
                               "segregation_group": "FOOD_GRAIN",
                               "requires_full_clean": True},
        )
        wt = create_draft_ticket(ctx["transfer"]["id"], gross_weight_tons=19.0,
                                 tare_weight_tons=14.0, truck_max_payload_tons=40.0)
        certify_ticket(wt["id"])
        car_id = ctx["car"]["id"]
        assert get_railcar(car_id)["placement_status"] == "EMPTY_AWAITING_CLEANING"

        set_clock("2026-08-03T02:05:00Z")
        c1 = validate_success(api.start_railcar_cleaning(car_id, "RINSE", OPERATOR))
        assert c1["placement_status"] == "CLEANING"
        f1 = validate_success(api.fail_railcar_cleaning(car_id, OPERATOR))
        assert f1["placement_status"] == "EMPTY_AWAITING_CLEANING"

        set_clock("2026-08-03T02:10:00Z")
        validate_success(api.start_railcar_cleaning(car_id, "STEAM", OPERATOR))
        validate_success(api.fail_railcar_cleaning(car_id, OPERATOR))

        set_clock("2026-08-03T02:20:00Z")
        validate_success(api.start_railcar_cleaning(car_id, "DETERGENT", OPERATOR))
        passed = validate_success(api.pass_railcar_cleaning(car_id, OPERATOR))
        assert passed["placement_status"] == "READY_FOR_RELEASE"

        charges = [c for c in list_all_charges()
                   if c["charge_type"] == "CLEANING" and c["railcar_id"] == car_id]
        assert [c["amount_cents"] for c in charges] == [250000, 1200000, 600000], (
            "one ACCRUED charge per attempt, failed attempts not refunded; "
            "created_at-ordered list gives RINSE, STEAM, DETERGENT order"
        )
        for c in charges:
            assert c["status"] == "ACCRUED"
            assert c["quantity"] == 1
            assert c["unit_rate_cents"] == c["amount_cents"]
