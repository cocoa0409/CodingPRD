"""Purchase orders: submit gates, min-order boundary, landed cost, valuation."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_purchase_order,
    create_active_program,
    create_approved_vendor_with_quote,
    create_open_event,
    create_pos_order,
    create_quote_payload,
    create_stock_po,
    create_variant,
    create_vendor,
    get_variant,
    NON_EXISTENT_UUID,
    patch_vendor,
    receive_po,
    setup_storefront,
    stock_variant,
    submit_po,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestMinOrderQtyBoundary:
    def _setup(self, api):
        shop = setup_storefront(stock_qty=None)
        vendor = create_approved_vendor_with_quote(
            shop["program"]["id"], shop["design"]["id"],
            unit_cost_cents=500, min_order_qty=25,
        )
        return shop, vendor

    def test_qty_exactly_at_min_order_submits(self, api):
        """PRD §3.5: "`qty_ordered` must be at least the `min_order_qty` of
        the vendor's `ACTIVE` quote on that design (else
        `ERR_MIN_ORDER_QTY`)."

        Design: Difficulty/boundary_precision_check/min_order_qty_boundary_exact_vs_below
        """
        shop, vendor = self._setup(api)
        po = create_stock_po(
            shop["program"]["id"], shop["variant"]["id"], vendor["id"], 25
        )
        submitted = validate_success(api.submit_purchase_order(po["id"], MANAGER), 200)
        assert submitted["status"] == "SUBMITTED", (
            "qty_ordered 25 == min_order_qty 25 satisfies 'at least'"
        )

    def test_qty_one_below_min_order_rejected(self, api):
        """PRD §3.5: "`qty_ordered` must be at least the `min_order_qty` of
        the vendor's `ACTIVE` quote on that design (else
        `ERR_MIN_ORDER_QTY`)."

        Design: Difficulty/boundary_precision_check/min_order_qty_boundary_exact_vs_below
        """
        shop, vendor = self._setup(api)
        po = create_stock_po(
            shop["program"]["id"], shop["variant"]["id"], vendor["id"], 24
        )
        res = api.submit_purchase_order(po["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_MIN_ORDER_QTY, 422)


class TestPoSubmitVendorGate:
    def test_submit_with_pending_vendor_rejected(self, api):
        """PRD §3.5: "the vendor must be `APPROVED` (else
        `ERR_VENDOR_NOT_APPROVED`), the variant's design must be `APPROVED`
        (else `ERR_DESIGN_NOT_LICENSED`), and `qty_ordered` must be at least
        the `min_order_qty` of the vendor's `ACTIVE` quote on that design
        (else `ERR_MIN_ORDER_QTY`)."

        Design: Difficulty/cross_entity_state_dependency/po_submit_requires_vendor_approved
        """
        shop = setup_storefront(stock_qty=None)
        pending_vendor = create_vendor(
            shop["program"]["id"],
            quotes=[create_quote_payload(shop["design"]["id"], min_order_qty=25)],
            name="PendingCo",
            contact_email="pending@co.com",
        )
        po = create_stock_po(
            shop["program"]["id"], shop["variant"]["id"], pending_vendor["id"], 25
        )
        res = api.submit_purchase_order(po["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_VENDOR_NOT_APPROVED, 409)

    def test_submit_succeeds_after_vendor_approval(self, api):
        """PRD §3.5: "the vendor must be `APPROVED` (else
        `ERR_VENDOR_NOT_APPROVED`)"
        PRD §3.5: "A successful submit moves the order to `SUBMITTED`; from
        any other state the submit is `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/po_submit_requires_vendor_approved
        """
        shop = setup_storefront(stock_qty=None)
        pending_vendor = create_vendor(
            shop["program"]["id"],
            quotes=[create_quote_payload(shop["design"]["id"], min_order_qty=25)],
            name="PendingCo",
            contact_email="pending@co.com",
        )
        po = create_stock_po(
            shop["program"]["id"], shop["variant"]["id"], pending_vendor["id"], 25
        )
        patch_vendor(pending_vendor["id"], status="APPROVED")
        submitted = validate_success(api.submit_purchase_order(po["id"], MANAGER), 200)
        assert submitted["status"] == "SUBMITTED", (
            "identical PO body — only the vendor's state changed"
        )
        resubmit = api.submit_purchase_order(po["id"], MANAGER)
        validate_error(resubmit, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


class TestLandedCost:
    def test_landed_cost_amortizes_licensing_fee(self, api):
        """PRD §3.5: "`landed_unit_cost_cents` becomes the purchase order's
        `unit_cost_cents` plus the design's `licensing_fee_cents` divided by
        the order's `qty_ordered`, with that division rounded half-up to whole
        cents — the one-time licensing fee amortized across the run."

        Design: Corner/calculations/landed_cost_amortizes_licensing_fee
        """
        shop = setup_storefront(stock_qty=None, licensing_fee_cents=10000)
        vendor = create_approved_vendor_with_quote(
            shop["program"]["id"], shop["design"]["id"],
            unit_cost_cents=500, min_order_qty=25,
        )
        po = create_stock_po(
            shop["program"]["id"], shop["variant"]["id"], vendor["id"], 25
        )
        submit_po(po["id"])
        receive_po(po["id"], 25)
        variant = get_variant(shop["variant"]["id"])
        assert variant["landed_unit_cost_cents"] == 900, (
            f"500 + round_half_up(10000/25) = 500 + 400, got "
            f"{variant['landed_unit_cost_cents']}"
        )
        assert variant["on_hand_qty"] == 25

    def test_receive_unknown_po_returns_not_found(self, api):
        """PRD §2.8: "Path identifiers are validated left to right — the
        program first, then the resource within it — and the first missing
        identifier yields its own 404: `ERR_PROGRAM_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`,
        `ERR_VARIANT_NOT_FOUND`, `ERR_DROP_NOT_FOUND`, `ERR_PO_NOT_FOUND`,
        `ERR_CAMPAIGN_NOT_FOUND`, `ERR_PREORDER_NOT_FOUND`,
        `ERR_EVENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_EXCHANGE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, or
        `ERR_ALLOCATION_RUN_NOT_FOUND`."

        Design: Corner/errors/receive_unknown_po_returns_not_found
        """
        create_active_program()
        res = api.receive_purchase_order(
            NON_EXISTENT_UUID, {"qty": 1}, MANAGER
        )
        validate_error(res, ApiErrorId.ERR_PO_NOT_FOUND, 404)


class TestInventoryValuationDualMethod:
    def _setup_two_layer_stock(self, api):
        """100 units received at landed 500, then 100 at landed 700; a POS
        sale of 100 units consumes stock. Returns program_id."""
        shop = setup_storefront(
            stock_qty=None, unit_price_cents=1000, size="ONE_SIZE"
        )
        program_id = shop["program"]["id"]
        variant_id = shop["variant"]["id"]
        vendor_a = create_approved_vendor_with_quote(
            program_id, shop["design"]["id"], unit_cost_cents=500,
            min_order_qty=25, production_days=10, name="VendorA",
        )
        vendor_b = create_approved_vendor_with_quote(
            program_id, shop["design"]["id"], unit_cost_cents=700,
            min_order_qty=25, production_days=5, name="VendorB",
        )
        stock_variant(program_id, variant_id, vendor_a["id"], 100)
        stock_variant(program_id, variant_id, vendor_b["id"], 100)
        event = create_open_event(program_id, register="GYM-A", name="Game 1")
        create_pos_order(
            program_id, event["id"], variant_id, 100, payment_method="CASH"
        )
        return program_id

    def test_fifo_valuation_consumes_oldest_layer_first(self, api):
        """PRD §3.5: "Under `FIFO`, each receipt forms a cost layer stamped
        with its receipt time and its landed unit cost; layers are consumed
        oldest-first — receipt time ascending, ties broken by the purchase
        order's `created_at` ascending — against units sold, fulfilled, or
        swapped out in chronological order, and the valuation is the sum over
        the units remaining in each layer of quantity times that layer's
        landed cost."

        Design: Difficulty/dual_variant_calc/inventory_valuation_fifo_vs_weighted_avg
        """
        program_id = self._setup_two_layer_stock(api)
        data = validate_success(
            api.get_valuation(program_id, TREASURER, params={"method": "FIFO"}), 200
        )
        assert data["total_value_cents"] == 70000, (
            f"the 100 sold consumed the earlier 500-cost layer; the 100 "
            f"remaining units are all from the 700-cost layer, got "
            f"{data['total_value_cents']}"
        )

    def test_weighted_avg_valuation_blends_layer_costs(self, api):
        """PRD §3.5: "Under `WEIGHTED_AVG`, each variant's average is its
        total received cost divided by its total received quantity, rounded
        half-up to whole cents, and the valuation is the sum over variants of
        `on_hand_qty` times that average."
        PRD §3.5: "Identical receipt histories produce different numbers under
        the two methods whenever receipt costs differ across layers."

        Design: Difficulty/dual_variant_calc/inventory_valuation_fifo_vs_weighted_avg
        """
        program_id = self._setup_two_layer_stock(api)
        wavg = validate_success(
            api.get_valuation(program_id, TREASURER, params={"method": "WEIGHTED_AVG"}),
            200,
        )
        assert wavg["total_value_cents"] == 60000, (
            f"avg = (50000 + 70000) / 200 = 600; 100 units x 600, got "
            f"{wavg['total_value_cents']}"
        )
        fifo = validate_success(
            api.get_valuation(program_id, TREASURER, params={"method": "FIFO"}), 200
        )
        assert fifo["total_value_cents"] != wavg["total_value_cents"], (
            "identical inputs must produce divergent dual-variant outputs "
            "when receipt costs differ across layers"
        )
