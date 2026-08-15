"""Order drafting, submission gates, and order-totals arithmetic
(PRD §3.4, §2.9)."""
from test_helpers import (
    ACCOUNT_MANAGER,
    ApiErrorId,
    assert_order,
    assert_order_line,
    create_active_clinic,
    create_approved_order,
    create_bundle_program,
    create_lot,
    create_order,
    create_product,
    create_stocked_product,
    create_submitted_order,
    enroll_clinic,
    get_clinic,
    get_lot,
    get_order,
    get_success_data,
    make_clinic_buyer_headers,
    order_line_spec,
    setup_enrolled_clinic,
    sole_line,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrderDraft:
    def test_order_create_initial_state_and_lines_pending(self, api):
        """PRD §3.4: "A new order starts `DRAFT`, and each of its lines starts
        `PENDING`."
        PRD §3.5: "A covered line moves `PENDING` → `ALLOCATED` with its
        `lot_id` set to the covering lot, its `qty_allocated` set to the full
        `qty_requested`" — before allocation a line holds no lot and no
        allocated units.

        Design: Corner/entities/order_create_initial_state_and_lines_pending
        """
        clinic = create_active_clinic(clinic_name="Clinic IS",
                                      license_number="LIC-IS")
        product, _lot = create_stocked_product(
            product_overrides={"sku": "CONS-IS", "product_name": "Film Pack"})
        order = validate_success(api.create_order(
            {
                "clinic_id": clinic["id"],
                "ship_to_address": clinic["ship_to_address"],
                "delivery_window_start": "2026-08-03T13:00:00Z",
                "delivery_window_end": "2026-08-03T15:00:00Z",
                "lines": [order_line_spec(product["id"], 2)],
            },
            make_clinic_buyer_headers(clinic["id"])), 201)
        assert_order(order)
        assert order["status"] == "DRAFT"
        # Totals are computed at submission; a DRAFT has none yet.
        for field in ("merchandise_subtotal_cents", "bundle_discount_cents",
                      "merchandise_net_cents", "equipment_surcharge_cents",
                      "freight_fee_cents", "total_cents"):
            assert order.get(field) in (None, 0), (
                f"{field} must not be priced before submit, got {order.get(field)}")

        line = sole_line(order["id"])
        assert_order_line(line)
        assert line["status"] == "PENDING"
        assert line["qty_allocated"] == 0
        assert line["lot_id"] is None

    def test_order_submit_idempotency_violation(self, api):
        """PRD §3.4: "First the order must be `DRAFT` (otherwise
        `ERR_ORDER_INVALID_STATE`)..."
        PRD §3.4: "Submission also reserves the delivery window on the clinic's
        calendar, moves the order from `DRAFT` to `SUBMITTED`, and increments
        its `version`."

        Design: Corner/state_machines/order_submit_idempotency_violation
        """
        clinic = create_active_clinic(clinic_name="Clinic ID",
                                      license_number="LIC-ID")
        product = create_product(sku="CONS-ID", product_name="Tube Box")
        # qty 2: net 2*2500 = 5000 meets the default 5000-cent minimum exactly
        # (equality passes), so the submit gate under test is reachable.
        order = create_order(clinic["id"], [order_line_spec(product["id"], 2)])

        first = validate_success(
            api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"])))
        assert first["status"] == "SUBMITTED"

        resp = api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    def test_order_cancelled_terminal_lockdown_and_resubmit(self, api):
        """PRD §3.6: "Whole-order cancellation — available to the same two
        actors — is accepted from `DRAFT`, `SUBMITTED`, `APPROVED`, or
        `BACKORDERED`, and from anywhere else is rejected with
        `ERR_ORDER_INVALID_STATE`."
        PRD §3.4: "First the order must be `DRAFT` (otherwise
        `ERR_ORDER_INVALID_STATE`)..."

        Design: Corner/state_machines/order_cancelled_terminal_lockdown_and_resubmit
        """
        clinic = create_active_clinic(clinic_name="Clinic TL2",
                                      license_number="LIC-TL2")
        product = create_product(sku="CONS-TL2", product_name="Tape Roll")
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])
        cancelled = validate_success(
            api.cancel_order(order["id"], make_clinic_buyer_headers(clinic["id"])))
        assert cancelled["status"] == "CANCELLED"

        resp = api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        assert get_order(order["id"])["status"] == "CANCELLED"


class TestSubmitClinicGate:
    def test_order_submit_rejected_while_clinic_suspended(self, api):
        """PRD §3.1: "Suspension freezes commercial activity: while a clinic is
        `SUSPENDED`, order submission, order approval, authorization approval,
        and bundle enrollment all fail with `ERR_CLINIC_NOT_ACTIVE`, yet the
        clinic's `DRAFT` orders remain `DRAFT` — suspension cascades to
        nothing."

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_active_clinic
        """
        clinic = create_active_clinic(clinic_name="Clinic X1",
                                      license_number="LIC-X1")
        product, _lot = create_stocked_product(
            product_overrides={"sku": "CONS-X1", "product_name": "Wrap Roll",
                               "unit_price_cents": 10000})
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])

        get_success_data(api.suspend_clinic(clinic["id"], ACCOUNT_MANAGER))

        resp = api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_CLINIC_NOT_ACTIVE)
        assert get_order(order["id"])["status"] == "DRAFT", (
            "The order remains DRAFT while its clinic is SUSPENDED")

    def test_order_submit_succeeds_after_clinic_reinstated(self, api):
        """PRD §3.1: "An `AccountManager` may later suspend an `ACTIVE` clinic
        (moving it to `SUSPENDED`) and reinstate a `SUSPENDED` one back to
        `ACTIVE`"
        PRD §3.4: "First the order must be `DRAFT` (otherwise
        `ERR_ORDER_INVALID_STATE`) and the clinic must be `ACTIVE` (otherwise
        `ERR_CLINIC_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_active_clinic
        """
        clinic = create_active_clinic(clinic_name="Clinic X1R",
                                      license_number="LIC-X1R")
        product, _lot = create_stocked_product(
            product_overrides={"sku": "CONS-X1R", "product_name": "Wrap Roll R",
                               "unit_price_cents": 10000})
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])

        get_success_data(api.suspend_clinic(clinic["id"], ACCOUNT_MANAGER))
        resp = api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_CLINIC_NOT_ACTIVE)

        get_success_data(api.reinstate_clinic(clinic["id"], ACCOUNT_MANAGER))
        submitted = validate_success(
            api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"])))
        assert submitted["status"] == "SUBMITTED"


class TestDeliveryCalendar:
    def test_delivery_window_intersection_rejected(self, api):
        """PRD §3.4: "The clinic's orders in `SUBMITTED`, `APPROVED`, or
        `BACKORDERED` hold their delivery windows; a new window may touch an
        existing one — the new window's start equalling another's end is fine —
        but may not intersect it, otherwise `ERR_DELIVERY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_adjacency
        """
        clinic = create_active_clinic(clinic_name="Clinic W",
                                      license_number="LIC-W1",
                                      delivery_frequency_per_week=5)
        product, _lot = create_stocked_product(
            lot_qty=20,
            product_overrides={"sku": "CONS-W1", "product_name": "Gauze Roll",
                               "unit_price_cents": 10000})
        first = create_submitted_order(
            clinic["id"], product["id"], 1,
            window_start="2026-08-10T13:00:00Z",
            window_end="2026-08-10T15:00:00Z")
        assert first["status"] == "SUBMITTED"

        overlapping = create_order(
            clinic["id"], [order_line_spec(product["id"], 1)],
            window_start="2026-08-10T14:00:00Z",
            window_end="2026-08-10T16:00:00Z")
        resp = api.submit_order(overlapping["id"],
                                make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)
        assert get_order(overlapping["id"])["status"] == "DRAFT"

    def test_delivery_window_touching_adjacency_accepted(self, api):
        """PRD §3.4: "The clinic's orders in `SUBMITTED`, `APPROVED`, or
        `BACKORDERED` hold their delivery windows; a new window may touch an
        existing one — the new window's start equalling another's end is fine —
        but may not intersect it, otherwise `ERR_DELIVERY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_adjacency
        """
        clinic = create_active_clinic(clinic_name="Clinic W2",
                                      license_number="LIC-W2",
                                      delivery_frequency_per_week=5)
        product, _lot = create_stocked_product(
            lot_qty=20,
            product_overrides={"sku": "CONS-W2", "product_name": "Gauze Roll 2",
                               "unit_price_cents": 10000})
        create_submitted_order(
            clinic["id"], product["id"], 1,
            window_start="2026-08-10T13:00:00Z",
            window_end="2026-08-10T15:00:00Z")

        touching = create_order(
            clinic["id"], [order_line_spec(product["id"], 1)],
            window_start="2026-08-10T15:00:00Z",
            window_end="2026-08-10T17:00:00Z")
        submitted = validate_success(
            api.submit_order(touching["id"], make_clinic_buyer_headers(clinic["id"])))
        assert submitted["status"] == "SUBMITTED", (
            "A start equal to the predecessor's end is adjacency, not overlap")

    def test_delivery_frequency_cap_exceeded(self, api):
        """PRD §3.4: "The weekly cadence is enforced next: counting the
        submitting order together with the clinic's other window-holding orders
        whose `delivery_window_start` falls in the same ISO week, the total must
        remain at or below the clinic's `delivery_frequency_per_week`, otherwise
        `ERR_DELIVERY_FREQUENCY_EXCEEDED`."

        Design: Corner/validations/delivery_frequency_cap_exceeded
        """
        clinic = create_active_clinic(clinic_name="Clinic FR",
                                      license_number="LIC-FR",
                                      delivery_frequency_per_week=1)
        product = create_product(sku="CONS-FR", product_name="Saline Bag")
        # Monday of ISO week 2026-W32. qty 2 -> net 5000 meets the default
        # 5000-cent minimum exactly, so the cadence gate is what fails below.
        create_submitted_order(clinic["id"], product["id"], 2,
                               window_start="2026-08-03T13:00:00Z",
                               window_end="2026-08-03T15:00:00Z")
        # Wednesday of the same ISO week — non-overlapping but the cadence
        # cap of 1 is already spent.
        second = create_order(clinic["id"], [order_line_spec(product["id"], 2)],
                              window_start="2026-08-05T13:00:00Z",
                              window_end="2026-08-05T15:00:00Z")
        resp = api.submit_order(second["id"], make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_DELIVERY_FREQUENCY_EXCEEDED)
        assert get_order(second["id"])["status"] == "DRAFT"


class TestMinimumOrderBoundary:
    def _setup_minimum_orders(self, api):
        clinic = create_active_clinic(
            clinic_name="Clinic M", license_number="LIC-M1",
            minimum_order_value_cents=50000, free_freight_threshold_cents=100000)
        p_low = create_product(sku="CONS-M1", product_name="Gloves S",
                               unit_price_cents=49999)
        p_exact = create_product(sku="CONS-M2", product_name="Gloves M",
                                 unit_price_cents=50000)
        create_lot(p_low["id"], qty_on_hand=10)
        create_lot(p_exact["id"], qty_on_hand=10)
        o_low = create_order(clinic["id"], [order_line_spec(p_low["id"], 1)],
                             window_start="2026-08-10T13:00:00Z",
                             window_end="2026-08-10T15:00:00Z")
        o_exact = create_order(clinic["id"], [order_line_spec(p_exact["id"], 1)],
                               window_start="2026-08-10T13:00:00Z",
                               window_end="2026-08-10T15:00:00Z")
        return clinic, o_low, o_exact

    def test_minimum_order_one_cent_below_rejected(self, api):
        """PRD §3.4: "Last of the submit-time checks, the merchandise net must
        reach the clinic's `minimum_order_value_cents` — an order whose net
        equals the minimum exactly passes — otherwise
        `ERR_ORDER_BELOW_MINIMUM`."
        PRD §3.4: "A successful submission ... reserves the delivery window on
        the clinic's calendar" — a rejected submission reserves nothing.

        Design: Difficulty/boundary_precision_check/minimum_order_exact_boundary
        """
        clinic, o_low, o_exact = self._setup_minimum_orders(api)

        resp = api.submit_order(o_low["id"], make_clinic_buyer_headers(clinic["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_BELOW_MINIMUM)
        assert get_order(o_low["id"])["status"] == "DRAFT", (
            "net 49999 < minimum 50000 leaves the order DRAFT")

        # The failed submission holds no window, so the sibling order sharing
        # the same window still submits.
        ok = validate_success(
            api.submit_order(o_exact["id"], make_clinic_buyer_headers(clinic["id"])))
        assert ok["status"] == "SUBMITTED"

    def test_minimum_order_exact_equality_passes(self, api):
        """PRD §3.4: "Last of the submit-time checks, the merchandise net must
        reach the clinic's `minimum_order_value_cents` — an order whose net
        equals the minimum exactly passes — otherwise
        `ERR_ORDER_BELOW_MINIMUM`."
        PRD §3.4: "Sixth, `freight_fee_cents` is zero when the merchandise net
        reaches the clinic's `free_freight_threshold_cents` — equality waives
        freight — and a flat 2,500 cents otherwise."

        Design: Difficulty/boundary_precision_check/minimum_order_exact_boundary
        """
        clinic, _o_low, o_exact = self._setup_minimum_orders(api)

        ok = validate_success(
            api.submit_order(o_exact["id"], make_clinic_buyer_headers(clinic["id"])))
        assert ok["status"] == "SUBMITTED"
        assert ok["merchandise_net_cents"] == 50000, (
            "net equals the minimum exactly and passes")
        assert ok["freight_fee_cents"] == 2500, (
            "net 50000 < free-freight threshold 100000, so freight applies")


class TestOrderTotalsEvaluationOrder:
    def _setup_bundle_order(self, api):
        clinic, _program, _enrollment = setup_enrolled_clinic(
            program_overrides={
                "program_name": "ACME mix",
                "manufacturer_code": "ACME-VET",
                "qualifying_product_types": ["CONSUMABLE", "EQUIPMENT"],
                "min_distinct_categories": 2,
                "bundle_discount_pct": 10,
                "rebate_base_rate_bp": 0,
                "rebate_bonus_rate_bp": 0,
                "bonus_threshold_cents": 999999999,
            },
            clinic_overrides={
                "clinic_name": "Clinic O", "license_number": "LIC-O1",
                "ship_to_address": "4 Farm Ct", "minimum_order_value_cents": 5000,
                "free_freight_threshold_cents": 100000,
            })
        p1 = create_product(sku="CONS-O1", product_name="Wrap Case",
                            manufacturer_code="ACME-VET",
                            product_type="CONSUMABLE", unit_price_cents=65000)
        p2 = create_product(sku="EQ-O1", product_name="Exam Lamp",
                            manufacturer_code="ACME-VET",
                            product_type="EQUIPMENT", unit_price_cents=40000)
        create_lot(p1["id"], qty_on_hand=10)
        create_lot(p2["id"], qty_on_hand=5)
        order = create_order(
            clinic["id"],
            [order_line_spec(p1["id"], 1), order_line_spec(p2["id"], 1)],
            window_start="2026-08-05T13:00:00Z",
            window_end="2026-08-05T15:00:00Z")
        return clinic, order

    def test_freight_computed_on_net_not_gross(self, api):
        """PRD §3.4: "Freight is therefore always computed on the net, never on
        the gross subtotal, while the discount is computed on the gross
        qualifying lines, never on the net."
        PRD §3.4: "Sixth, `freight_fee_cents` is zero when the merchandise net
        reaches the clinic's `free_freight_threshold_cents` — equality waives
        freight — and a flat 2,500 cents otherwise."
        PRD §3.4: "Finally, `total_cents` is the merchandise net plus the
        equipment surcharge plus the freight fee."

        Design: Difficulty/combinatorial_formula/order_totals_net_freight_evaluation_order
        """
        clinic, order = self._setup_bundle_order(api)
        submitted = validate_success(
            api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"])))
        # Gross 105000 >= 100000 would waive freight if freight read the gross;
        # net 94500 < 100000 must charge the flat 2500.
        assert submitted["merchandise_net_cents"] == 94500
        assert submitted["freight_fee_cents"] == 2500, (
            "Freight must be decided on the net (94500), not the gross (105000)")
        assert submitted["total_cents"] == 94500 + 1500 + 2500

    def test_discount_computed_on_gross_per_line(self, api):
        """PRD §3.4: "Third, `bundle_discount_cents` is computed: for each
        qualifying line, the line's gross total is multiplied by the program's
        `bundle_discount_pct` and divided by one hundred, rounded half up to
        whole cents per line, and the per-line results are summed; a
        non-qualified order gets a discount of zero."
        PRD §3.4: "Fifth, `equipment_surcharge_cents` is 1,500 cents per unit
        summed over the order's `EQUIPMENT` lines, and it is never waived."

        Design: Difficulty/combinatorial_formula/order_totals_net_freight_evaluation_order
        """
        clinic, order = self._setup_bundle_order(api)
        submitted = validate_success(
            api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"])))
        assert submitted["merchandise_subtotal_cents"] == 105000
        # Per-line: round_half_up(65000*10/100)=6500, round_half_up(40000*10/100)=4000.
        assert submitted["bundle_discount_cents"] == 10500
        assert submitted["merchandise_net_cents"] == 105000 - 10500
        # One EQUIPMENT unit at 1500c, charged even though the order otherwise
        # qualifies for nothing else surcharge-related.
        assert submitted["equipment_surcharge_cents"] == 1500


class TestEquipmentSurcharge:
    def test_equipment_surcharge_scales_with_units(self, api):
        """PRD §3.4: "Fifth, `equipment_surcharge_cents` is 1,500 cents per unit
        summed over the order's `EQUIPMENT` lines, and it is never waived."
        PRD §3.4: "Sixth, `freight_fee_cents` is zero when the merchandise net
        reaches the clinic's `free_freight_threshold_cents`..."
        PRD §3.4: "Finally, `total_cents` is the merchandise net plus the
        equipment surcharge plus the freight fee."

        Design: Corner/calculations/equipment_surcharge_scales_with_units
        """
        clinic = create_active_clinic(clinic_name="Clinic ES",
                                      license_number="LIC-ES",
                                      free_freight_threshold_cents=5000)
        product, _lot = create_stocked_product(
            lot_qty=5,
            product_overrides={"sku": "EQ-ES", "product_name": "Dental scaler",
                               "product_type": "EQUIPMENT",
                               "unit_price_cents": 20000})
        order = create_order(clinic["id"], [order_line_spec(product["id"], 3)])
        submitted = validate_success(
            api.submit_order(order["id"], make_clinic_buyer_headers(clinic["id"])))
        assert submitted["merchandise_subtotal_cents"] == 60000
        assert submitted["bundle_discount_cents"] == 0, (
            "No enrollment means no bundle discount")
        assert submitted["equipment_surcharge_cents"] == 4500, "3 units * 1500c"
        assert submitted["freight_fee_cents"] == 0, (
            "net 60000 >= threshold 5000 waives freight")
        assert submitted["total_cents"] == 60000 + 4500, (
            "The surcharge is never waived even when freight is")


class TestOrderListing:
    def test_order_list_filtered_by_status(self, api):
        """PRD §3.4: "Order listings may be filtered by `clinic_id` or
        `status`..."
        PRD §3.5: "when at least one line went to backorder, it moves
        `SUBMITTED` → `BACKORDERED` instead"

        Design: Corner/endpoints/order_list_filtered_by_status
        """
        clinic = create_active_clinic(clinic_name="Clinic LF",
                                      license_number="LIC-LF")
        product, _lot = create_stocked_product(
            lot_qty=5,
            product_overrides={"sku": "CONS-LF", "product_name": "Filter Feed"})
        order_a = create_approved_order(
            clinic["id"], product["id"], 5,
            window_start="2026-08-03T13:00:00Z",
            window_end="2026-08-03T15:00:00Z")
        assert order_a["status"] == "APPROVED"
        order_b = create_approved_order(
            clinic["id"], product["id"], 5,
            window_start="2026-08-04T13:00:00Z",
            window_end="2026-08-04T15:00:00Z")
        assert order_b["status"] == "BACKORDERED"

        data, meta = validate_paginated(api.list_orders(
            ACCOUNT_MANAGER,
            params={"clinic_id": clinic["id"], "status": "BACKORDERED"}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == order_b["id"]
        assert order_a["id"] not in [o["id"] for o in data]


class TestImmediateConsistency:
    def test_immediate_consistency_on_approve_and_read(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §2.5: "A triggering request and all of its cascades commit
        atomically: either every effect lands or the request fails outright."
        PRD §3.5: "A covered line moves `PENDING` → `ALLOCATED` with its
        `lot_id` set to the covering lot, its `qty_allocated` set to the full
        `qty_requested`, and the lot's `qty_allocated` increased by the same
        amount."

        Design: Corner/consistency_model/immediate_consistency_on_approve_and_read
        """
        clinic = create_active_clinic(clinic_name="Clinic IC",
                                      license_number="LIC-IC")
        product, lot = create_stocked_product(
            lot_qty=5,
            product_overrides={"sku": "CONS-IC", "product_name": "Imm Pack"})
        order = create_submitted_order(clinic["id"], product["id"], 2)

        approved = validate_success(api.approve_order(order["id"], ACCOUNT_MANAGER))
        assert approved["status"] == "APPROVED", (
            "The approve response itself carries the new status")

        line = sole_line(order["id"])
        assert line["status"] == "ALLOCATED"
        assert line["lot_id"] == lot["id"]
        assert line["qty_allocated"] == 2

        lot_after = get_lot(lot["id"])
        assert lot_after["qty_available"] == 3
        assert lot_after["qty_allocated"] == 2
