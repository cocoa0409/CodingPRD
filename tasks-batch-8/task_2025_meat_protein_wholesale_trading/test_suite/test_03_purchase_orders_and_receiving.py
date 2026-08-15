"""Purchase orders: initial states, booking and receiving gates, supplier
suspension, warehouse aggregate capacity, and validation ordering."""
from test_helpers import (
    NON_EXISTENT_UUID,
    WEEK_1,
    ApiErrorId,
    add_sheet_line,
    api_client,
    book_po,
    create_allocation_payload,
    create_customer,
    create_forward_contract_payload,
    create_product,
    create_purchase_order_payload,
    create_sheet,
    create_supplier,
    create_warehouse,
    get_lot,
    get_po,
    get_po_lot,
    get_warehouse,
    make_customer_rep_headers,
    publish_sheet,
    receive_po,
    receive_po_payload,
    set_clock,
    validate_error,
    validate_success,
)


class TestInitialStatesOnCreate:
    def test_initial_states_on_create(self, trader_headers,
                                      desk_admin_headers):
        """PRD §3.3: "A successfully booked order starts in `BOOKED` status
        with `received_weight_lbs` null and `actual_cutout_value_cents` null"
        PRD §3.2: "The sheet is born in `DRAFT` status with `published_at`
        null."
        PRD §3.6: "A new contract is `OPEN`, with `delivered_lbs`,
        `earmarked_lbs`, and `amendment_round` all starting at zero."
        PRD §3.6: "A requested allocation starts in `REQUESTED` status with
        `allocated_lbs` at zero and `unit_price_cents` null."

        Design: Corner/state_machines/initial_states_on_create
        """
        product = create_product(product_code="RIBEYE-IS", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-IS")
        customer = create_customer(customer_code="CUST-IS",
                                   allocation_tier="TIER_2")

        sheet_resp = api_client.create_price_sheet({"week_start_date": WEEK_1},
                                                   trader_headers)
        sheet = validate_success(sheet_resp, expected_status=201)
        assert sheet["status"] == "DRAFT", \
            f"a sheet is born DRAFT, got {sheet['status']}"
        assert sheet["published_at"] is None
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])

        po_resp = api_client.create_purchase_order(
            create_purchase_order_payload(supplier["id"], product["id"],
                                          ordered_weight_lbs=100),
            trader_headers,
        )
        po = validate_success(po_resp, expected_status=201)
        assert po["status"] == "BOOKED", f"got {po['status']}"
        assert po["received_weight_lbs"] is None
        assert po["actual_cutout_value_cents"] is None

        fc_resp = api_client.create_forward_contract(
            create_forward_contract_payload(customer["id"], product["id"],
                                            committed_lbs=100),
            trader_headers,
        )
        fc = validate_success(fc_resp, expected_status=201)
        assert fc["status"] == "OPEN", f"got {fc['status']}"
        assert fc["delivered_lbs"] == 0
        assert fc["earmarked_lbs"] == 0
        assert fc["amendment_round"] == 0

        alloc_resp = api_client.create_allocation(
            create_allocation_payload(customer["id"], line["id"], 50),
            make_customer_rep_headers(customer["id"]),
        )
        alloc = validate_success(alloc_resp, expected_status=201)
        assert alloc["status"] == "REQUESTED", f"got {alloc['status']}"
        assert alloc["allocated_lbs"] == 0
        assert alloc["unit_price_cents"] is None


class TestPurchaseOrderCancel:
    def test_cancel_po_twice_returns_po_not_booked(self, trader_headers):
        """PRD §3.3: "A `Trader` may cancel an order only while it is `BOOKED`
        — otherwise `ERR_PO_NOT_BOOKED`."

        Design: Corner/state_machines/cancel_po_twice_returns_po_not_booked
        """
        product = create_product(product_code="RIBEYE-C2", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-C2")
        po = book_po(supplier["id"], product["id"], ordered_weight_lbs=100)

        first = api_client.cancel_purchase_order(po["id"], trader_headers)
        assert validate_success(first)["status"] == "CANCELLED"

        second = api_client.cancel_purchase_order(po["id"], trader_headers)
        validate_error(second, ApiErrorId.ERR_PO_NOT_BOOKED)
        assert get_po(po["id"])["status"] == "CANCELLED", \
            "a rejected second cancel must not mutate the order"


class TestReceiving:
    def test_receive_side_effect_creates_lot_and_occupancy(
            self, warehouse_operator_headers):
        """PRD §3.3: "On success the purchase order's `received_weight_lbs` is
        recorded, its `status` moves from `BOOKED` to `RECEIVED`, and its
        `version` increments; exactly one inventory lot is created in
        `IN_INSPECTION` status, stamped with the payload's `lot_code` and
        `production_date`, tied to the order through `po_id`, holding both
        `received_weight_lbs` and `current_weight_lbs` equal to the payload
        weight; and the warehouse's occupancy is recomputed."
        PRD §2.11: "A warehouse's `occupied_lbs` is a live aggregate: the sum
        of `current_weight_lbs` over all lots stored at that warehouse whose
        status is `IN_INSPECTION`, `AVAILABLE`, or `QUARANTINED`."

        Design: Corner/state_machines/receive_side_effect_creates_lot_and_occupancy
        """
        product = create_product(product_code="RIBEYE-SE", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-SE")
        warehouse = create_warehouse(name="WH-SE")
        set_clock("2026-08-03T00:00:00Z")
        po = book_po(supplier["id"], product["id"], ordered_weight_lbs=800)

        resp = api_client.receive_purchase_order(
            po["id"],
            receive_po_payload(warehouse["id"], 800, lot_code="LOT-SE"),
            warehouse_operator_headers,
        )
        po_after = validate_success(resp)
        assert po_after["status"] == "RECEIVED"
        assert po_after["received_weight_lbs"] == 800

        lot = get_po_lot(po["id"])
        assert lot["status"] == "IN_INSPECTION"
        assert lot["lot_code"] == "LOT-SE"
        assert lot["po_id"] == po["id"]
        assert lot["received_weight_lbs"] == 800
        assert lot["current_weight_lbs"] == 800

        assert get_warehouse(warehouse["id"])["occupied_lbs"] == 800

    def test_lots_reverse_reachable_from_po(self, desk_admin_headers):
        """PRD §2.3: "Inventory lots filter by `warehouse_id`, `product_id`,
        `status`, `po_id`, `parent_lot_id`, and `fabrication_batch_id`."
        PRD §3.4: "Lots born at receiving are tied to their purchase order
        through `po_id`"

        Design: Corner/entities/lots_reverse_reachable_from_po
        """
        product = create_product(product_code="RIBEYE-RR", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-RR")
        warehouse = create_warehouse()
        set_clock("2026-08-03T00:00:00Z")
        po = book_po(supplier["id"], product["id"], ordered_weight_lbs=800)
        receive_po(po["id"], warehouse["id"], received_weight_lbs=800,
                   lot_code="LOT-RR")

        resp = api_client.list_inventory_lots(desk_admin_headers,
                                              params={"po_id": po["id"]})
        lots = validate_success(resp)
        assert isinstance(lots, list) and len(lots) == 1, \
            f"exactly one lot must be reachable via po_id, got {len(lots)}"
        lot = lots[0]
        assert lot["po_id"] == po["id"]
        assert lot["status"] == "IN_INSPECTION"
        assert lot["current_weight_lbs"] == 800

    def test_production_date_in_future_returns_422(
            self, warehouse_operator_headers):
        """PRD §3.3: "the payload's `production_date` may not lie in the future
        of the logical clock, and the lot's age at receiving — logical date
        minus `production_date` — must be less than or equal to the product's
        `shelf_life_days`; either failure is `ERR_PRODUCTION_DATE_INVALID`
        (HTTP 422)."

        Design: Corner/validations/production_date_in_future_returns_422
        """
        product = create_product(product_code="RIBEYE-PD", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-PD")
        warehouse = create_warehouse()
        po = book_po(supplier["id"], product["id"], ordered_weight_lbs=100)

        resp = api_client.receive_purchase_order(
            po["id"],
            receive_po_payload(warehouse["id"], 100, lot_code="LOT-PD",
                               production_date="2026-08-20"),
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_DATE_INVALID)
        assert get_po(po["id"])["status"] == "BOOKED", \
            "a rejected receive must leave the PO BOOKED"
        lots = validate_success(api_client.list_inventory_lots(
            warehouse_operator_headers, params={"po_id": po["id"]}))
        assert lots == [], "a rejected receive must not create a lot"

    def test_body_fk_reference_not_found_returns_422(self, trader_headers):
        """PRD §2.8: "Every body-referenced identifier — `supplier_id`,
        `product_id`, `warehouse_id`, `customer_id`, `price_sheet_line_id`,
        `forward_contract_id`, `allocation_id`, `shipment_id`, `lot_id`,
        `input_lot_id`, and each element of `lot_ids` — must resolve to an
        existing resource; otherwise `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

        Design: Corner/validations/body_fk_reference_not_found_returns_422
        """
        product = create_product(product_code="RIBEYE-RF", max_fat_pct=12.0)
        resp = api_client.create_purchase_order(
            create_purchase_order_payload(NON_EXISTENT_UUID, product["id"],
                                          ordered_weight_lbs=100),
            trader_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


class TestSupplierSuspension:
    def test_supplier_suspend_cascades_to_booked_pos(self, desk_admin_headers,
                                                     trader_headers):
        """PRD §3.1: "Suspension is forceful: every purchase order of that
        supplier still in `BOOKED` status is cancelled automatically with
        `cancel_reason` set to `SUPPLIER_SUSPENDED`, and each such cancelled
        order is removed from the inbound component of the net exposure
        calculation."
        PRD §3.1: "Reinstatement moves the supplier from `SUSPENDED` back to
        `ACTIVE` — attempting it on a supplier that is not `SUSPENDED`
        likewise fails with `ERR_INVALID_STATE` — clears `suspension_reason`
        to null, and pointedly does not reinstate the previously cancelled
        purchase orders."

        Design: Corner/state_machines/supplier_suspend_cascades_to_booked_pos
        """
        product = create_product(product_code="CARC-SC", kind="CARCASS",
                                 max_fat_pct=None, shelf_life_days=30)
        supplier = create_supplier(establishment_number="EST-SC")
        po = book_po(supplier["id"], product["id"], ordered_weight_lbs=500,
                     contract_price_per_cwt_cents=25_000,
                     required_delivery_date="2026-08-12")

        resp = api_client.set_supplier_status(
            supplier["id"], {"status": "SUSPENDED", "reason": "USDA audit"},
            desk_admin_headers,
        )
        validate_success(resp)
        po_after = get_po(po["id"])
        assert po_after["status"] == "CANCELLED"
        assert po_after["cancel_reason"] == "SUPPLIER_SUSPENDED"

        reinstate = api_client.set_supplier_status(
            supplier["id"], {"status": "ACTIVE"}, desk_admin_headers)
        assert validate_success(reinstate)["status"] == "ACTIVE"
        assert get_po(po["id"])["status"] == "CANCELLED", \
            "reinstatement must not resurrect cancelled purchase orders"

    def test_po_create_blocked_when_supplier_suspended(self, desk_admin_headers,
                                                       trader_headers):
        """PRD §3.3: "The supplier must be `ACTIVE`: booking against a
        `SUSPENDED` supplier is rejected with `ERR_SUPPLIER_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/po_create_blocked_when_supplier_suspended
        """
        product = create_product(product_code="CARC-D", kind="CARCASS",
                                 max_fat_pct=None, shelf_life_days=30)
        supplier = create_supplier(establishment_number="EST-11")
        api_client.set_supplier_status(
            supplier["id"], {"status": "SUSPENDED", "reason": "audit hold"},
            desk_admin_headers,
        )

        blocked = api_client.create_purchase_order(
            create_purchase_order_payload(
                supplier["id"], product["id"], ordered_weight_lbs=1000,
                contract_price_per_cwt_cents=25_000,
                required_delivery_date="2026-08-12", po_number="PO-11"),
            trader_headers,
        )
        validate_error(blocked, ApiErrorId.ERR_SUPPLIER_SUSPENDED)

        api_client.set_supplier_status(supplier["id"], {"status": "ACTIVE"},
                                       desk_admin_headers)
        ok = api_client.create_purchase_order(
            create_purchase_order_payload(
                supplier["id"], product["id"], ordered_weight_lbs=1000,
                contract_price_per_cwt_cents=25_000,
                required_delivery_date="2026-08-12", po_number="PO-11"),
            trader_headers,
        )
        assert validate_success(ok, expected_status=201)["status"] == "BOOKED"

    def test_po_receive_blocked_when_supplier_suspended(
            self, desk_admin_headers, warehouse_operator_headers):
        """PRD §3.1: "Suspension is forceful: every purchase order of that
        supplier still in `BOOKED` status is cancelled automatically."
        PRD §2.8: the target-state precondition (stage 7, `ERR_PO_NOT_BOOKED`)
        is evaluated before the cross-entity supplier check (stage 8,
        `ERR_SUPPLIER_SUSPENDED`), and "Earlier stages mask later ones" — so
        receiving the cascade-cancelled order reports `ERR_PO_NOT_BOOKED`.

        Design: Difficulty/cross_entity_state_dependency/po_create_blocked_when_supplier_suspended
        """
        product = create_product(product_code="CARC-D2", kind="CARCASS",
                                 max_fat_pct=None, shelf_life_days=30)
        supplier = create_supplier(establishment_number="EST-11B")
        warehouse = create_warehouse()
        po = book_po(supplier["id"], product["id"], ordered_weight_lbs=500,
                     contract_price_per_cwt_cents=25_000,
                     required_delivery_date="2026-08-12")
        api_client.set_supplier_status(
            supplier["id"], {"status": "SUSPENDED", "reason": "audit hold"},
            desk_admin_headers,
        )

        resp = api_client.receive_purchase_order(
            po["id"],
            receive_po_payload(warehouse["id"], 500,
                               production_date="2026-08-01"),
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PO_NOT_BOOKED)
        assert get_po(po["id"])["status"] == "CANCELLED", \
            "the suspension cascade cancels the BOOKED order"


class TestWarehouseAggregateCapacity:
    def test_receive_lands_exactly_on_capacity_then_overflows(
            self, warehouse_operator_headers):
        """PRD §2.11: "At receiving, the warehouse's `occupied_lbs` plus the
        incoming received weight must not exceed its `capacity_lbs`."
        PRD §2.11: "Either violation is rejected with
        `ERR_WAREHOUSE_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/warehouse_aggregate_capacity
        """
        product = create_product(product_code="RIBEYE-K", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-12")
        warehouse = create_warehouse(name="WH-AGG", capacity_lbs=1000)
        set_clock("2026-08-03T00:00:00Z")
        po_a = book_po(supplier["id"], product["id"], ordered_weight_lbs=700)
        po_b = book_po(supplier["id"], product["id"], ordered_weight_lbs=300)
        po_c = book_po(supplier["id"], product["id"], ordered_weight_lbs=10)

        receive_po(po_a["id"], warehouse["id"], 700,
                   production_date="2026-08-02")
        receive_po(po_b["id"], warehouse["id"], 300,
                   production_date="2026-08-02")
        assert get_warehouse(warehouse["id"])["occupied_lbs"] == 1000, \
            "700 + 300 lands exactly on the cap and is allowed"

        resp = api_client.receive_purchase_order(
            po_c["id"],
            receive_po_payload(warehouse["id"], 1,
                               production_date="2026-08-02"),
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WAREHOUSE_CAPACITY_EXCEEDED)
        assert get_po(po_c["id"])["status"] == "BOOKED"
        assert get_warehouse(warehouse["id"])["occupied_lbs"] == 1000, \
            "a rejected receive must not change occupancy"

    def test_single_receive_at_exact_capacity_allowed(
            self, warehouse_operator_headers):
        """PRD §2.11: "At receiving, the warehouse's `occupied_lbs` plus the
        incoming received weight must not exceed its `capacity_lbs`."
        PRD §2.11: "Either violation is rejected with
        `ERR_WAREHOUSE_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/warehouse_aggregate_capacity
        """
        product = create_product(product_code="RIBEYE-K2", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-12B")
        warehouse = create_warehouse(capacity_lbs=500)
        po_full = book_po(supplier["id"], product["id"], ordered_weight_lbs=500)
        po_extra = book_po(supplier["id"], product["id"], ordered_weight_lbs=1)

        receive_po(po_full["id"], warehouse["id"], 500,
                   production_date="2026-08-01")
        assert get_warehouse(warehouse["id"])["occupied_lbs"] == 500, \
            "occupied == capacity satisfies must-not-exceed"

        resp = api_client.receive_purchase_order(
            po_extra["id"],
            receive_po_payload(warehouse["id"], 1,
                               production_date="2026-08-01"),
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WAREHOUSE_CAPACITY_EXCEEDED)


class TestReceiveValidationOrdering:
    def test_receive_cancelled_po_over_capacity_reports_state_error(
            self, warehouse_operator_headers, trader_headers):
        """PRD §2.8: "Earlier stages mask later ones: a request that fails an
        earlier check reports that check's error and is never evaluated against
        later checks, so the reported error is always the highest-priority
        failure."
        PRD §3.3: "The purchase order must be `BOOKED`, else
        `ERR_PO_NOT_BOOKED`."

        Design: Difficulty/priority_pair_validation_conflict/receive_state_vs_capacity_constraint
        """
        product = create_product(product_code="RIBEYE-E", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-8")
        warehouse = create_warehouse(name="WH-CAP", capacity_lbs=100)
        po = book_po(supplier["id"], product["id"], ordered_weight_lbs=200)
        api_client.cancel_purchase_order(po["id"], trader_headers)

        resp = api_client.receive_purchase_order(
            po["id"],
            receive_po_payload(warehouse["id"], 500, lot_code="LOT-X",
                               production_date="2026-08-02"),
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PO_NOT_BOOKED)
        assert get_po(po["id"])["status"] == "CANCELLED"
        lots = validate_success(api_client.list_inventory_lots(
            warehouse_operator_headers, params={"po_id": po["id"]}))
        assert lots == [], "no lot may be created by the rejected receive"

    def test_receive_already_received_po_over_capacity_reports_state_error(
            self, warehouse_operator_headers):
        """PRD §2.8: "Earlier stages mask later ones: a request that fails an
        earlier check reports that check's error and is never evaluated against
        later checks, so the reported error is always the highest-priority
        failure."
        PRD §3.3: "The purchase order must be `BOOKED`, else
        `ERR_PO_NOT_BOOKED`."

        Design: Difficulty/priority_pair_validation_conflict/receive_state_vs_capacity_constraint
        """
        product = create_product(product_code="RIBEYE-E2", max_fat_pct=12.0)
        supplier = create_supplier(establishment_number="EST-8B")
        warehouse = create_warehouse(capacity_lbs=100)
        po = book_po(supplier["id"], product["id"], ordered_weight_lbs=100)
        receive_po(po["id"], warehouse["id"], 100,
                   production_date="2026-08-01")

        resp = api_client.receive_purchase_order(
            po["id"],
            receive_po_payload(warehouse["id"], 50,
                               production_date="2026-08-01"),
            warehouse_operator_headers,
        )
        # The state check (stage 7) masks the capacity check (stage 11):
        # occupied 100 + 50 would also exceed the capacity-100 warehouse.
        validate_error(resp, ApiErrorId.ERR_PO_NOT_BOOKED)
        assert get_po(po["id"])["status"] == "RECEIVED"
