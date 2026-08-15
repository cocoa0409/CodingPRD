"""Inbound receipt scheduling: schema validation, initial state, dock doors."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    arrive_receipt,
    create_customer,
    create_customer_with_card,
    create_rate_card_for,
    create_receipt_payload,
    create_zone,
    get_lot,
    get_receipt,
    make_customer_admin_headers,
    receive_stock,
    schedule_receipt,
    validate_error,
    validate_success,
)

BILLING = TEST_USERS["billing_admin_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]


class TestReceiptSchemaValidation:
    def test_missing_zone_id_rejected(self, api):
        """PRD §3.2: "A `CustomerAdmin` schedules an inbound receipt for their own
        customer by providing the `customer_id`, the pre-assigned `zone_id`, the
        `product_code`, the manufacturer's `lot_code`, the `production_date` as an
        ISO calendar date — this date is the primary key for FIFO release — the
        goods' `temp_class`, a declared `expected_pallets` of at least one, and
        the scheduled arrival window from `window_start` to `window_end`."
        PRD §2.9: "Request-body schema, applied to all write endpoints: required
        fields are present, types are valid, enum values are in range, quantities
        that must be positive are positive, and any `window_end` is strictly later
        than its `window_start`; otherwise `ERR_VALIDATION`."

        Design: Corner/entities/receipt_missing_required_field_returns_validation
        """
        customer = create_customer("Req Co")
        payload = create_receipt_payload(customer["id"], "irrelevant-zone")
        del payload["zone_id"]
        resp = api.create_inbound_receipt(
            payload, make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_window_end_before_start_rejected(self, api):
        """PRD §2.9: "Request-body schema, applied to all write endpoints:
        required fields are present, types are valid, enum values are in range,
        quantities that must be positive are positive, and any `window_end` is
        strictly later than its `window_start`; otherwise `ERR_VALIDATION`."

        Design: Corner/validations/window_end_before_start_rejected
        """
        customer = create_customer("Winv Co")
        zone = create_zone("FZ-WV", capacity_pallets=5, dock_doors=1)
        resp = api.create_inbound_receipt(
            create_receipt_payload(customer["id"], zone["id"], lot_code="WV",
                                   window_start="2026-08-02T10:00:00Z",
                                   window_end="2026-08-02T08:00:00Z"),
            make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestReceiptInitialState:
    def test_receipt_born_scheduled_with_null_completion_fields(self, api):
        """PRD §3.2: "The receipt is born `SCHEDULED`; its `lot_id` stays null
        until completion, as does `actual_pallets`."

        Design: Corner/state_machines/receipt_initial_state_scheduled
        """
        customer = create_customer("Init Co")
        zone = create_zone("FZ-IN", capacity_pallets=5, dock_doors=1)
        receipt = validate_success(
            api.create_inbound_receipt(
                create_receipt_payload(customer["id"], zone["id"], lot_code="IN",
                                       expected_pallets=2),
                make_customer_admin_headers(customer["id"])),
            expected_status=201)
        assert receipt["status"] == "SCHEDULED"
        assert receipt["actual_pallets"] is None, "actual_pallets null until COMPLETED"
        assert receipt["lot_id"] is None, "lot_id null until COMPLETED"


class TestTempClassMismatch:
    def test_chilled_receipt_into_frozen_zone_rejected(self, api):
        """PRD §3.2: "The receipt's `temp_class` must equal the assigned zone's
        `temp_class`, else `ERR_TEMP_CLASS_MISMATCH`."

        Design: Corner/validations/temp_class_mismatch_rejected_at_receipt_create
        """
        customer = create_customer("Temp Co")
        zone = create_zone("FZ-TC", temp_class="FROZEN", capacity_pallets=5,
                           dock_doors=1)
        resp = api.create_inbound_receipt(
            create_receipt_payload(customer["id"], zone["id"], product_code="MILK",
                                   lot_code="TC", temp_class="CHILLED"),
            make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_TEMP_CLASS_MISMATCH, expected_status=409)
        data = api.list_inbound_receipts(
            make_customer_admin_headers(customer["id"]),
            params={"customer_id": customer["id"]}).json()["data"]
        assert data == [], "no receipt persisted on rejection"


class TestNoActiveRateCard:
    def test_completion_without_rate_card_rejected(self, api):
        """PRD §2.10: "Four charging events require the customer to have an ACTIVE
        rate card at the moment of the event: receipt completion, order
        submission, blast-freeze booking completion, and claim approval. Any of
        them attempted with no ACTIVE card in force is rejected with
        `ERR_NO_ACTIVE_RATE_CARD`."

        Design: Corner/validations/charging_without_active_rate_card_rejected
        """
        # Customer WITHOUT any rate card; receipt scheduled and arrived.
        customer = create_customer("Nocard Co")
        zone = create_zone("FZ-NC", capacity_pallets=5, dock_doors=2)
        receipt = schedule_receipt(customer["id"], zone["id"], lot_code="NC")
        arrive_receipt(receipt["id"])
        resp = api.complete_inbound_receipt(receipt["id"], {"actual_pallets": 1},
                                            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE_CARD,
                       expected_status=409)
        assert get_receipt(receipt["id"])["status"] == "ARRIVED", (
            "rejected completion leaves the receipt ARRIVED")

        # Installing a card unblocks the same completion.
        create_rate_card_for(customer)
        completed = validate_success(
            api.complete_inbound_receipt(receipt["id"], {"actual_pallets": 1},
                                         OPERATOR))
        assert completed["status"] == "COMPLETED"


class TestLotProductionDateMismatch:
    def test_conflicting_production_date_rejected_at_completion(self, api):
        """PRD §3.2: "Completion then performs a lot upsert keyed on the triple of
        `customer_id`, `product_code`, and `lot_code`: if no such **InventoryLot**
        exists it is created, and if one does exist its `production_date` — set by
        the first receipt ever merged into it — must equal this receipt's
        `production_date`, else `ERR_LOT_PRODUCTION_DATE_MISMATCH`."

        Design: Corner/validations/lot_production_date_mismatch_rejected
        """
        customer, _card = create_customer_with_card("Lot Co")
        zone = create_zone("FZ-LM", capacity_pallets=10, dock_doors=2)
        first = receive_stock(customer["id"], zone["id"], 1, lot_code="PD",
                              production_date="2026-01-15")
        second = schedule_receipt(customer["id"], zone["id"], lot_code="PD",
                                  production_date="2026-02-20",
                                  window_start="2026-08-03T08:00:00Z",
                                  window_end="2026-08-03T10:00:00Z")
        arrive_receipt(second["id"])
        resp = api.complete_inbound_receipt(second["id"], {"actual_pallets": 1},
                                            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_LOT_PRODUCTION_DATE_MISMATCH,
                       expected_status=409)
        assert get_receipt(second["id"])["status"] == "ARRIVED", (
            "rejected completion leaves the receipt ARRIVED")
        assert get_lot(first["lot_id"])["on_hand_pallets"] == 1, (
            "no pallet merged into the lot on rejection")


class TestDockDoorAggregateCapacity:
    def _setup_dock_zone(self):
        customer, _card = create_customer_with_card("Dock Co")
        zone = create_zone("FZ-21", capacity_pallets=50, dock_doors=1)
        receipt1 = schedule_receipt(customer["id"], zone["id"], lot_code="DK1",
                                    expected_pallets=2,
                                    window_start="2026-08-05T09:00:00Z",
                                    window_end="2026-08-05T11:00:00Z")
        return customer, zone, receipt1

    def test_adjacent_window_is_not_overlap(self, api):
        """PRD §3.2: "Windows that merely touch — one window's end equal to
        another's start — do not overlap and are always allowed."

        Design: Difficulty/resource_temporal_overlap/dock_door_aggregate_capacity_semantics
        """
        customer, zone, _receipt1 = self._setup_dock_zone()
        # 11:00 start == receipt1's 11:00 end: mere adjacency, always allowed.
        receipt2 = validate_success(
            api.create_inbound_receipt(
                create_receipt_payload(customer["id"], zone["id"], lot_code="DK2",
                                       expected_pallets=2,
                                       window_start="2026-08-05T11:00:00Z",
                                       window_end="2026-08-05T13:00:00Z"),
                make_customer_admin_headers(customer["id"])),
            expected_status=201)
        assert receipt2["status"] == "SCHEDULED"

    def test_overlapping_window_exceeds_dock_doors(self, api):
        """PRD §3.2: "And the dock doors must absorb the window: counting the
        zone's other receipts standing at `SCHEDULED` or `ARRIVED` whose windows
        strictly overlap the new one, the count must remain below the zone's
        `dock_doors`, else `ERR_DOCK_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/dock_door_aggregate_capacity_semantics
        """
        customer, zone, _receipt1 = self._setup_dock_zone()
        # 10:30-12:00 strictly overlaps receipt1's 09:00-11:00; dock_doors == 1.
        resp = api.create_inbound_receipt(
            create_receipt_payload(customer["id"], zone["id"], lot_code="DK3",
                                   expected_pallets=2,
                                   window_start="2026-08-05T10:30:00Z",
                                   window_end="2026-08-05T12:00:00Z"),
            make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED,
                       expected_status=409)
