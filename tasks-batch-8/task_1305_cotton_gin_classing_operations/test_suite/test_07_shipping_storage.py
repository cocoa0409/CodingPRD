"""Shipping orders and storage: dock turnaround windows, window shape,
cross-entity coherence guards, the order pipeline, free-day boundary, and
the ship cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bales_by_tag,
    class_bale,
    create_confirmed_order,
    create_grade_schedule,
    create_grade_schedule_payload,
    create_grower,
    create_module,
    create_order,
    create_shift,
    create_shipping_order_payload,
    create_warehouse,
    create_warehouse_receipt_payload,
    get_bale,
    get_grower,
    get_order,
    get_receipt,
    get_warehouse,
    gin_module,
    issue_receipt,
    list_ledger_entries,
    make_warehouse_manager_headers,
    pledge_receipt,
    set_clock,
    setup_classed_bale,
    setup_ginned_bale,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
WM = TEST_USERS["warehouse_manager_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


def _two_receipted_bales(membership="MB-900", legal_name="Dock Farm",
                         warehouse_name="WH-D", dock_count=2,
                         stand_label="STAND-N"):
    """Grower + warehouse + module with two 500-lb bales, both receipted."""
    grower = create_grower(membership, legal_name)
    warehouse = create_warehouse(warehouse_name, capacity_bales=10,
                                 dock_count=dock_count)
    shift = create_shift("2026", stand_label)
    module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-D")
    gin_module(module["id"], shift["id"], [("B-D1", 500), ("B-D2", 500)])
    bales = bales_by_tag(module["id"])
    r1 = issue_receipt(bales["B-D1"]["id"], warehouse["id"], wm_user_id="wm-1")
    r2 = issue_receipt(bales["B-D2"]["id"], warehouse["id"], wm_user_id="wm-1")
    return grower, warehouse, bales, (r1, r2)


class TestGradeWindowAdjacency:
    def test_overlapping_window_rejected(self, api):
        """PRD: "For the same `grade_code`, two windows must never overlap;
        adjacency — one window ending exactly when the next begins — is
        allowed. An overlapping create is rejected with
        `ERR_GRADE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/grade_schedule_halfopen_window_adjacency
        """
        create_grade_schedule(grade_code="41-4", premium_discount_points=-110,
                              loan_rate_points=5200,
                              effective_from="2026-01-01T00:00:00Z",
                              effective_to="2026-07-01T00:00:00Z")
        resp = api.create_grade_schedule(
            create_grade_schedule_payload(
                grade_code="41-4", premium_discount_points=-100,
                loan_rate_points=5225, effective_from="2026-06-30T00:00:00Z",
                effective_to="2026-12-01T00:00:00Z"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_GRADE_WINDOW_OVERLAP)

    def test_adjacency_and_other_grade_allowed(self, api):
        """PRD: "adjacency — one window ending exactly when the next begins —
        is allowed."
        PRD: "For the same `grade_code`, two windows must never overlap"

        Design: Difficulty/resource_temporal_overlap/grade_schedule_halfopen_window_adjacency
        """
        create_grade_schedule(grade_code="41-4", premium_discount_points=-110,
                              loan_rate_points=5200,
                              effective_from="2026-01-01T00:00:00Z",
                              effective_to="2026-07-01T00:00:00Z")
        adjacent = validate_success(api.create_grade_schedule(
            create_grade_schedule_payload(
                grade_code="41-4", premium_discount_points=-95,
                loan_rate_points=5250, effective_from="2026-07-01T00:00:00Z",
                effective_to="2027-01-01T00:00:00Z"), ADMIN), expected_status=201)
        assert adjacent["grade_code"] == "41-4", "half-open boundary permits touching"

        other_grade = validate_success(api.create_grade_schedule(
            create_grade_schedule_payload(
                grade_code="31-3", premium_discount_points=265,
                loan_rate_points=5450, effective_from="2026-03-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z"), ADMIN), expected_status=201)
        assert other_grade["grade_code"] == "31-3", (
            "the overlap resource is (grade_code, window)")


class TestDockTurnaroundBuffer:
    def test_tight_gap_rejected(self, api):
        """PRD: "on the same warehouse and dock, the new window must keep at
        least a 30-minute gap to every non-cancelled order's window — the new
        window must end at least 30 minutes before the existing one starts, or
        start at least 30 minutes after the existing one ends — and any tighter
        pairing fails with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dock_window_turnaround_buffer_conflict
        """
        grower, warehouse, bales, _receipts = _two_receipted_bales()
        create_order(warehouse["id"], grower["id"], [bales["B-D1"]["id"]],
                     dock_number=1, load_start="2026-08-10T10:00:00Z",
                     load_end="2026-08-10T12:00:00Z")
        # 12:20 start leaves only a 20-minute gap after the 12:00 end
        resp = api.create_shipping_order(
            create_shipping_order_payload(
                warehouse["id"], grower["id"], [bales["B-D2"]["id"]],
                dock_number=1, load_start="2026-08-10T12:20:00Z",
                load_end="2026-08-10T13:00:00Z"), WM)
        validate_error(resp, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)

    def test_exact_thirty_minute_gap_and_other_dock_allowed(self, api):
        """PRD: "the new window must end at least 30 minutes before the
        existing one starts, or start at least 30 minutes after the existing
        one ends"

        Design: Difficulty/resource_temporal_overlap/dock_window_turnaround_buffer_conflict
        """
        grower, warehouse, bales, _receipts = _two_receipted_bales()
        create_order(warehouse["id"], grower["id"], [bales["B-D1"]["id"]],
                     dock_number=1, load_start="2026-08-10T10:00:00Z",
                     load_end="2026-08-10T12:00:00Z")
        exact = validate_success(api.create_shipping_order(
            create_shipping_order_payload(
                warehouse["id"], grower["id"], [bales["B-D2"]["id"]],
                dock_number=1, load_start="2026-08-10T12:30:00Z",
                load_end="2026-08-10T13:00:00Z"), WM), expected_status=201)
        assert exact["status"] == "DRAFT", "the 30-minute buffer is inclusive"

        other_dock = validate_success(api.create_shipping_order(
            create_shipping_order_payload(
                warehouse["id"], grower["id"], [bales["B-D2"]["id"]],
                dock_number=2, load_start="2026-08-10T10:30:00Z",
                load_end="2026-08-10T11:30:00Z"), WM), expected_status=201)
        assert other_dock["status"] == "DRAFT", (
            "the conflict resource is (warehouse, dock)")


class TestWindowAndShapeValidation:
    def test_inverted_windows_rejected(self, api):
        """PRD: "`effective_to` must be strictly later than `effective_from` or
        the create is rejected with `ERR_INVALID_WINDOW` (HTTP 400)."
        PRD: "a loading window from `load_start` inclusive to `load_end`
        exclusive, which must be strictly later than the start (else
        `ERR_INVALID_WINDOW`)."

        Design: Corner/validations/inverted_windows_rejected
        """
        e1 = api.create_grade_schedule(
            create_grade_schedule_payload(
                grade_code="11-1", premium_discount_points=0,
                loan_rate_points=5000, effective_from="2026-06-01T00:00:00Z",
                effective_to="2026-06-01T00:00:00Z"), ADMIN)
        validate_error(e1, ApiErrorId.ERR_INVALID_WINDOW)

        grower = create_grower("MB-C45", "Invert Farm")
        warehouse = create_warehouse("WH-IV", capacity_bales=5, dock_count=1)
        shift = create_shift("2026", "STAND-IV2")
        module = create_module(grower["id"], ticket_number="T-1",
                               module_tag="MT-IV2")
        gin_module(module["id"], shift["id"], [("B-IV2", 500)])
        bale = bales_by_tag(module["id"])["B-IV2"]
        e2 = api.create_shipping_order(
            create_shipping_order_payload(
                warehouse["id"], grower["id"], [bale["id"]], dock_number=1,
                load_start="2026-08-10T10:00:00Z",
                load_end="2026-08-10T10:00:00Z"), WM)
        validate_error(e2, ApiErrorId.ERR_INVALID_WINDOW)

    def test_empty_bale_ids_and_dock_out_of_range_rejected(self, api):
        """PRD: "an ordered `bale_ids` list of at least one element (an empty
        list fails with `ERR_EMPTY_SHIPMENT`, HTTP 400), a `dock_number` within
        the warehouse's docks from 1 to `dock_count` inclusive (out of range
        fails with `ERR_INVALID_REQUEST`)"

        Design: Corner/validations/empty_bale_ids_and_dock_out_of_range_rejected
        """
        grower = create_grower("MB-C46", "Shape Farm")
        warehouse = create_warehouse("WH-SH", capacity_bales=5, dock_count=2)
        shift = create_shift("2026", "STAND-SH")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-SH")
        gin_module(module["id"], shift["id"], [("B-SH1", 500)])
        bale = bales_by_tag(module["id"])["B-SH1"]

        e1 = api.create_shipping_order(
            create_shipping_order_payload(
                warehouse["id"], grower["id"], [], dock_number=1,
                load_start="2026-08-10T10:00:00Z",
                load_end="2026-08-10T11:00:00Z"), WM)
        validate_error(e1, ApiErrorId.ERR_EMPTY_SHIPMENT)

        e2 = api.create_shipping_order(
            create_shipping_order_payload(
                warehouse["id"], grower["id"], [bale["id"]], dock_number=9,
                load_start="2026-08-10T10:00:00Z",
                load_end="2026-08-10T11:00:00Z"), WM)
        validate_error(e2, ApiErrorId.ERR_INVALID_REQUEST)


class TestShipmentCoherence:
    def test_mixed_grower_shipment_rejected(self, api):
        """PRD: "Every listed bale must belong to the order's grower — a bale
        owned by someone else fails with `ERR_MIXED_GROWER_SHIPMENT`
        (HTTP 422)"

        Design: Corner/validations/mixed_grower_shipment_rejected
        """
        g1 = create_grower("MB-C47A", "Mix A")
        g2 = create_grower("MB-C47B", "Mix B")
        warehouse = create_warehouse("WH-MX", capacity_bales=5, dock_count=1)
        shift = create_shift("2026", "STAND-MX")
        m1 = create_module(g1["id"], ticket_number="T-1", module_tag="MT-MX-A")
        m2 = create_module(g2["id"], ticket_number="T-1", module_tag="MT-MX-B")
        gin_module(m1["id"], shift["id"], [("B-MX-A", 500)])
        gin_module(m2["id"], shift["id"], [("B-MX-B", 500)])
        b1 = bales_by_tag(m1["id"])["B-MX-A"]
        b2 = bales_by_tag(m2["id"])["B-MX-B"]
        issue_receipt(b1["id"], warehouse["id"], wm_user_id="wm-1")
        issue_receipt(b2["id"], warehouse["id"], wm_user_id="wm-1")

        resp = api.create_shipping_order(
            create_shipping_order_payload(
                warehouse["id"], g1["id"], [b1["id"], b2["id"]], dock_number=1,
                load_start="2026-08-10T10:00:00Z",
                load_end="2026-08-10T11:00:00Z"), WM)
        validate_error(resp, ApiErrorId.ERR_MIXED_GROWER_SHIPMENT)
        data, meta = _list_orders(api, warehouse["id"])
        assert meta["total_count"] == 0, "no ShippingOrder persisted"
        assert get_receipt(list_receipts_by_bale(api, b1["id"]))["status"] == "ACTIVE"
        assert get_receipt(list_receipts_by_bale(api, b2["id"]))["status"] == "ACTIVE"

    def test_bale_warehouse_mismatch_rejected(self, api):
        """PRD: "every bale's non-terminal receipt must sit at the order's
        warehouse, else `ERR_BALE_WAREHOUSE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/bale_warehouse_mismatch_rejected
        """
        grower = create_grower("MB-C48", "Mismatch WH Farm")
        w1 = create_warehouse("WH-A", capacity_bales=5, dock_count=1)
        w2 = create_warehouse("WH-B", capacity_bales=5, dock_count=1)
        shift = create_shift("2026", "STAND-WM")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-WM")
        gin_module(module["id"], shift["id"], [("B-WM1", 500)])
        bale = bales_by_tag(module["id"])["B-WM1"]
        issue_receipt(bale["id"], w2["id"], wm_user_id="wm-1")

        resp = api.create_shipping_order(
            create_shipping_order_payload(
                w1["id"], grower["id"], [bale["id"]], dock_number=1,
                load_start="2026-08-10T10:00:00Z",
                load_end="2026-08-10T11:00:00Z"), WM)
        validate_error(resp, ApiErrorId.ERR_BALE_WAREHOUSE_MISMATCH)
        _data, meta = _list_orders(api, w1["id"])
        assert meta["total_count"] == 0


class TestOrderPipeline:
    def test_confirm_revalidates_shippability(self, api):
        """PRD: "The order must be `DRAFT` (else `ERR_ORDER_NOT_CONFIRMABLE`,
        HTTP 409), and every listed bale must still satisfy the same shippable
        predicate (else `ERR_BALE_NOT_SHIPPABLE`) — custody may have moved
        since creation."

        Design: Corner/validations/confirm_order_with_pledged_bale_rejected
        """
        ctx = setup_classed_bale(membership_number="MB-C49",
                                 legal_name="Reval Farm", bale_tag="B-RV1",
                                 stand_label="STAND-RV")
        warehouse = create_warehouse("WH-RV", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")
        order = create_order(warehouse["id"], ctx["grower"]["id"],
                             [ctx["bale"]["id"]], dock_number=1)
        pledge_receipt(receipt["id"])  # receipt moves ACTIVE -> PLEDGED

        resp = api.confirm_shipping_order(order["id"], WM)
        validate_error(resp, ApiErrorId.ERR_BALE_NOT_SHIPPABLE)
        assert get_order(order["id"])["status"] == "DRAFT"
        assert get_receipt(receipt["id"])["status"] == "PLEDGED"

    def test_ship_from_draft_and_double_confirm_rejected(self, api):
        """PRD: "A `WarehouseManager` ships a `CONFIRMED` order (else
        `ERR_ORDER_NOT_SHIPPABLE`, HTTP 409)"
        PRD: "The order must be `DRAFT` (else `ERR_ORDER_NOT_CONFIRMABLE`,
        HTTP 409)"

        Design: Corner/state_machines/order_confirm_twice_and_ship_from_draft_rejected
        """
        grower = create_grower("MB-C20", "Order Farm")
        warehouse = create_warehouse("WH-OR", capacity_bales=5, dock_count=2)
        shift = create_shift("2026", "STAND-OR")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-OR")
        gin_module(module["id"], shift["id"], [("B-OR1", 500)])
        bale = bales_by_tag(module["id"])["B-OR1"]
        issue_receipt(bale["id"], warehouse["id"], wm_user_id="wm-1")
        order = create_order(warehouse["id"], grower["id"], [bale["id"]],
                             dock_number=1)

        e1 = api.ship_shipping_order(order["id"], WM)
        validate_error(e1, ApiErrorId.ERR_ORDER_NOT_SHIPPABLE)

        confirmed = validate_success(api.confirm_shipping_order(order["id"], WM))
        assert confirmed["status"] == "CONFIRMED"
        e2 = api.confirm_shipping_order(order["id"], WM)
        validate_error(e2, ApiErrorId.ERR_ORDER_NOT_CONFIRMABLE)

    def test_cancel_after_ship_and_reissue_rejected(self, api):
        """PRD: "cancelling from any other state fails with
        `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409)."
        PRD: "The bale's custody must be `ON_GIN_FLOOR` with no existing
        receipt in `ACTIVE`, `PLEDGED`, or `RELEASED` status for that bale —
        otherwise `ERR_RECEIPT_NOT_ISSUABLE` (HTTP 409)"
        PRD: "each listed bale's receipt flips to `SHIPPED` and each bale's
        `custody_status` flips to `SHIPPED`; the warehouse's
        `stored_bale_count` decreases by the number of listed bales"

        Design: Corner/state_machines/order_cancel_after_ship_and_receipt_reissue_rejected
        """
        grower = create_grower("MB-C21", "Lock Farm")
        warehouse = create_warehouse("WH-LK", capacity_bales=5, dock_count=1)
        shift = create_shift("2026", "STAND-LK")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-LK")
        gin_module(module["id"], shift["id"], [("B-LK1", 500)])
        bale = bales_by_tag(module["id"])["B-LK1"]
        issue_receipt(bale["id"], warehouse["id"], wm_user_id="wm-1")
        order = create_confirmed_order(warehouse["id"], grower["id"],
                                       [bale["id"]], dock_number=1)
        validate_success(api.ship_shipping_order(order["id"], WM))

        e1 = api.cancel_shipping_order(order["id"], WM)
        validate_error(e1, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)

        e2 = api.create_warehouse_receipt(
            create_warehouse_receipt_payload(bale["id"], warehouse["id"]),
            make_warehouse_manager_headers("wm-1"))
        validate_error(e2, ApiErrorId.ERR_RECEIPT_NOT_ISSUABLE)

        assert get_bale(bale["id"])["custody_status"] == "SHIPPED"
        assert get_warehouse(warehouse["id"])["stored_bale_count"] == 0


class TestStorageCharges:
    def test_storage_free_day_boundary(self, api):
        """PRD: "The first 15 days are free; chargeable days are the days
        stored minus 15, floored at zero, and each chargeable day costs 12
        cents. Exactly 15 days stored means zero charge; 16 days means 12
        cents. When the computed charge is zero, no `LedgerEntry` is posted at
        all; otherwise a `STORAGE_CHARGE` entry with a negative `amount_cents`
        posts against the grower with a `memo` naming the receipt, and the
        grower's `credit_balance_cents` recomputes."

        Design: Corner/calculations/storage_free_day_boundary
        """
        grower = create_grower("MB-C37", "Storage Farm")
        warehouse = create_warehouse("WH-ST", capacity_bales=5, dock_count=2)
        shift = create_shift("2026", "STAND-ST")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-ST")
        gin_module(module["id"], shift["id"], [("B-ST1", 500), ("B-ST2", 500)])
        bales = bales_by_tag(module["id"])
        issue_receipt(bales["B-ST1"]["id"], warehouse["id"], wm_user_id="wm-1")
        issue_receipt(bales["B-ST2"]["id"], warehouse["id"], wm_user_id="wm-1")
        o1 = create_confirmed_order(warehouse["id"], grower["id"],
                                    [bales["B-ST1"]["id"]], dock_number=1,
                                    load_start="2026-08-16T10:00:00Z",
                                    load_end="2026-08-16T11:00:00Z")
        o2 = create_confirmed_order(warehouse["id"], grower["id"],
                                    [bales["B-ST2"]["id"]], dock_number=2,
                                    load_start="2026-08-17T10:00:00Z",
                                    load_end="2026-08-17T11:00:00Z")

        set_clock("2026-08-16T00:00:00Z")  # days_stored == 15
        validate_success(api.ship_shipping_order(o1["id"], WM))
        entries = list_ledger_entries(grower_id=grower["id"])
        assert [e for e in entries if e["entry_type"] == "STORAGE_CHARGE"] == [], (
            "15 days stored posts no STORAGE_CHARGE entry at all")

        set_clock("2026-08-17T00:00:00Z")  # days_stored == 16
        validate_success(api.ship_shipping_order(o2["id"], WM))
        entries = list_ledger_entries(grower_id=grower["id"])
        storage = [e for e in entries if e["entry_type"] == "STORAGE_CHARGE"]
        assert len(storage) == 1
        assert storage[0]["amount_cents"] == -12, "1 chargeable day x 12 cents"
        # ginning -11500 (two 500-lb bales) plus the single storage charge
        assert get_grower(grower["id"])["credit_balance_cents"] == -11512

    def test_ship_cascade_decrements_count_and_posts_storage(self, api):
        """PRD: "On success the order moves to terminal `SHIPPED`; each listed
        bale's receipt flips to `SHIPPED` and each bale's `custody_status`
        flips to `SHIPPED`; the warehouse's `stored_bale_count` decreases by
        the number of listed bales; and storage accrual ends for each receipt
        at the logical-clock date."
        PRD: "The first 15 days are free; chargeable days are the days stored
        minus 15, floored at zero, and each chargeable day costs 12 cents."

        Design: Corner/endpoints/ship_order_decrements_count_and_posts_storage
        """
        grower = create_grower("MB-C62", "Ship Farm")
        warehouse = create_warehouse("WH-S2", capacity_bales=5, dock_count=2)
        shift = create_shift("2026", "STAND-S2")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-S2")
        gin_module(module["id"], shift["id"], [("B-S21", 500), ("B-S22", 500)])
        bales = bales_by_tag(module["id"])
        r1 = issue_receipt(bales["B-S21"]["id"], warehouse["id"], wm_user_id="wm-1")
        r2 = issue_receipt(bales["B-S22"]["id"], warehouse["id"], wm_user_id="wm-1")
        order = create_confirmed_order(
            warehouse["id"], grower["id"],
            [bales["B-S21"]["id"], bales["B-S22"]["id"]], dock_number=1,
            load_start="2026-08-25T10:00:00Z", load_end="2026-08-25T12:00:00Z")

        set_clock("2026-08-21T00:00:00Z")  # 20 days stored
        shipped = validate_success(api.ship_shipping_order(order["id"], WM))
        assert shipped["status"] == "SHIPPED"
        assert get_receipt(r1["id"])["status"] == "SHIPPED"
        assert get_receipt(r2["id"])["status"] == "SHIPPED"
        assert get_bale(bales["B-S21"]["id"])["custody_status"] == "SHIPPED"
        assert get_bale(bales["B-S22"]["id"])["custody_status"] == "SHIPPED"
        assert get_warehouse(warehouse["id"])["stored_bale_count"] == 0

        entries = list_ledger_entries(grower_id=grower["id"])
        storage = [e for e in entries if e["entry_type"] == "STORAGE_CHARGE"]
        assert sorted(e["amount_cents"] for e in storage) == [-60, -60], (
            "20 days - 15 free = 5 days x 12 cents per receipt")
        # ginning -11500 plus two storage charges of -60
        assert get_grower(grower["id"])["credit_balance_cents"] == -11620


def _list_orders(api, warehouse_id):
    return validate_paginated(api.list_shipping_orders(
        WM, params={"warehouse_id": warehouse_id}))


def list_receipts_by_bale(api, bale_id):
    data, _meta = validate_paginated(api.list_warehouse_receipts(
        WM, params={"bale_id": bale_id}))
    return data[0]["id"]
