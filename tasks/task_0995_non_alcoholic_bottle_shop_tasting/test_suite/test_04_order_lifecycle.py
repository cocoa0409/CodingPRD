"""Order lifecycle: parallel payment/fulfillment dimensions, cancel
compensation, invalid transitions, OCC, and submit-time violations
(PRD §3.8, §2.4, §2.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    assert_order,
    create_draft_order,
    get_lot,
    get_member,
    get_order,
    make_attested_member,
    make_category,
    make_lot,
    make_member,
    make_member_headers,
    make_shipping_rule,
    make_sku,
    make_special_order,
    receive_special_order_payload,
    set_clock,
    setup_packed_order,
    setup_submitted_order,
    submit_order_fresh,
    submit_order_payload,
    validate_error,
    validate_success,
    walk_special_order,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["shop_staff_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _setup_dtc_order(api, price=800, qty=1):
    """Submitted DTC-to-CA order (zero tax/surcharge rule). Returns
    (order, member, sku)."""
    set_clock()
    make_shipping_rule(state_code="CA", tax_rate_bps=0)
    return setup_submitted_order(
        channel="DTC", ship_to_state_code="CA", qty=qty,
        sku=None, member=None,
    ) if price == 800 else _setup_priced_order(api, price, qty)


def _setup_priced_order(api, price, qty):
    set_clock()
    category = make_category()
    sku = make_sku(category["id"], base_price_cents=price)
    make_lot(sku["id"], qty_received=50)
    member = make_member()
    make_shipping_rule(state_code="CA", tax_rate_bps=0)
    order = create_draft_order(member["id"], channel="DTC",
                               ship_to_state_code="CA")
    add_line(order["id"], member["id"], sku["id"], qty=qty)
    order = validate_success(submit_order_fresh(order["id"], member["id"]), 200)
    return order, member, sku


class TestParallelDimensions:
    def test_pack_and_ship_move_fulfillment_only(self, api):
        """PRD §3.8: "A freshly created order starts with `payment_status`
        set to `UNPAID` and `fulfillment_status` set to `DRAFT` — these two
        dimensions evolve in parallel."
        PRD §3.8: "From `PICKING` a `ShopStaff` operator packs the order,
        transitioning `fulfillment_status` to `PACKED` and bumping `version`."
        PRD §3.8: "the new `Shipment` begins in `LABEL_CREATED` status and the
        order's `fulfillment_status` transitions to `SHIPPED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
        """
        order, member, sku = _setup_dtc_order(api)
        get_success = validate_success(api.pack_order(order["id"], STAFF), 200)
        assert get_success["payment_status"] == "AUTHORIZED"
        assert get_success["fulfillment_status"] == "PACKED"
        shipment = validate_success(
            api.create_shipment(
                order["id"],
                {"carrier": "UPS", "tracking_no": "T123",
                 "shipped_on": "2026-05-02"},
                STAFF,
            ),
            201,
        )
        order = get_order(order["id"])
        assert order["payment_status"] == "AUTHORIZED", (
            "creating a shipment must not move the payment axis"
        )
        assert order["fulfillment_status"] == "SHIPPED"
        assert shipment["status"] == "LABEL_CREATED"

    def test_delivery_moves_both_axes_together(self, api):
        """PRD §3.9: "From `OUT_FOR_DELIVERY` it may reach `DELIVERED` — a
        `ShopStaff` or `PlatformAdmin` operator supplies a `delivered_on`
        date — which bubbles up to the parent order: the order's
        `payment_status` transitions to `CAPTURED`, the order's
        `fulfillment_status` transitions to `DELIVERED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
        """
        order, member, sku = _setup_dtc_order(api)
        validate_success(api.pack_order(order["id"], STAFF), 200)
        shipment = validate_success(
            api.create_shipment(
                order["id"],
                {"carrier": "UPS", "tracking_no": "T123",
                 "shipped_on": "2026-05-02"},
                STAFF,
            ),
            201,
        )
        get_order_response = api.mark_shipment_in_transit(shipment["id"], STAFF)
        validate_success(get_order_response, 200)
        validate_success(
            api.mark_shipment_out_for_delivery(shipment["id"], STAFF), 200
        )
        validate_success(
            api.mark_shipment_delivered(
                shipment["id"], {"delivered_on": "2026-05-05"}, STAFF
            ),
            200,
        )
        order = get_order(order["id"])
        assert order["payment_status"] == "CAPTURED"
        assert order["fulfillment_status"] == "DELIVERED"


class TestCancelConservesInventory:
    def _setup_picking_order(self, api):
        set_clock()
        category = make_category(code="tea17", display_name="Tea17")
        sku = make_sku(category["id"], sku_code="sku-17", base_price_cents=1000)
        lot = make_lot(sku["id"], lot_code="L17", qty_received=20)
        member = make_member(email="m17@x.com")
        make_shipping_rule(state_code="CA", tax_rate_bps=0)
        order = create_draft_order(member["id"], channel="DTC",
                                   ship_to_state_code="CA")
        add_line(order["id"], member["id"], sku["id"], qty=6)
        return order, member, sku, lot

    def test_submit_decrements_lot_qty(self, api):
        """PRD §3.8: "Successful submission transitions the order from `DRAFT`
        to `PICKING` on the fulfillment axis, sets `payment_status` to
        `AUTHORIZED`, runs the lot-allocation walk to populate each line's
        `lot_allocation` (decrementing `InventoryLot.qty_remaining` and
        recomputing `on_hand_cached` for affected SKUs), recomputes the
        order's totals, and bumps the order's `version` by one."

        Design: Difficulty/compensating_invariant/order_submit_cancel_conserves_inventory
        """
        order, member, sku, lot = self._setup_picking_order(api)
        assert get_lot(lot["id"])["qty_remaining"] == 20
        validate_success(submit_order_fresh(order["id"], member["id"]), 200)
        assert get_lot(lot["id"])["qty_remaining"] == 14

    def test_cancel_from_picking_restores_lot_qty_exactly(self, api):
        """PRD §3.8: "From `PICKING`, only `ShopStaff` may cancel, and only
        while `payment_status` is `AUTHORIZED` or `UNPAID`; the cancellation
        restores `InventoryLot.qty_remaining` for every entry in every line's
        `lot_allocation`, recomputes `on_hand_cached` for the affected SKUs,
        sets `payment_status` to `VOIDED`, reverses the loyalty redemption,
        and transitions the order to `CANCELLED`."

        Design: Difficulty/compensating_invariant/order_submit_cancel_conserves_inventory
        """
        order, member, sku, lot = self._setup_picking_order(api)
        validate_success(submit_order_fresh(order["id"], member["id"]), 200)
        assert get_lot(lot["id"])["qty_remaining"] == 14
        cancelled = validate_success(api.cancel_order(order["id"], STAFF), 200)
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "VOIDED"
        assert get_lot(lot["id"])["qty_remaining"] == 20, (
            "cancel must restore qty_remaining to the exact pre-submit value"
        )


class TestInvalidTransitions:
    def test_pack_from_draft_rejected(self, api):
        """PRD §3.8: "From `PICKING` a `ShopStaff` operator packs the order,
        transitioning `fulfillment_status` to `PACKED` and bumping `version`."
        PRD §2.7: "5. State — the target entity's current state permits the
        requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/order_cannot_pack_from_draft
        """
        set_clock()
        category = make_category(code="cs", display_name="CS")
        sku = make_sku(category["id"], sku_code="ss1", base_price_cents=100)
        make_lot(sku["id"], qty_received=5)
        member = make_member(email="ms@x.com")
        order = create_draft_order(member["id"], channel="RETAIL")
        resp = api.pack_order(order["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_initial_state_draft_unpaid(self, api):
        """PRD §3.8: "A freshly created order starts with `payment_status`
        set to `UNPAID` and `fulfillment_status` set to `DRAFT` — these two
        dimensions evolve in parallel."

        Design: Corner/state_machines/initial_state_order_draft_unpaid
        """
        set_clock()
        member = make_member(email="mi@x.com")
        order = validate_success(
            api.create_order(
                {"member_id": member["id"], "channel": "RETAIL"},
                make_member_headers(member["id"]),
            ),
            201,
        )
        assert_order(order)
        assert order["fulfillment_status"] == "DRAFT"
        assert order["payment_status"] == "UNPAID"


class TestSubmitViolations:
    def test_insufficient_inventory_rejected(self, api):
        """PRD §3.2: "If the walk ends with demand still outstanding — the
        non-`EXPIRED`, non-`QUARANTINED` lots cannot cover the request — the
        operation that triggered the walk is rejected with
        `ERR_INSUFFICIENT_INVENTORY`."

        Design: Corner/validations/insufficient_inventory_error
        """
        set_clock()
        category = make_category(code="ci", display_name="CI")
        sku = make_sku(category["id"], sku_code="si1", base_price_cents=100)
        make_lot(sku["id"], qty_received=2)
        member = make_member(email="mi2@x.com")
        make_shipping_rule(state_code="CA", tax_rate_bps=0)
        order = create_draft_order(member["id"], channel="DTC",
                                   ship_to_state_code="CA")
        add_line(order["id"], member["id"], sku["id"], qty=5)
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

    def test_discontinued_sku_blocks_submit(self, api):
        """PRD §3.8: "Every line's SKU must have `discontinued` equal to
        false — adding a discontinued SKU is rejected with
        `ERR_SKU_DISCONTINUED`."

        Design: Corner/validations/sku_discontinued_blocks_submit
        """
        set_clock()
        category = make_category(code="cd", display_name="CD")
        sku = make_sku(category["id"], sku_code="sd1", base_price_cents=100)
        make_lot(sku["id"], qty_received=5)
        member = make_member(email="md@x.com")
        order = create_draft_order(member["id"], channel="RETAIL")
        add_line(order["id"], member["id"], sku["id"], qty=1)
        # Discontinue the SKU after the line exists, then submit.
        validate_success(
            api.update_sku(sku["id"], {"discontinued": True}, ADMIN), 200
        )
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_SKU_DISCONTINUED)

    def test_stale_order_version_rejected(self, api):
        """PRD §2.4: "Submitting an order requires the request to carry
        `expected_order_version`, equal to the `Order`'s `version` the client
        last observed. If the order's current `version` differs — because
        another writer added or removed lines or modified
        `loyalty_points_redeemed` in the interim — the submission is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_version_on_order_submit
        """
        set_clock()
        category = make_category(code="cov", display_name="COV")
        sku = make_sku(category["id"], sku_code="sov", base_price_cents=100)
        make_lot(sku["id"], qty_received=10)
        member = make_member(email="mov@x.com")
        order = create_draft_order(member["id"], channel="RETAIL")
        stale_version = order["version"]
        add_line(order["id"], member["id"], sku["id"], qty=1)
        resp = api.submit_order(
            order["id"],
            submit_order_payload(stale_version),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_insufficient_points_rejected(self, api):
        """PRD §3.8: "At submit time the member's `loyalty_points_balance`
        must be greater than or equal to `loyalty_points_redeemed`, otherwise
        the submit is rejected with `ERR_INSUFFICIENT_POINTS`."
        PRD §3.10: "the member's `loyalty_points_balance` is credited with a
        bonus of ten points per bottle (ten multiplied by `quantity`)."

        Design: Corner/errors/error_insufficient_points
        """
        set_clock()
        category = make_category(code="cpt", display_name="CPT")
        sku = make_sku(category["id"], sku_code="spt", base_price_cents=1000)
        make_lot(sku["id"], qty_received=50)
        member = make_member(email="mpt@x.com")
        # Accrue a modest positive balance (10 pts/bottle * 10 bottles = 100)
        # so the member demonstrably has some points but fewer than 500.
        special = make_special_order(member["id"], requested_sku_code="spt",
                                     quantity=10, deposit_cents=0)
        walk_special_order(special["id"], sku["id"])
        balance = get_member(member["id"])["loyalty_points_balance"]
        assert balance < 500, "setup must leave the member below 500 points"
        make_shipping_rule(state_code="CA", tax_rate_bps=0)
        order = create_draft_order(
            member["id"], channel="DTC", ship_to_state_code="CA",
            loyalty_points_redeemed=500,
        )
        add_line(order["id"], member["id"], sku["id"], qty=1)
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS)
