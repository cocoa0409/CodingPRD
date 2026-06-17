"""Business-rule constraints: validation-priority ordering (PRD §2.11), cross-entity
state dependencies (PRD §3.6, §3.9), resource temporal/lifecycle overlap (PRD §3.8,
§3.9), and the per-validation reservation/return/transfer rejections (PRD §3.3-§3.9).
"""

from test_helpers import (
    api_client, validate_error, validate_paginated, get_success_data,
    setup_round_trip_confirmed, setup_transfer_requested,
    create_equipment_class, create_location, create_equipment, create_customer,
    create_supply, create_reservation, confirm_reservation,
    dispatch_reservation, get_location,
    make_customer_headers, create_reservation_payload,
    create_supply_line_payload, create_transfer_payload, dispatch_payload,
    return_payload, MISSING_UUID, TEST_USERS,
)

FM = TEST_USERS["fleet_manager_headers"]
LA = TEST_USERS["location_agent_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Rule 5 — validation priority conflicts across error-category pairs
# ─────────────────────────────────────────────────────────────────────────
class TestStateBeatsSafetyOnDispatch:
    """A dispatch violating BOTH the state precondition (PENDING, not CONFIRMED)
    AND the safety precondition (TRUCK, unverified license) returns ERR_INVALID_STATE,
    proving state (priority 9) outranks business-safety (priority 10)."""

    def _trigger(self):
        cls = create_equipment_class(category="TRUCK", requires_coverage=False)
        hub = create_location(name="HUB", lot_capacity=5)
        create_equipment(cls["id"], hub["id"])
        cust = create_customer(license_verified=False, loyalty_tier="STANDARD")
        resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                                  scheduled_pickup_at="2026-07-01T09:00:00Z",
                                  scheduled_return_at="2026-07-02T09:00:00Z")
        # Reservation left PENDING (not confirmed); license unverified.
        return api_client.dispatch_reservation(
            resv["id"], dispatch_payload(resv["version"]), LA
        )

    def test_dispatch_pending_unverified_returns_invalid_state(self):
        """PRD §2.11: "For transition endpoints, the state-precondition check (`ERR_INVALID_STATE`) precedes the deeper business-safety, capacity, and temporal checks specific to that transition."

        Design: Difficulty/priority_pair_validation_conflict/state_before_safety_dispatch_wrong_state_and_unverified
        """
        res = self._trigger()
        validate_error(res, "ERR_INVALID_STATE")

    def test_dispatch_pending_unverified_http_409(self):
        """PRD §2.11: "For transition endpoints, the state-precondition check (`ERR_INVALID_STATE`) precedes the deeper business-safety, capacity, and temporal checks specific to that transition."

        Design: Difficulty/priority_pair_validation_conflict/state_before_safety_dispatch_wrong_state_and_unverified
        """
        res = self._trigger()
        assert res.status_code == 409


class TestExistenceBeatsStockOnSupply:
    """Adding a SupplyLineItem to a NON-EXISTENT reservation while ALSO over-requesting
    stock returns ERR_NOT_FOUND, proving existence (priority 4) outranks the stock
    check (priority 13)."""

    def _trigger(self):
        box = create_supply(sku="TINYBOX", unit_price_cents=100, stock_qty=1)
        return api_client.add_supply(
            MISSING_UUID, create_supply_line_payload(box["id"], 99), LA
        )

    def test_supply_to_missing_reservation_returns_not_found(self):
        """PRD §2.11: "Existence of every path identifier and body foreign key comes next (`ERR_NOT_FOUND`, validated left-to-right in the path and then over the body references)."
        PRD §2.11: "Only after those generic checks does the system evaluate the request-specific business rules."

        Design: Difficulty/priority_pair_validation_conflict/existence_before_stock_supply_bad_reservation_and_overstock
        """
        res = self._trigger()
        validate_error(res, "ERR_NOT_FOUND")

    def test_supply_to_missing_reservation_http_404(self):
        """PRD §2.11: "Existence of every path identifier and body foreign key comes next (`ERR_NOT_FOUND`, validated left-to-right in the path and then over the body references)."
        PRD §2.11: "Only after those generic checks does the system evaluate the request-specific business rules."

        Design: Difficulty/priority_pair_validation_conflict/existence_before_stock_supply_bad_reservation_and_overstock
        """
        res = self._trigger()
        assert res.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# Rule 7 — cross-entity state dependencies
# ─────────────────────────────────────────────────────────────────────────
class TestDispatchBlockedByUnverifiedLicense:
    """A CONFIRMED round-trip TRUCK reservation cannot dispatch while the owning
    Customer.license_verified is false."""

    def _setup(self):
        cls = create_equipment_class(category="TRUCK", requires_coverage=False)
        hub = create_location(name="HUB", lot_capacity=5)
        create_equipment(cls["id"], hub["id"])
        cust = create_customer(license_verified=False, loyalty_tier="STANDARD")
        resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                                  scheduled_pickup_at="2026-07-01T09:00:00Z",
                                  scheduled_return_at="2026-07-02T09:00:00Z")
        confirmed = confirm_reservation(resv["id"], cust)  # confirm has no license gate
        return confirmed, cust

    def test_dispatch_unverified_truck_returns_license_error(self):
        """PRD §3.6: "for a `TRUCK` class the holder's `license_verified` must be true (else `ERR_LICENSE_NOT_VERIFIED`)".

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_customer_license_unverified
        """
        confirmed, _ = self._setup()
        res = api_client.dispatch_reservation(
            confirmed["id"], dispatch_payload(confirmed["version"]), LA
        )
        validate_error(res, "ERR_LICENSE_NOT_VERIFIED")

    def test_dispatch_unverified_leaves_fulfillment_unchanged(self):
        """PRD §3.6: "for a `TRUCK` class the holder's `license_verified` must be true (else `ERR_LICENSE_NOT_VERIFIED`)".

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_customer_license_unverified
        """
        confirmed, cust = self._setup()
        api_client.dispatch_reservation(
            confirmed["id"], dispatch_payload(confirmed["version"]), LA
        )
        resv = get_success_data(
            api_client.get_reservation(confirmed["id"], make_customer_headers(cust["id"]))
        )
        assert resv["fulfillment_status"] == "AWAITING_DISPATCH"


class TestTransferApproveBlockedByDestinationFull:
    """A transfer cannot move REQUESTED->APPROVED when the destination on_lot_count
    is already == lot_capacity."""

    def _setup(self):
        # TO_FULL cap 1 pre-filled with one unit (on_lot_count==1==capacity).
        t = setup_transfer_requested(
            from_overrides={"name": "FROM", "state_code": "CA", "lot_capacity": 5},
            to_overrides={"name": "TO_FULL", "state_code": "NV", "lot_capacity": 1},
            reason="FLEET_REBALANCE",
            filler_at_to=True,
        )
        return t

    def test_approve_to_full_destination_returns_lot_full(self):
        """PRD §3.9: "Approval requires the destination location to be `OPEN` and to have capacity — its `on_lot_count` strictly below its `lot_capacity`, else `ERR_RETURN_LOT_FULL`."

        Design: Difficulty/cross_entity_state_dependency/transfer_approve_blocked_by_destination_lot_full
        """
        t = self._setup()
        res = api_client.approve_transfer(t["transfer"]["id"], FM)
        validate_error(res, "ERR_RETURN_LOT_FULL")

    def test_approve_to_full_destination_leaves_transfer_requested(self):
        """PRD §3.9: "Approval requires the destination location to be `OPEN` and to have capacity — its `on_lot_count` strictly below its `lot_capacity`, else `ERR_RETURN_LOT_FULL`."

        Design: Difficulty/cross_entity_state_dependency/transfer_approve_blocked_by_destination_lot_full
        """
        t = self._setup()
        api_client.approve_transfer(t["transfer"]["id"], FM)
        fetched = get_success_data(api_client.get_transfer(t["transfer"]["id"], FM))
        assert fetched["status"] == "REQUESTED"


# ─────────────────────────────────────────────────────────────────────────
# Rule 6 (boundary, capacity metric) — lot full on return
# ─────────────────────────────────────────────────────────────────────────
class TestLotCapacityFullBoundaryOnReturn:
    """Return is rejected with ERR_RETURN_LOT_FULL when the drop-off on_lot_count is
    already == lot_capacity (the >= capacity boundary)."""

    def _setup(self):
        cls = create_equipment_class(requires_coverage=False)
        pick = create_location(name="PICK", state_code="CA", lot_capacity=5)
        drop = create_location(name="DROP", state_code="NV", lot_capacity=1,
                               accepts_one_way_dropoff=True)
        # Pre-fill DROP to on_lot_count == 1 == capacity.
        create_equipment(cls["id"], drop["id"], odometer_miles=0, fuel_level_eighths=8)
        eq = create_equipment(cls["id"], pick["id"], odometer_miles=0, fuel_level_eighths=8)
        cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
        resv = create_reservation(cust, cls["id"], pick["id"], drop["id"],
                                  scheduled_pickup_at="2026-07-01T09:00:00Z",
                                  scheduled_return_at="2026-07-02T09:00:00Z")
        confirmed = confirm_reservation(resv["id"], cust)
        contract = dispatch_reservation(confirmed["id"], confirmed["version"])
        return contract, drop

    def test_return_to_full_lot_returns_lot_full(self):
        """PRD §3.6: "The drop-off location (the reservation's `dropoff_location_id`) must be `OPEN`, and its `on_lot_count` must be strictly below its `lot_capacity` or the return is rejected with `ERR_RETURN_LOT_FULL`."

        Design: Difficulty/boundary_precision_check/lot_capacity_full_boundary_on_return
        """
        contract, _ = self._setup()
        res = api_client.return_contract(
            contract["id"], return_payload(30, 8, "2026-07-02T09:00:00Z"), LA
        )
        validate_error(res, "ERR_RETURN_LOT_FULL")

    def test_return_rejected_leaves_lot_count_unchanged(self):
        """PRD §3.6: "The drop-off location (the reservation's `dropoff_location_id`) must be `OPEN`, and its `on_lot_count` must be strictly below its `lot_capacity` or the return is rejected with `ERR_RETURN_LOT_FULL`."

        Design: Difficulty/boundary_precision_check/lot_capacity_full_boundary_on_return
        """
        contract, drop = self._setup()
        api_client.return_contract(
            contract["id"], return_payload(30, 8, "2026-07-02T09:00:00Z"), LA
        )
        assert get_location(drop["id"])["on_lot_count"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Rule 8 — resource temporal-overlap across interval semantics
# ─────────────────────────────────────────────────────────────────────────
class TestBufferedWindowOverlapBlocksSecondRoundtrip:
    """With one unit at HUB, a first round-trip earmarks it; a second round-trip whose
    start falls inside the first's buffer-extended window is rejected double-booked."""

    def _setup(self):
        cls = create_equipment_class(requires_coverage=False)
        hub = create_location(name="HUB", lot_capacity=5)
        create_equipment(cls["id"], hub["id"])
        custa = create_customer(license_verified=True, loyalty_tier="STANDARD")
        custb = create_customer(license_verified=True, loyalty_tier="STANDARD")
        resva = create_reservation(custa, cls["id"], hub["id"], hub["id"],
                                   scheduled_pickup_at="2026-07-01T09:00:00Z",
                                   scheduled_return_at="2026-07-02T09:00:00Z")
        confirm_reservation(resva["id"], custa)  # earmarks the only unit
        # Second window starts 07-02T10:00 < 07-02T09:00 + 3h = 07-02T12:00 -> inside buffer.
        resvb = create_reservation(custb, cls["id"], hub["id"], hub["id"],
                                   scheduled_pickup_at="2026-07-02T10:00:00Z",
                                   scheduled_return_at="2026-07-03T10:00:00Z")
        return resvb, custb

    def test_second_roundtrip_confirm_rejected_double_booked(self):
        """PRD §3.8: "the comparison right-extends each window by the 3-hour turnaround and treats the intervals as half-open: the new reservation's window collides with an existing one when the new pickup is earlier than the existing return plus the turnaround buffer and the existing pickup is earlier than the new return plus the turnaround buffer."

        Design: Difficulty/resource_temporal_overlap/equipment_buffered_window_overlap_blocks_second_roundtrip
        """
        resvb, custb = self._setup()
        res = api_client.confirm_reservation(resvb["id"], make_customer_headers(custb["id"]))
        validate_error(res, "ERR_EQUIPMENT_DOUBLE_BOOKED")

    def test_rejected_second_roundtrip_stays_pending(self):
        """PRD §3.6: "If every stationed unit is held by a colliding confirmed reservation, the confirm is rejected with `ERR_EQUIPMENT_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/equipment_buffered_window_overlap_blocks_second_roundtrip
        """
        resvb, custb = self._setup()
        api_client.confirm_reservation(resvb["id"], make_customer_headers(custb["id"]))
        fetched = get_success_data(
            api_client.get_reservation(resvb["id"], make_customer_headers(custb["id"]))
        )
        assert fetched["booking_status"] == "PENDING"


class TestOpenTransferLifecycleOverlapBlocksSecond:
    """A unit already encumbered by a REQUESTED transfer cannot have a second opened."""

    def _setup(self):
        cls = create_equipment_class(requires_coverage=False)
        from_loc = create_location(name="FROM", state_code="CA", lot_capacity=5)
        to1 = create_location(name="TO1", state_code="NV", lot_capacity=5)
        to2 = create_location(name="TO2", state_code="AZ", lot_capacity=5)
        eq = create_equipment(cls["id"], from_loc["id"])
        get_success_data(api_client.create_transfer(
            create_transfer_payload(eq["id"], to1["id"], reason="FLEET_REBALANCE"), FM))
        return eq, to2

    def test_second_transfer_open_returns_in_progress(self):
        """PRD §3.9: "A unit may have at most one open transfer — a transfer in `REQUESTED` or `APPROVED` status counts as open — and opening a second while one is open is rejected with `ERR_TRANSFER_IN_PROGRESS".

        Design: Difficulty/resource_temporal_overlap/equipment_open_transfer_lifecycle_overlap_blocks_second
        """
        eq, to2 = self._setup()
        res = api_client.create_transfer(
            create_transfer_payload(eq["id"], to2["id"], reason="FLEET_REBALANCE"), FM
        )
        validate_error(res, "ERR_TRANSFER_IN_PROGRESS")

    def test_only_one_transfer_exists_after_rejected_second(self):
        """PRD §3.9: "A unit may have at most one open transfer — a transfer in `REQUESTED` or `APPROVED` status counts as open — and opening a second while one is open is rejected with `ERR_TRANSFER_IN_PROGRESS".

        Design: Difficulty/resource_temporal_overlap/equipment_open_transfer_lifecycle_overlap_blocks_second
        """
        eq, to2 = self._setup()
        api_client.create_transfer(
            create_transfer_payload(eq["id"], to2["id"], reason="FLEET_REBALANCE"), FM
        )
        data, meta = validate_paginated(
            api_client.list_transfers(FM, params={"equipment_id": eq["id"]})
        )
        assert meta["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Queue B — corner validation instances
# ─────────────────────────────────────────────────────────────────────────
def _class_loc_customer():
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    return cls, hub, cust


def test_reservation_create_invalid_time_range_rejected():
    """PRD §3.3: "The `scheduled_return_at` must be strictly later than `scheduled_pickup_at`; otherwise the create is rejected with `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/reservation_create_invalid_time_range_rejected
    """
    cls, hub, cust = _class_loc_customer()
    res = api_client.create_reservation(
        create_reservation_payload(cust["id"], cls["id"], hub["id"], hub["id"],
                                   scheduled_pickup_at="2026-07-02T09:00:00Z",
                                   scheduled_return_at="2026-07-01T09:00:00Z"),
        make_customer_headers(cust["id"]),
    )
    validate_error(res, "ERR_INVALID_TIME_RANGE")


def test_coverage_mismatch_selected_without_plan_rejected():
    """PRD §3.3: "a `coverage_choice` of `SELECTED` requires a non-null `coverage_plan_id` that references an active coverage plan, while a `coverage_choice` of `DECLINED` requires that no `coverage_plan_id` be provided; either inconsistency is rejected with `ERR_COVERAGE_MISMATCH`."

    Design: Corner/validations/coverage_mismatch_selected_without_plan_rejected
    """
    cls, hub, cust = _class_loc_customer()
    res = api_client.create_reservation(
        create_reservation_payload(cust["id"], cls["id"], hub["id"], hub["id"],
                                   coverage_choice="SELECTED"),
        make_customer_headers(cust["id"]),
    )
    validate_error(res, "ERR_COVERAGE_MISMATCH")


def test_one_way_dropoff_not_allowed_rejected():
    """PRD §3.3: "For a one-way reservation, the `dropoff_location_id` must differ from the `pickup_location_id` and the chosen drop-off location must have `accepts_one_way_dropoff` set to true; a violation is rejected with `ERR_ONE_WAY_DROPOFF_NOT_ALLOWED`."

    Design: Corner/validations/one_way_dropoff_not_allowed_rejected
    """
    cls = create_equipment_class(requires_coverage=False)
    pick = create_location(name="PICK", state_code="CA", lot_capacity=5)
    drop = create_location(name="DROP_NO", state_code="NV", lot_capacity=5,
                           accepts_one_way_dropoff=False)
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    res = api_client.create_reservation(
        create_reservation_payload(cust["id"], cls["id"], pick["id"], drop["id"]),
        make_customer_headers(cust["id"]),
    )
    validate_error(res, "ERR_ONE_WAY_DROPOFF_NOT_ALLOWED")


def test_coverage_required_class_confirm_without_coverage_rejected():
    """PRD §3.6: "if the equipment class has `requires_coverage` set to true, the reservation's `coverage_choice` must be `SELECTED`; otherwise the confirm is rejected with `ERR_COVERAGE_REQUIRED`."

    Design: Corner/validations/coverage_required_class_confirm_without_coverage_rejected
    """
    cls = create_equipment_class(requires_coverage=True)
    hub = create_location(name="HUB", lot_capacity=5)
    create_equipment(cls["id"], hub["id"])
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    resv = create_reservation(cust, cls["id"], hub["id"], hub["id"],
                              coverage_choice="DECLINED")
    res = api_client.confirm_reservation(resv["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_COVERAGE_REQUIRED")


def test_odometer_regression_on_return_rejected():
    """PRD §3.6: "The closing `return_odometer_miles` must be at least the contract's `pickup_odometer_miles`; a lower reading is rejected with `ERR_ODOMETER_REGRESSION`."

    Design: Corner/validations/odometer_regression_on_return_rejected
    """
    s = setup_round_trip_confirmed(
        equipment_overrides={"odometer_miles": 1000, "fuel_level_eighths": 8},
        class_overrides={"requires_coverage": False},
        customer_overrides={"license_verified": True, "loyalty_tier": "STANDARD"},
    )
    contract = dispatch_reservation(s["reservation"]["id"], s["reservation"]["version"])
    res = api_client.return_contract(
        contract["id"], return_payload(900, 8, "2026-07-02T09:00:00Z"), LA
    )
    validate_error(res, "ERR_ODOMETER_REGRESSION")


def test_supply_quantity_exceeds_stock_rejected():
    """PRD §3.4: "The requested `quantity` must not exceed the catalog item's current `stock_qty`; if it does, the create is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/supply_quantity_exceeds_stock_rejected
    """
    cls, hub, cust = _class_loc_customer()
    box = create_supply(sku="SMALLBOX", unit_price_cents=200, stock_qty=2)
    resv = create_reservation(cust, cls["id"], hub["id"], hub["id"])
    res = api_client.add_supply(
        resv["id"], create_supply_line_payload(box["id"], 5), make_customer_headers(cust["id"])
    )
    validate_error(res, "ERR_INSUFFICIENT_STOCK")
    assert get_success_data(api_client.get_supply(box["id"], FM))["stock_qty"] == 2


def test_add_supply_after_confirm_returns_reservation_locked():
    """PRD §3.4: "While a reservation is still `PENDING`, the holder (a `Customer`, or a `LocationAgent` acting on their behalf) may attach moving supplies and equipment add-ons to it; once the reservation leaves `PENDING`, any attempt to add or remove either is rejected with `ERR_RESERVATION_LOCKED`."

    Design: Corner/validations/add_supply_after_confirm_returns_reservation_locked
    """
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    create_equipment(cls["id"], hub["id"])
    box = create_supply(sku="BOX", unit_price_cents=200, stock_qty=10)
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    resv = create_reservation(cust, cls["id"], hub["id"], hub["id"])
    confirm_reservation(resv["id"], cust)
    res = api_client.add_supply(
        resv["id"], create_supply_line_payload(box["id"], 1), make_customer_headers(cust["id"])
    )
    validate_error(res, "ERR_RESERVATION_LOCKED")


def test_dispatch_no_equipment_available_returns_error():
    """PRD §3.6: "and the dispatch selector must yield a non-empty candidate set (else `ERR_NO_EQUIPMENT_AVAILABLE`)."

    Design: Corner/validations/dispatch_no_equipment_available_returns_error
    """
    cls = create_equipment_class(requires_coverage=False)
    pick = create_location(name="PICK", state_code="CA", lot_capacity=5)  # no units
    drop = create_location(name="DROP", state_code="NV", lot_capacity=5,
                           accepts_one_way_dropoff=True)
    cust = create_customer(license_verified=True, loyalty_tier="STANDARD")
    resv = create_reservation(cust, cls["id"], pick["id"], drop["id"])
    confirmed = confirm_reservation(resv["id"], cust)  # one-way confirm needs no unit
    res = api_client.dispatch_reservation(
        confirmed["id"], dispatch_payload(confirmed["version"]), LA
    )
    validate_error(res, "ERR_NO_EQUIPMENT_AVAILABLE")


def test_transfer_create_to_equals_from_returns_invalid_transfer():
    """PRD §3.9: "The create is validated: the `from_location_id` must equal the unit's current location, the `to_location_id` must differ from the origin, and the destination location must be `OPEN`; any violation is rejected with `ERR_INVALID_TRANSFER`."

    Design: Corner/validations/transfer_create_to_equals_from_returns_invalid_transfer
    """
    cls = create_equipment_class(requires_coverage=False)
    hub = create_location(name="HUB", lot_capacity=5)
    eq = create_equipment(cls["id"], hub["id"])
    res = api_client.create_transfer(
        create_transfer_payload(eq["id"], hub["id"], reason="FLEET_REBALANCE"), FM
    )
    validate_error(res, "ERR_INVALID_TRANSFER")
