"""Zone capacity accounting, storage posture, and putaway/arrival gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_order,
    assert_zone,
    complete_receipt,
    create_customer_with_card,
    create_order,
    create_submitted_order,
    create_zone,
    get_zone,
    receive_stock,
    schedule_receipt,
    ship_order,
    submit_order,
    arrive_receipt,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]


class TestZoneValidation:
    def test_invalid_temp_class_enum_rejected(self, api):
        """PRD §3.2: "Each **TemperatureZone** is created with a `zone_code` that
        must be unique across all zones, a `temp_class` of `FROZEN` or `CHILLED`,
        a `capacity_pallets` count of at least one, and a `dock_doors` count of at
        least one bounding how many arrivals may overlap at the zone's doors."
        PRD §2.9: "Request-body schema, applied to all write endpoints: required
        fields are present, types are valid, enum values are in range, quantities
        that must be positive are positive, and any `window_end` is strictly later
        than its `window_start`; otherwise `ERR_VALIDATION`."

        Design: Corner/entities/zone_invalid_enum_temp_class_rejected
        """
        resp = api.create_zone(
            {"zone_code": "ZX-1", "temp_class": "ARCTIC", "capacity_pallets": 5,
             "dock_doors": 1},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_fresh_zone_computed_fields(self, api):
        """PRD §3.2: "A freshly created zone starts empty: `in_use_pallets` and
        `reserved_pallets` at zero, `free_pallets` equal to capacity, and `posture`
        `OPEN`."
        PRD §2.8: "`free_pallets` is what remains: the zone's `capacity_pallets`
        minus `in_use_pallets` minus `reserved_pallets`."

        Design: Corner/entities/zone_computed_fields_system_derived_on_create
        """
        zone = validate_success(
            api.create_zone(
                {"zone_code": "ZC-1", "temp_class": "FROZEN", "capacity_pallets": 7,
                 "dock_doors": 1},
                OPERATOR),
            expected_status=201)
        assert_zone(zone)
        assert zone["in_use_pallets"] == 0
        assert zone["reserved_pallets"] == 0
        assert zone["free_pallets"] == 7, "free == capacity on a fresh zone"
        assert zone["posture"] == "OPEN"


class TestZonePostureThreshold:
    def test_tight_threshold_boundary(self, api):
        """PRD §2.8: "The tight threshold for a zone is the greater of one pallet
        position and ten percent of the zone's capacity rounded down to a whole
        number. When `free_pallets` reaches zero the posture is `FULL`. When
        `free_pallets` is greater than zero but no more than the tight threshold,
        the posture is `TIGHT`. Otherwise the posture is `OPEN`."

        Design: Corner/calculations/zone_posture_tight_threshold_boundary
        """
        customer, _card = create_customer_with_card("Tight Co")
        zone9 = create_zone("FZ-T9", capacity_pallets=10, dock_doors=2)
        zone8 = create_zone("FZ-T8", capacity_pallets=10, dock_doors=2)
        # Capacity 10 -> tight threshold max(1, floor(10*0.10)) == 1.
        receive_stock(customer["id"], zone9["id"], 9, lot_code="T9")
        receive_stock(customer["id"], zone8["id"], 8, lot_code="T8")

        z9 = get_zone(zone9["id"])
        assert z9["free_pallets"] == 1 and z9["posture"] == "TIGHT", (
            f"free 1 <= threshold 1 must be TIGHT, got {z9['posture']}")
        z8 = get_zone(zone8["id"])
        assert z8["free_pallets"] == 2 and z8["posture"] == "OPEN", (
            f"free 2 > threshold 1 must be OPEN, got {z8['posture']}")


class TestZoneExactFillThenOverflow:
    def _setup_full_zone(self):
        customer, _card = create_customer_with_card("Cap Co")
        zone = create_zone("FZ-15", capacity_pallets=3, dock_doors=2)
        receipt1 = schedule_receipt(customer["id"], zone["id"], lot_code="C1",
                                    expected_pallets=3,
                                    window_start="2026-08-02T08:00:00Z",
                                    window_end="2026-08-02T10:00:00Z")
        receipt2 = schedule_receipt(customer["id"], zone["id"], lot_code="C2",
                                    production_date="2026-01-16",
                                    expected_pallets=1,
                                    window_start="2026-08-02T11:00:00Z",
                                    window_end="2026-08-02T13:00:00Z")
        arrive_receipt(receipt1["id"])
        complete_receipt(receipt1["id"], 3)
        return customer, zone, receipt2

    def test_exact_fill_succeeds_and_zone_turns_full(self, api):
        """PRD §3.2: "the counted `actual_pallets` must fit within the zone's
        capacity minus its `in_use_pallets` minus its now-reduced
        `reserved_pallets`, else `ERR_ZONE_CAPACITY_EXCEEDED`."
        PRD §2.8: "When `free_pallets` reaches zero the posture is `FULL`."

        Design: Difficulty/boundary_precision_check/zone_capacity_exact_fill_then_overflow
        """
        _customer, zone, _receipt2 = self._setup_full_zone()
        z = get_zone(zone["id"])
        # Exact fill (actual == capacity) is legal and leaves free_pallets == 0.
        assert z["in_use_pallets"] == 3 and z["free_pallets"] == 0
        assert z["posture"] == "FULL", f"free 0 must be FULL, got {z['posture']}"

    def test_arrival_rejected_once_zone_full(self, api):
        """PRD §3.2: "The zone's posture must not be `FULL` — that is,
        `free_pallets` must not have reached zero — or the arrival is turned away
        with `ERR_ZONE_FULL`."

        Design: Difficulty/boundary_precision_check/zone_capacity_exact_fill_then_overflow
        """
        _customer, zone, receipt2 = self._setup_full_zone()
        resp = api.arrive_inbound_receipt(receipt2["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ZONE_FULL, expected_status=409)
        receipt2_after = validate_success(
            api.get_inbound_receipt(receipt2["id"], OPERATOR))
        assert receipt2_after["status"] == "SCHEDULED", (
            "rejected arrival leaves the receipt SCHEDULED")


class TestReceiptArrivalGatedByPosture:
    def _setup_cap1_zone(self):
        customer, _card = create_customer_with_card("Posture Co")
        zone = create_zone("FZ-18", capacity_pallets=1, dock_doors=2)
        receive_stock(customer["id"], zone["id"], 1, lot_code="P1")
        receipt2 = schedule_receipt(customer["id"], zone["id"], lot_code="P2",
                                    production_date="2026-01-16",
                                    expected_pallets=1,
                                    window_start="2026-08-02T11:00:00Z",
                                    window_end="2026-08-02T13:00:00Z")
        order = create_submitted_order(customer["id"], 1)
        allocate_order(order["id"])
        return customer, zone, receipt2, order

    def test_arrival_blocked_while_full(self, api):
        """PRD §3.2: "The zone's posture must not be `FULL` — that is,
        `free_pallets` must not have reached zero — or the arrival is turned away
        with `ERR_ZONE_FULL`."

        Design: Difficulty/cross_entity_state_dependency/receipt_arrival_gated_by_zone_posture
        """
        _customer, _zone, receipt2, _order = self._setup_cap1_zone()
        resp = api.arrive_inbound_receipt(receipt2["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ZONE_FULL, expected_status=409)
        assert validate_success(
            api.get_inbound_receipt(receipt2["id"], OPERATOR))["status"] == "SCHEDULED"

    def test_arrival_allowed_after_shipment_frees_slot(self, api):
        """PRD §3.5: "the zone's `in_use_pallets` falls by the shipped count".
        PRD §3.2: "The zone's posture must not be `FULL` — that is,
        `free_pallets` must not have reached zero — or the arrival is turned away
        with `ERR_ZONE_FULL`."

        Design: Difficulty/cross_entity_state_dependency/receipt_arrival_gated_by_zone_posture
        """
        _customer, zone, receipt2, order = self._setup_cap1_zone()
        blocked = api.arrive_inbound_receipt(receipt2["id"], OPERATOR)
        validate_error(blocked, ApiErrorId.ERR_ZONE_FULL)
        ship_order(order["id"])
        assert get_zone(zone["id"])["in_use_pallets"] == 0, (
            "shipping frees the physical slot")
        arrived = validate_success(
            api.arrive_inbound_receipt(receipt2["id"], OPERATOR))
        assert arrived["status"] == "ARRIVED", (
            "posture TIGHT (not FULL) no longer gates arrival")


class TestOverReceiptPutaway:
    def test_zone_capacity_exceeded_on_over_receipt_putaway(self, api):
        """PRD §3.2: "The reservation comes off first: the receipt's
        `expected_pallets` is subtracted from the zone's `reserved_pallets`, and
        only then is the capacity check applied — the counted `actual_pallets`
        must fit within the zone's capacity minus its `in_use_pallets` minus its
        now-reduced `reserved_pallets`, else `ERR_ZONE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/zone_capacity_exceeded_on_over_receipt_putaway
        """
        customer, _card = create_customer_with_card("Over Co")
        zone = create_zone("FZ-OV", capacity_pallets=4, dock_doors=2)
        receive_stock(customer["id"], zone["id"], 3, lot_code="O1",
                      window_start="2026-08-02T08:00:00Z",
                      window_end="2026-08-02T10:00:00Z")
        receipt_b = schedule_receipt(customer["id"], zone["id"], lot_code="O2",
                                     expected_pallets=1,
                                     window_start="2026-08-02T11:00:00Z",
                                     window_end="2026-08-02T13:00:00Z")
        arrive_receipt(receipt_b["id"])
        # After reservation release: capacity 4 - in_use 3 - reserved 0 == 1 < 2.
        resp = api.complete_inbound_receipt(receipt_b["id"], {"actual_pallets": 2},
                                            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED,
                       expected_status=409)
        receipt_b_after = validate_success(
            api.get_inbound_receipt(receipt_b["id"], OPERATOR))
        assert receipt_b_after["status"] == "ARRIVED", (
            "rejected completion leaves the receipt ARRIVED")
        z = get_zone(zone["id"])
        assert z["in_use_pallets"] == 3, "failed putaway creates no pallets"


class TestStateBeatsCapacity:
    def _setup_completed_full_zone(self):
        customer, _card = create_customer_with_card("State Co")
        zone = create_zone("FZ-13", capacity_pallets=2, dock_doors=2)
        receipt = receive_stock(customer["id"], zone["id"], 2, lot_code="T2")
        return customer, zone, receipt

    def test_second_complete_reports_invalid_state(self, api):
        """PRD §2.9: "A request that would fail at several tiers is rejected with
        the error belonging to the earliest applicable tier, so that a failure
        deeper in the cascade never masks one nearer the surface."
        PRD §2.9: "State validity, applied to all action endpoints: the target
        resource must stand in a valid from-state for the requested transition,
        including terminal-state lockdown, and any OCC expectation on the request
        must match; an invalid from-state is rejected `ERR_INVALID_STATE`, while
        a stale OCC expectation is rejected `ERR_STALE_VERSION`."
        PRD §3.2: "A `WarehouseOperator` completes an `ARRIVED` receipt by
        reporting the counted `actual_pallets`"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_constraint_on_receipt_complete
        """
        _customer, _zone, receipt = self._setup_completed_full_zone()
        # The zone is now FULL (free 0), so the p9 capacity check would also
        # fail — but the p6 state check (receipt already COMPLETED) is earlier.
        resp = api.complete_inbound_receipt(receipt["id"], {"actual_pallets": 1},
                                            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_second_complete_mutates_nothing(self, api):
        """PRD §3.2: "With the lot resolved, the system creates exactly
        `actual_pallets` Pallets" — only on a successful completion.
        PRD §2.9: "State validity, applied to all action endpoints: the target
        resource must stand in a valid from-state for the requested transition,
        including terminal-state lockdown, and any OCC expectation on the request
        must match; an invalid from-state is rejected `ERR_INVALID_STATE`, while
        a stale OCC expectation is rejected `ERR_STALE_VERSION`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_constraint_on_receipt_complete
        """
        _customer, zone, receipt = self._setup_completed_full_zone()
        resp = api.complete_inbound_receipt(receipt["id"], {"actual_pallets": 1},
                                            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        receipt_after = validate_success(
            api.get_inbound_receipt(receipt["id"], OPERATOR))
        assert receipt_after["status"] == "COMPLETED"
        assert receipt_after["actual_pallets"] == 2, "original count unchanged"
        assert get_zone(zone["id"])["in_use_pallets"] == 2, "no new pallets created"
