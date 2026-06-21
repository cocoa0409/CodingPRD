"""Reservation / Equipment / Contract / Transfer lifecycles, the cascades they
fire (PRD §2.9, §3.6, §3.7, §3.9), and the compensating-action invariants that
conserve lot counts and supply stock (PRD §3.6, §3.7).
"""

from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_round_trip_confirmed, setup_round_trip_dispatched, setup_round_trip_returned,
    setup_one_way_dispatched, setup_transfer_requested,
    create_equipment_class, create_location, create_equipment, create_customer,
    create_coverage_plan, create_supply, create_reservation, confirm_reservation,
    dispatch_reservation, return_contract, settle_contract, file_damage,
    add_supply_line, get_ledger, ledger_lines_of_kind, get_location, get_equipment,
    get_reservation, get_supply, make_customer_headers,
    TEST_USERS,
)

FM = TEST_USERS["fleet_manager_headers"]
LA = TEST_USERS["location_agent_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Rule 3 — non-linear state-machine shape on different entities
# ─────────────────────────────────────────────────────────────────────────
class TestReservationParallelDimensions:
    """Reservation carries two independent state axes: booking_status advances
    while fulfillment_status holds, then fulfillment advances while booking holds."""

    def test_confirm_advances_booking_only(self):
        """PRD §3.6: "A `Customer` confirms their own `PENDING` reservation, advancing `booking_status` from `PENDING` to `CONFIRMED`."
        PRD §3.3: "The `booking_status` begins at `PENDING` and the `fulfillment_status` begins at `AWAITING_DISPATCH`; these two are independent dimensions, and the fulfillment dimension only advances while the booking dimension is `CONFIRMED`."

        Design: Difficulty/non_linear_state_machine/reservation_parallel_dimensions_independent
        """
        s = setup_round_trip_confirmed(
            class_overrides={"requires_coverage": False},
            customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
        )
        assert s["reservation"]["booking_status"] == "CONFIRMED"
        assert s["reservation"]["fulfillment_status"] == "AWAITING_DISPATCH"

    def test_dispatch_advances_fulfillment_only(self):
        """PRD §3.6: "A `LocationAgent` dispatches a `CONFIRMED` reservation, advancing `fulfillment_status` from `AWAITING_DISPATCH` to `DISPATCHED` while the booking dimension stays `CONFIRMED`."

        Design: Difficulty/non_linear_state_machine/reservation_parallel_dimensions_independent
        """
        s = setup_round_trip_dispatched(
            class_overrides={"requires_coverage": False},
            customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
        )
        resv = get_reservation(s["reservation"]["id"], s["customer"])
        assert resv["booking_status"] == "CONFIRMED"
        assert resv["fulfillment_status"] == "DISPATCHED"


class TestContractBranchingCleanVsDamaged:
    """RentalContract forks at return into RETURNED_CLEAN vs RETURNED_DAMAGED based
    on whether a DamageReport exists at return time."""

    def test_return_with_damage_report_branches_damaged(self):
        """PRD §3.6: "if at least one damage report exists it moves from `ACTIVE` to `RETURNED_DAMAGED`."

        Design: Difficulty/non_linear_state_machine/contract_branching_clean_vs_damaged
        """
        cov = create_coverage_plan(daily_fee_cents=1500, damage_deductible_cents=15000)
        cls = create_equipment_class(requires_coverage=True)
        hub = create_location(name="HUB", lot_capacity=5)
        create_equipment(cls["id"], hub["id"], odometer_miles=0, fuel_level_eighths=8)
        cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
        resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                                  coverage_plan_id=cov["id"], coverage_choice="SELECTED",
                                  scheduled_pickup_at="2026-07-01T09:00:00Z",
                                  scheduled_return_at="2026-07-02T09:00:00Z")
        confirmed = confirm_reservation(resv["id"], cust)
        contract = dispatch_reservation(confirmed["id"], confirmed["version"])
        file_damage(contract["id"], 50000, "Dented rear door")
        returned = return_contract(contract["id"], 0, 8, "2026-07-02T09:00:00Z")
        assert returned["status"] == "RETURNED_DAMAGED"

    def test_return_without_damage_report_branches_clean(self):
        """PRD §3.6: "if no damage report exists for the contract at return time it moves from `ACTIVE` to `RETURNED_CLEAN".

        Design: Difficulty/non_linear_state_machine/contract_branching_clean_vs_damaged
        """
        s = setup_round_trip_returned(
            return_odometer_miles=0, return_fuel_eighths=8,
            actual_return_at="2026-07-02T09:00:00Z",
            class_overrides={"requires_coverage": False},
            equipment_overrides={"odometer_miles": 0, "fuel_level_eighths": 8},
            customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
            reservation_overrides={"scheduled_pickup_at": "2026-07-01T09:00:00Z",
                                   "scheduled_return_at": "2026-07-02T09:00:00Z"},
        )
        assert s["contract"]["status"] == "RETURNED_CLEAN"


# ─────────────────────────────────────────────────────────────────────────
# Rule 4 — transitive cascade chains from different triggers
# ─────────────────────────────────────────────────────────────────────────
class TestReturnCascadeDepth3:
    """Return mutates contract -> drives Equipment IN_TRANSIT->AVAILABLE at drop-off
    -> recomputes the drop-off location's on_lot_count."""

    def _return(self):
        s = setup_one_way_dispatched(
            pick_overrides={"name": "PICK", "state_code": "CA", "lot_capacity": 5},
            drop_overrides={"name": "DROP", "state_code": "NV", "lot_capacity": 5,
                            "accepts_one_way_dropoff": True},
            class_overrides={"requires_coverage": False},
            equipment_overrides={"odometer_miles": 0, "fuel_level_eighths": 8},
            customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
            reservation_overrides={"scheduled_pickup_at": "2026-07-01T09:00:00Z",
                                   "scheduled_return_at": "2026-07-02T09:00:00Z"},
        )
        return_contract(s["contract"]["id"], 25, 8, "2026-07-02T09:00:00Z")
        return s

    def test_equipment_lands_available_at_dropoff(self):
        """PRD §3.6: "On a successful return the system computes `miles_driven` as the closing odometer minus the pickup odometer, advances the unit from `IN_TRANSIT` to `AVAILABLE`, sets the unit's `current_location_id` to the drop-off location, updates the unit's `odometer_miles` and `fuel_level_eighths` to the closing readings, and recomputes the drop-off location's `on_lot_count`."

        Design: Difficulty/transitive_cascade/return_cascade_contract_to_equipment_to_location_depth3
        """
        s = self._return()
        eq = get_equipment(s["eq"]["id"])
        assert eq["status"] == "AVAILABLE"
        assert eq["current_location_id"] == s["drop"]["id"]

    def test_dropoff_on_lot_count_recomputed(self):
        """PRD §2.6: "The `on_lot_count` is recomputed on every dispatch, every return, every transfer completion, and any other event that changes which units sit on a lot".

        Design: Difficulty/transitive_cascade/return_cascade_contract_to_equipment_to_location_depth3
        """
        s = self._return()
        drop = get_location(s["drop"]["id"])
        assert drop["on_lot_count"] == 1


class TestSettleCascadeDepth2:
    """Settle emits ChargeLedgerEntry rows AND bubbles the reservation's
    fulfillment_status DISPATCHED->COMPLETED."""

    def _settle(self):
        s = setup_round_trip_returned(
            return_odometer_miles=0, return_fuel_eighths=8,
            actual_return_at="2026-07-02T09:00:00Z",
            class_overrides={"requires_coverage": False},
            equipment_overrides={"odometer_miles": 0, "fuel_level_eighths": 8},
            customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
            reservation_overrides={"scheduled_pickup_at": "2026-07-01T09:00:00Z",
                                   "scheduled_return_at": "2026-07-02T09:00:00Z"},
        )
        settle_contract(s["contract"]["id"], s["contract"]["version"])
        return s

    def test_settle_bubbles_reservation_to_completed(self):
        """PRD §3.7: "Settlement runs the contract-settlement calculation, sets `settlement_total_cents`, increments the contract's `version`, and bubbles the linked reservation's `fulfillment_status` from `DISPATCHED` to `COMPLETED`."

        Design: Difficulty/transitive_cascade/settle_cascade_contract_to_ledger_to_reservation_depth2
        """
        s = self._settle()
        resv = get_reservation(s["reservation"]["id"], s["customer"])
        assert resv["fulfillment_status"] == "COMPLETED"

    def test_settle_emits_base_days_ledger_line(self):
        """PRD §3.7: "The clean branch emits a `BASE_DAYS` line, either a `MILEAGE` line or a `ONE_WAY_FLAT` line depending on trip type, an `ADDON` line, a `COVERAGE` line, a `FUEL_SHORTFALL` line, a `LATE_RETURN` line, a `SUPPLY` line, and — for each returnable supply line that yields a refund — a negative `SUPPLY_REFUND` line".

        Design: Difficulty/transitive_cascade/settle_cascade_contract_to_ledger_to_reservation_depth2
        """
        s = self._settle()
        ledger = get_ledger(s["contract"]["id"])
        assert len(ledger_lines_of_kind(ledger, "BASE_DAYS")) >= 1


# ─────────────────────────────────────────────────────────────────────────
# Rule 9 — compensating-action invariants across conserved quantities
# ─────────────────────────────────────────────────────────────────────────
class TestVoidConservesLotCount:
    """Dispatch decrements pickup on_lot_count by 1; voiding restores it."""

    def _void(self):
        s = setup_round_trip_dispatched(
            location_overrides={"name": "HUB", "lot_capacity": 5},
            class_overrides={"requires_coverage": False},
            customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
        )
        get_success_data(api_client.void_contract(s["contract"]["id"], FM))
        return s

    def test_void_restores_lot_count_and_equipment(self):
        """PRD §3.7: "Voiding rolls the dispatched unit back to `AVAILABLE` at its pickup location and recomputes that location's `on_lot_count`, returns the reservation's `fulfillment_status` from `DISPATCHED` to `AWAITING_DISPATCH` while clearing the reservation's `assigned_equipment_id`, and increments the contract's `version`."

        Design: Difficulty/compensating_invariant/void_contract_conserves_location_lot_count
        """
        s = self._void()
        loc = get_location(s["loc"]["id"])
        assert loc["on_lot_count"] == 1
        eq = get_equipment(s["eq"]["id"])
        assert eq["status"] == "AVAILABLE"
        assert eq["current_location_id"] == s["loc"]["id"]

    def test_void_returns_reservation_to_awaiting_dispatch(self):
        """PRD §3.7: "returns the reservation's `fulfillment_status` from `DISPATCHED` to `AWAITING_DISPATCH` while clearing the reservation's `assigned_equipment_id".

        Design: Difficulty/compensating_invariant/void_contract_conserves_location_lot_count
        """
        s = self._void()
        resv = get_reservation(s["reservation"]["id"], s["customer"])
        assert resv["fulfillment_status"] == "AWAITING_DISPATCH"
        assert resv["assigned_equipment_id"] is None


class TestCancelConservesSupplyStock:
    """Adding a SupplyLineItem decrements stock_qty; cancelling restores it."""

    def _setup_and_cancel(self):
        cls = create_equipment_class(requires_coverage=False)
        hub = create_location(name="HUB", lot_capacity=5)
        wb = create_supply(sku="WARDROBE_BOX", unit_price_cents=1200, stock_qty=10)
        cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
        resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                                  scheduled_pickup_at="2026-07-01T09:00:00Z",
                                  scheduled_return_at="2026-07-02T09:00:00Z")
        add_supply_line(resv["id"], cust, wb["id"], 4)
        get_success_data(
            api_client.cancel_reservation(resv["id"], make_customer_headers(cust["id"]))
        )
        return wb, resv, cust

    def test_cancel_restores_supply_stock(self):
        """PRD §3.6: "Cancellation advances `booking_status` to `CANCELLED`, restores `stock_qty` to the catalog for every supply line on the reservation, releases any unit that was `RESERVED` for this reservation back to `AVAILABLE` while clearing `assigned_equipment_id` and recomputing that unit's current location's `on_lot_count`, and increments the reservation's `version`."

        Design: Difficulty/compensating_invariant/cancel_reservation_conserves_supply_stock_total
        """
        wb, _, _ = self._setup_and_cancel()
        supply = get_supply(wb["id"])
        assert supply["stock_qty"] == 10

    def test_cancel_marks_reservation_cancelled(self):
        """PRD §3.6: "Cancellation advances booking_status to CANCELLED".

        Design: Difficulty/compensating_invariant/cancel_reservation_conserves_supply_stock_total
        """
        _, resv, cust = self._setup_and_cancel()
        fetched = get_reservation(resv["id"], cust)
        assert fetched["booking_status"] == "CANCELLED"


# ─────────────────────────────────────────────────────────────────────────
# Queue B — corner state-machine instances
# ─────────────────────────────────────────────────────────────────────────
def test_create_reservation_returns_201_with_derived_fields():
    """PRD §3.3: "The `trip_type` is computed as `ROUND_TRIP` when the pickup and drop-off locations are the same and `ONE_WAY` when they differ. The `planned_days` is the number of whole 24-hour spans between the scheduled pickup and scheduled return, rounded up to the next whole day, with a floor of 1 day."

    Design: Corner/entities/create_reservation_returns_201_with_derived_fields
    """
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    from test_helpers import create_reservation_payload
    res = api_client.create_reservation(
        create_reservation_payload(cust["id"], cls["id"], hub["id"], hub["id"],
                                   scheduled_pickup_at="2026-07-01T09:00:00Z",
                                   scheduled_return_at="2026-07-03T09:00:00Z",
                                   coverage_choice="DECLINED"),
        make_customer_headers(cust["id"]),
    )
    created = validate_success(res, 201)
    assert created["trip_type"] == "ROUND_TRIP"
    assert created["planned_days"] == 2
    assert created["booking_status"] == "PENDING"
    assert created["fulfillment_status"] == "AWAITING_DISPATCH"


def test_equipment_initial_state_available_on_create():
    """PRD §3.2: "On creation the unit's `current_location_id` is set equal to its `home_location_id`, its `status` is `AVAILABLE`, and the home location's `on_lot_count` is recomputed."

    Design: Corner/state_machines/equipment_initial_state_available_on_create
    """
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    eq = validate_success(api_client.create_equipment(
        {"equipment_class_id": cls["id"], "home_location_id": hub["id"]}, FM), 201)
    assert eq["status"] == "AVAILABLE"


def test_equipment_computed_status_and_current_location_ignore_input():
    """PRD §3.2: "On creation the unit's `current_location_id` is set equal to its `home_location_id`, its `status` is `AVAILABLE`, and the home location's `on_lot_count` is recomputed."

    Design: Corner/entities/equipment_computed_status_and_current_location_ignore_input
    """
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    eq = validate_success(api_client.create_equipment(
        {"equipment_class_id": cls["id"], "home_location_id": hub["id"]}, FM), 201)
    assert eq["status"] == "AVAILABLE"
    assert eq["current_location_id"] == hub["id"]
    loc = get_location(hub["id"])
    assert loc["on_lot_count"] == 1


def test_transfer_complete_lands_unit_and_rebalances_lots():
    """PRD §3.9: "Completion re-checks that the destination's `on_lot_count` is strictly below its `lot_capacity` at completion time (else `ERR_RETURN_LOT_FULL`), then moves the unit from `IN_TRANSIT` to `AVAILABLE`, sets the unit's `current_location_id` to the `to_location_id`, and recomputes both the destination's and the origin's `on_lot_count`, incrementing the transfer's `version`."

    Design: Corner/state_machines/transfer_complete_lands_unit_and_rebalances_lots
    """
    t = setup_transfer_requested(
        from_overrides={"name": "FROM", "state_code": "CA", "lot_capacity": 5},
        to_overrides={"name": "TO", "state_code": "NV", "lot_capacity": 5},
        reason="FLEET_REBALANCE",
    )
    get_success_data(api_client.approve_transfer(t["transfer"]["id"], FM))
    completed = validate_success(api_client.complete_transfer(t["transfer"]["id"], LA), 200)
    assert completed["status"] == "COMPLETED"
    eq = get_equipment(t["eq"]["id"])
    assert eq["current_location_id"] == t["to_loc"]["id"]
    assert get_location(t["from_loc"]["id"])["on_lot_count"] == 0
    assert get_location(t["to_loc"]["id"])["on_lot_count"] == 1


def test_reject_transfer_leaves_equipment_available():
    """PRD §3.9: "A `FleetManager` may instead reject a `REQUESTED` transfer, advancing it to `REJECTED` and incrementing its `version`."

    Design: Corner/state_machines/reject_transfer_leaves_equipment_available
    """
    t = setup_transfer_requested(
        from_overrides={"name": "FROM", "state_code": "CA", "lot_capacity": 5},
        to_overrides={"name": "TO", "state_code": "NV", "lot_capacity": 5},
        reason="FLEET_REBALANCE",
    )
    rejected = validate_success(api_client.reject_transfer(t["transfer"]["id"], FM), 200)
    assert rejected["status"] == "REJECTED"
    eq = get_equipment(t["eq"]["id"])
    assert eq["status"] == "AVAILABLE"
    assert eq["current_location_id"] == t["from_loc"]["id"]


def test_derived_on_lot_count_reconciles_after_dispatch():
    """PRD §2.6: "Units in `DISPATCHED`, `IN_TRANSIT`, or `RETIRED` status do not occupy a slot and are excluded from the count. The `on_lot_count` is recomputed on every dispatch, every return, every transfer completion".

    Design: Corner/cross_cutting_complexity_layers/derived_on_lot_count_reconciles_after_dispatch
    """
    s = setup_round_trip_confirmed(
        location_overrides={"name": "HUB", "lot_capacity": 5},
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    assert get_location(s["loc"]["id"])["on_lot_count"] == 1
    dispatch_reservation(s["reservation"]["id"], s["reservation"]["version"])
    assert get_location(s["loc"]["id"])["on_lot_count"] == 0
