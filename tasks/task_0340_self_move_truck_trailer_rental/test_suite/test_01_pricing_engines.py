"""Pricing engines: the forward-looking reservation quote (PRD §3.5) and the
chronological contract settlement (PRD §3.7), including their divergence,
multi-input non-linear combinations, per-component rounding, and the
late-return grace boundary.

Every literal expected value is copied verbatim from the design indices.
"""

from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_round_trip_returned,
    create_equipment_class, create_location, create_equipment, create_customer,
    create_coverage_plan, create_supply, create_reservation, confirm_reservation,
    dispatch_reservation, return_contract, settle_contract,
    add_supply_line, add_addon_line, file_damage, get_ledger, sum_ledger_kind,
    ledger_lines_of_kind, make_customer_headers,
    create_reservation_payload, TEST_USERS,
)

FM = TEST_USERS["fleet_manager_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Rule 1 — dual-variant calculations across different entity domains
# ─────────────────────────────────────────────────────────────────────────
class TestQuoteVsSettlementTripCostDiverge:
    """The forward-looking quote and the actuals-based settlement consume the
    SAME round-trip reservation but produce different mileage components, so
    quoted_total_cents != settlement_total_cents."""

    def _run(self):
        # SILVER, daily 4000, mileage 100, round-trip 2 days, 137 actual miles, no shortfall.
        s = setup_round_trip_returned(
            return_odometer_miles=1137, return_fuel_eighths=8,
            actual_return_at="2026-07-03T09:00:00Z",
            class_overrides={"daily_rate_cents": 4000, "mileage_rate_cents": 100,
                             "one_way_flat_cents": 9900, "fuel_capacity_gallons": 40,
                             "requires_coverage": False},
            equipment_overrides={"odometer_miles": 1000, "fuel_level_eighths": 8},
            customer_overrides={"license_verified": True, "loyalty_tier": "SILVER"},
            reservation_overrides={"scheduled_pickup_at": "2026-07-01T09:00:00Z",
                                   "scheduled_return_at": "2026-07-03T09:00:00Z",
                                   "coverage_choice": "DECLINED"},
        )
        settled = settle_contract(s["contract"]["id"], s["contract"]["version"])
        return s, settled

    def test_quote_uses_estimated_mileage(self):
        """PRD §3.5: "For a round-trip reservation the system estimates mileage using a fixed assumed distance of 60 miles: it multiplies the class's `mileage_rate_cents` by those 60 estimated miles (this raw mileage is zero for any non-`TRUCK` category), then applies the loyalty discount to that mileage figure alone."

        Design: Difficulty/dual_variant_calc/quote_vs_settlement_trip_cost_diverge
        """
        s, _ = self._run()
        resv = get_success_data(
            api_client.get_reservation(s["reservation"]["id"],
                                       make_customer_headers(s["customer"]["id"]))
        )
        # base 4000*2=8000 + mileage 100*60*0.9=5400 = 13400.
        assert resv["quoted_total_cents"] == 13400

    def test_settlement_uses_actual_mileage_and_diverges_from_quote(self):
        """PRD §3.7: "for a round-trip (`TRUCK` only) it is the class's `mileage_rate_cents` multiplied by the actual `miles_driven`, with the loyalty discount applied to that mileage component".

        Design: Difficulty/dual_variant_calc/quote_vs_settlement_trip_cost_diverge
        """
        s, settled = self._run()
        # base 8000 + mileage 100*137*0.9=12330 = 20330.
        assert settled["settlement_total_cents"] == 20330
        resv = get_success_data(
            api_client.get_reservation(s["reservation"]["id"],
                                       make_customer_headers(s["customer"]["id"]))
        )
        assert settled["settlement_total_cents"] != resv["quoted_total_cents"]


class TestAvailabilityDispatchPoolVsLotOccupancy:
    """On the same location, the dispatch-ready pool counts only AVAILABLE while
    on_lot_count counts AVAILABLE + RESERVED + MAINTENANCE."""

    def _setup(self):
        cls = create_equipment_class(requires_coverage=False)
        hub = create_location(name="HUB", lot_capacity=5)
        create_equipment(cls["id"], hub["id"])               # stays AVAILABLE
        eq_maint = create_equipment(cls["id"], hub["id"])     # -> MAINTENANCE
        create_equipment(cls["id"], hub["id"])                # -> RESERVED via confirm
        get_success_data(api_client.maintenance_equipment(eq_maint["id"], FM))
        cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
        resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                                  coverage_choice="DECLINED")
        confirm_reservation(resv["id"], cust)  # earmarks one unit -> RESERVED
        return cls, hub

    def test_dispatch_pool_counts_only_available(self):
        """PRD §2.8: "The **dispatch-ready pool** for a class at a location counts only units whose `status` is exactly `AVAILABLE` with `current_location_id` equal to that location — earmarked (`RESERVED`), in-maintenance, and dispatched units are excluded from the free pool."

        Design: Difficulty/dual_variant_calc/availability_dispatch_pool_vs_lot_occupancy_diverge
        """
        cls, hub = self._setup()
        avail = get_success_data(
            api_client.get_location_availability(
                hub["id"], FM, params={"equipment_class_id": cls["id"]},
            )
        )
        # PRD §3.10 does not pin the keying of the per-class object; resolve the
        # entry for this class by either its code or its id, then assert the value.
        classes = avail["classes"]
        cls_view = classes.get(cls["code"]) or classes.get(cls["id"])
        assert cls_view is not None, f"no per-class entry for class in {classes}"
        assert cls_view["available_count"] == 1

    def test_lot_occupancy_counts_available_reserved_maintenance(self):
        """PRD §2.6: "The `on_lot_count` is the number of equipment units whose `current_location_id` equals that location and whose `status` is one of `AVAILABLE`, `RESERVED`, or `MAINTENANCE".

        Design: Difficulty/dual_variant_calc/availability_dispatch_pool_vs_lot_occupancy_diverge
        """
        cls, hub = self._setup()
        loc = get_success_data(api_client.get_location(hub["id"], FM))
        assert loc["on_lot_count"] == 3


# ─────────────────────────────────────────────────────────────────────────
# Rule 2 — combinatorial formulas across different modes
# ─────────────────────────────────────────────────────────────────────────
class TestSettlementMultiInputModeA:
    """Settlement combines >=3 interacting inputs with non-linear branches:
    rental_days, tiered mileage discount, conditional fuel-shortfall, conditional
    coverage, supplies net of refund."""

    def _settle(self):
        cls = create_equipment_class(daily_rate_cents=4000, mileage_rate_cents=100,
                                     one_way_flat_cents=9900, fuel_capacity_gallons=40,
                                     requires_coverage=True)
        cov = create_coverage_plan(daily_fee_cents=1500, damage_deductible_cents=15000)
        box = create_supply(unit_price_cents=250, stock_qty=100, returnable=True)
        hub = create_location(name="HUB", lot_capacity=5)
        eq = create_equipment(cls["id"], hub["id"], odometer_miles=0, fuel_level_eighths=8)
        cust = create_customer(license_verified=True, loyalty_tier="GOLD")
        resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                                  coverage_plan_id=cov["id"], coverage_choice="SELECTED",
                                  scheduled_pickup_at="2026-07-01T09:00:00Z",
                                  scheduled_return_at="2026-07-03T09:00:00Z")
        add_addon_line(resv["id"], cust, "UTILITY_DOLLY", 1)
        add_supply_line(resv["id"], cust, box["id"], 3)
        confirmed = confirm_reservation(resv["id"], cust)
        contract = dispatch_reservation(confirmed["id"], confirmed["version"])
        returned = return_contract(contract["id"], 80, 8, "2026-07-03T09:00:00Z")
        return settle_contract(returned["id"], returned["version"])

    def test_clean_settlement_has_zero_damage_charge(self):
        """PRD §3.7: "The damage charge is zero on a clean settlement."

        Design: Difficulty/combinatorial_formula/settlement_nonlinear_multi_input_mode_a
        """
        settled = self._settle()
        assert settled["damage_charge_cents"] == 0


class TestSupplyRefundRoundPerLineModeB:
    """supply_refund rounds half-up PER returnable line BEFORE summing: two lines
    of unit_price 333 refunding 1 unit each yield 167+167=334, not 333."""

    def _settle(self):
        cls = create_equipment_class(requires_coverage=False)
        boxa = create_supply(unit_price_cents=333, stock_qty=50, returnable=True)
        boxb = create_supply(unit_price_cents=333, stock_qty=50, returnable=True)
        hub = create_location(name="HUB", lot_capacity=5)
        create_equipment(cls["id"], hub["id"], odometer_miles=0, fuel_level_eighths=8)
        cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
        resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                                  scheduled_pickup_at="2026-07-01T09:00:00Z",
                                  scheduled_return_at="2026-07-02T09:00:00Z")
        add_supply_line(resv["id"], cust, boxa["id"], 1)
        add_supply_line(resv["id"], cust, boxb["id"], 1)
        confirmed = confirm_reservation(resv["id"], cust)
        contract = dispatch_reservation(confirmed["id"], confirmed["version"])
        returned = return_contract(contract["id"], 0, 8, "2026-07-02T09:00:00Z")
        settled = settle_contract(returned["id"], returned["version"])
        return settled, get_ledger(returned["id"])

    def test_supply_refund_ledger_sums_per_line_rounded(self):
        """PRD §3.7: "The supply refund is the sum over every returnable supply line of that line's `unit_price_cents` times its `refunded_units` times the refund fraction of one-half, each such per-line refund rounded half up before summation."

        Design: Difficulty/combinatorial_formula/supply_refund_round_per_line_then_sum_mode_b
        """
        _, ledger = self._settle()
        assert sum_ledger_kind(ledger, "SUPPLY_REFUND") == -334

    def test_settlement_total_with_per_line_refund(self):
        """PRD §3.7: "The settlement total is the exact integer sum of base, trip component, add-ons, coverage, fuel shortfall, late fee, and damage charge, plus supplies, minus the supply refund — each rounded component being summed as an already-rounded integer."

        Design: Difficulty/combinatorial_formula/supply_refund_round_per_line_then_sum_mode_b
        """
        settled, _ = self._settle()
        # base 4000 + supplies 666 - refund 334 = 4332.
        assert settled["settlement_total_cents"] == 4332


# ─────────────────────────────────────────────────────────────────────────
# Rule 6 — boundary precision: late-return grace 119 vs 120 minutes
# ─────────────────────────────────────────────────────────────────────────
class TestLateReturnGraceBoundary:
    """LATE_GRACE_MINUTES = 119: at 120 minutes late (>119) one late day applies."""

    def _settle_returned_at(self, actual_return_at):
        s = setup_round_trip_returned(
            return_odometer_miles=0, return_fuel_eighths=8,
            actual_return_at=actual_return_at,
            class_overrides={"requires_coverage": False},
            equipment_overrides={"odometer_miles": 0, "fuel_level_eighths": 8},
            customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
            reservation_overrides={"scheduled_pickup_at": "2026-07-01T09:00:00Z",
                                   "scheduled_return_at": "2026-07-02T09:00:00Z"},
        )
        settled = settle_contract(s["contract"]["id"], s["contract"]["version"])
        return settled, get_ledger(s["contract"]["id"])

    def test_120_minutes_late_charges_one_late_day(self):
        """PRD §3.7: "If the late minutes is within the 119-minute grace (that is, 119 minutes or fewer) there are zero late days; otherwise the late days is the amount by which the late minutes exceeds the grace, divided by the number of minutes in a day, rounded up. The late fee is the late days multiplied by 4000 cents per late day."

        Design: Difficulty/boundary_precision_check/late_return_grace_boundary_119_vs_120_minutes
        """
        # Returned 2026-07-02T11:00:00Z -> 120 minutes after scheduled 09:00.
        settled, ledger = self._settle_returned_at("2026-07-02T11:00:00Z")
        # rental_days = ceil(26h/24) = 2 -> base 8000; plus late_fee 4000 = 12000.
        assert settled["settlement_total_cents"] == 12000
        late_lines = ledger_lines_of_kind(ledger, "LATE_RETURN")
        assert len(late_lines) == 1
        assert late_lines[0]["amount_cents"] == 4000

    def test_119_minutes_late_within_grace_no_late_fee(self):
        """PRD §3.7: "If the late minutes is within the 119-minute grace (that is, 119 minutes or fewer) there are zero late days".

        Design: Difficulty/boundary_precision_check/late_return_grace_boundary_119_vs_120_minutes
        """
        # Returned 2026-07-02T10:59:00Z -> exactly 119 minutes late -> within grace.
        settled, ledger = self._settle_returned_at("2026-07-02T10:59:00Z")
        assert sum_ledger_kind(ledger, "LATE_RETURN") == 0


# ─────────────────────────────────────────────────────────────────────────
# Queue B — corner calculation instances
# ─────────────────────────────────────────────────────────────────────────
def test_one_way_quote_uses_flat_fee_not_mileage():
    """PRD §3.5: "For a one-way reservation the trip component is simply the class's `one_way_flat_cents`, and no mileage is quoted because actual miles are unknown at booking."

    Design: Corner/calculations/one_way_quote_uses_flat_fee_not_mileage
    """
    cls = create_equipment_class(daily_rate_cents=4000, one_way_flat_cents=9900,
                                 mileage_rate_cents=100, fuel_capacity_gallons=40,
                                 requires_coverage=False)
    pick = create_location(name="PICK", state_code="CA", lot_capacity=5)
    drop = create_location(name="DROP", state_code="NV", lot_capacity=5,
                           accepts_one_way_dropoff=True)
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    resv = create_reservation(cust, cls["id"], pick["id"], drop["id"],
                              scheduled_pickup_at="2026-07-01T09:00:00Z",
                              scheduled_return_at="2026-07-02T09:00:00Z")
    assert resv["trip_type"] == "ONE_WAY"
    # base 4000*1 + one_way_flat 9900 = 13900.
    assert resv["quoted_total_cents"] == 13900


def test_fuel_shortfall_one_eighth_charges_gallons_plus_service_fee():
    """PRD §3.7: "The fuel shortfall is the gallons short multiplied by a fuel price of 600 cents per gallon, rounded half up at this component, plus — whenever any eighths are missing at all — a flat refuel service fee of 3000 cents".

    Design: Corner/calculations/fuel_shortfall_one_eighth_charges_gallons_plus_service_fee
    """
    s = setup_round_trip_returned(
        return_odometer_miles=0, return_fuel_eighths=7,
        actual_return_at="2026-07-02T09:00:00Z",
        class_overrides={"fuel_capacity_gallons": 40, "requires_coverage": False},
        equipment_overrides={"odometer_miles": 0, "fuel_level_eighths": 8},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
        reservation_overrides={"scheduled_pickup_at": "2026-07-01T09:00:00Z",
                               "scheduled_return_at": "2026-07-02T09:00:00Z"},
    )
    settled = settle_contract(s["contract"]["id"], s["contract"]["version"])
    ledger = get_ledger(s["contract"]["id"])
    fuel_lines = ledger_lines_of_kind(ledger, "FUEL_SHORTFALL")
    # (40/8)*1*600 = 3000 + REFUEL_SERVICE_FEE 3000 = 6000.
    assert len(fuel_lines) == 1
    assert fuel_lines[0]["amount_cents"] == 6000
    # base 4000 + fuel 6000 = 10000.
    assert settled["settlement_total_cents"] == 10000


def test_damaged_settlement_declined_coverage_charges_full_gross():
    """PRD §3.7: "when coverage is `DECLINED` it is the full gross damage."

    Design: Corner/calculations/damaged_settlement_declined_coverage_charges_full_gross
    """
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    create_equipment(cls["id"], hub["id"], odometer_miles=0, fuel_level_eighths=8)
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                              coverage_choice="DECLINED",
                              scheduled_pickup_at="2026-07-01T09:00:00Z",
                              scheduled_return_at="2026-07-02T09:00:00Z")
    confirmed = confirm_reservation(resv["id"], cust)
    contract = dispatch_reservation(confirmed["id"], confirmed["version"])
    file_damage(contract["id"], 50000, "Major dent")
    returned = return_contract(contract["id"], 0, 8, "2026-07-02T09:00:00Z")
    settled = settle_contract(returned["id"], returned["version"])
    assert settled["damage_charge_cents"] == 50000
    # base 4000 + damage 50000 = 54000.
    assert settled["settlement_total_cents"] == 54000


def test_immediate_consistency_quote_in_create_response():
    """PRD §2.7: "The first, the **reservation quote**, is forward-looking: it runs at reservation creation and again at confirmation, and it estimates cost from planned dates and an assumed round-trip mileage constant rather than from any actual usage."

    Design: Corner/consistency_model/immediate_consistency_quote_in_create_response
    """
    cls = create_equipment_class(daily_rate_cents=4000, mileage_rate_cents=100,
                                 one_way_flat_cents=9900, fuel_capacity_gallons=40,
                                 requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    cust = create_customer(license_verified=True, loyalty_tier="SILVER")
    payload = create_reservation_payload(
        cust["id"], cls["id"], hub["id"], hub["id"],
        scheduled_pickup_at="2026-07-01T09:00:00Z",
        scheduled_return_at="2026-07-03T09:00:00Z",
        coverage_choice="DECLINED",
    )
    res = api_client.create_reservation(payload, make_customer_headers(cust["id"]))
    created = validate_success(res, 201)
    # round-trip SILVER 2 days: base 8000 + mileage 100*60*0.9=5400 = 13400.
    assert created["quoted_total_cents"] == 13400
    fetched = validate_success(
        api_client.get_reservation(created["id"], make_customer_headers(cust["id"])), 200
    )
    assert fetched["quoted_total_cents"] == 13400
