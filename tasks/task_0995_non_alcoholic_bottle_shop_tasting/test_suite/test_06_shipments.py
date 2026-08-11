"""Shipments: the delivered cascade into order and member loyalty, and
shipment terminal-state lockdown (PRD §3.9).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_member,
    get_member,
    get_order,
    make_category,
    make_lot,
    make_member,
    make_shipping_rule,
    make_sku,
    set_clock,
    setup_shipped_order,
    validate_error,
    validate_success,
)

STAFF = TEST_USERS["shop_staff_headers"]


def _setup_delivered_chain(api):
    """DTC order (SKU 10000 cents, qty 1; CA rule tax/surcharge 0) walked to
    OUT_FOR_DELIVERY. Returns (order_id, member_id, shipment_id)."""
    set_clock()
    category = make_category(code="tea7", display_name="Tea 7")
    sku = make_sku(category["id"], sku_code="sku-7", base_price_cents=10000)
    make_lot(sku["id"], lot_code="L7", qty_received=5)
    member = make_member(email="m7@x.com")
    make_shipping_rule(state_code="CA", tax_rate_bps=0)
    order, member, sku, shipment = setup_shipped_order(
        member=member, sku=sku, qty=1,
    )
    validate_success(api.mark_shipment_in_transit(shipment["id"], STAFF), 200)
    validate_success(
        api.mark_shipment_out_for_delivery(shipment["id"], STAFF), 200
    )
    return order["id"], member["id"], shipment["id"]


class TestDeliveredCascade:
    def test_mark_delivered_bubbles_to_order(self, api):
        """PRD §3.9: "From `OUT_FOR_DELIVERY` it may reach `DELIVERED` — a
        `ShopStaff` or `PlatformAdmin` operator supplies a `delivered_on`
        date — which bubbles up to the parent order: the order's
        `payment_status` transitions to `CAPTURED`, the order's
        `fulfillment_status` transitions to `DELIVERED`."

        Design: Difficulty/transitive_cascade/shipment_delivered_to_member_loyalty_chain
        """
        order_id, member_id, shipment_id = _setup_delivered_chain(api)
        shipment = validate_success(
            api.mark_shipment_delivered(
                shipment_id, {"delivered_on": "2026-05-05"}, STAFF
            ),
            200,
        )
        assert shipment["status"] == "DELIVERED"
        order = get_order(order_id)
        assert order["payment_status"] == "CAPTURED"
        assert order["fulfillment_status"] == "DELIVERED"

    def test_mark_delivered_accrues_loyalty_to_member(self, api):
        """PRD §3.9: "the member's `loyalty_points_balance` is incremented by
        the order's `loyalty_points_earned`, the member's
        `loyalty_points_lifetime` is incremented by the same amount".
        PRD §3.9: "The order's `loyalty_points_earned` is computed as one
        point per dollar of `grand_total_cents`, with the member's tier
        multiplier applied before rounding half-up to a whole point."

        Design: Difficulty/transitive_cascade/shipment_delivered_to_member_loyalty_chain
        """
        order_id, member_id, shipment_id = _setup_delivered_chain(api)
        member_before = get_member(member_id)
        validate_success(
            api.mark_shipment_delivered(
                shipment_id, {"delivered_on": "2026-05-05"}, STAFF
            ),
            200,
        )
        order = get_order(order_id)
        earned = order["loyalty_points_earned"]
        assert isinstance(earned, int) and earned > 0
        member_after = get_member(member_id)
        assert_member(member_after)
        assert (
            member_after["loyalty_points_balance"]
            == member_before["loyalty_points_balance"] + earned
        ), "balance must increase by exactly the order's loyalty_points_earned"
        assert (
            member_after["loyalty_points_lifetime"]
            == member_before["loyalty_points_lifetime"] + earned
        ), "lifetime must increase by the same amount as balance"
        assert member_after["loyalty_tier"] == "BRONZE"


class TestShipmentTerminalLockdown:
    def test_delivered_shipment_cannot_be_marked_lost(self, api):
        """PRD §3.9: "a `status` that walks through `LABEL_CREATED`,
        `IN_TRANSIT`, `OUT_FOR_DELIVERY`, `DELIVERED`, `RETURNED`, and
        `LOST`."
        PRD §3.9: "From `OUT_FOR_DELIVERY` the shipment may be marked `LOST`,
        which likewise sets the order's `payment_status` to `REFUNDED_FULL`
        and claws back the loyalty points, but does not restore the lot
        allocation — the bottles are gone."
        PRD §2.7: "5. State — the target entity's current state permits the
        requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/shipment_terminal_delivered_no_further_transition
        """
        order_id, member_id, shipment_id = _setup_delivered_chain(api)
        validate_success(
            api.mark_shipment_delivered(
                shipment_id, {"delivered_on": "2026-05-05"}, STAFF
            ),
            200,
        )
        resp = api.mark_shipment_lost(shipment_id, STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
