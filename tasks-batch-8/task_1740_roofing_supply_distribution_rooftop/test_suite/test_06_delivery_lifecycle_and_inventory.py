"""Delivery state machine (fail/reschedule cycle, terminal lockdown) and
inventory conservation across dispatch and failure."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_slot,
    schedule_delivery,
    setup_delivered_order,
    setup_order_scenario,
    validate_error,
    validate_success,
    ApiErrorId,
)

DISPATCH = TEST_USERS["dispatcher_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]


class TestDeliveryFailRescheduleCycle:
    def _failed_delivery(self):
        """CONFIRMED order (30 bundles), delivery dispatched then FAILED."""
        ctx = setup_order_scenario(branch_code="BR-D1", sku="SH-D1",
                                   price=3000, roof_squares=10.0, on_hand=200,
                                   company_name="Deliv Co")
        slot_a = make_slot(ctx["branch"]["id"], slot_date="2026-08-12",
                           equipment_type="GROUND", capacity=2)
        slot_b = make_slot(ctx["branch"]["id"], slot_date="2026-08-13",
                           equipment_type="GROUND", capacity=2)
        delivery = get_success_data(api_client.schedule_delivery(
            ctx["order"]["id"], slot_a["id"], "GROUND", DISPATCH))
        get_success_data(api_client.dispatch_delivery(delivery["id"], DISPATCH))
        get_success_data(api_client.fail_delivery(delivery["id"], DISPATCH))
        ctx.update({"slot_a": slot_a, "slot_b": slot_b, "delivery": delivery})
        return ctx

    def test_cycle_returns_to_en_route_and_attempt_count_accumulates(self, api):
        """PRD §3.5: "dispatch increments `attempt_count` by one."
        PRD §3.5: "A rescheduled delivery returns to `SCHEDULED` through
        reconfirmation, permitted only from `RESCHEDULED` (otherwise
        `ERR_DELIVERY_NOT_RESCHEDULED`) with no further effects."

        SCHEDULED -> EN_ROUTE -> FAILED -> RESCHEDULED -> SCHEDULED ->
        EN_ROUTE: two passes through dispatch leave attempt_count == 2.

        Design: Difficulty/non_linear_state_machine/delivery_fail_reschedule_cycle
        """
        ctx = self._failed_delivery()
        delivery_id = ctx["delivery"]["id"]
        get_success_data(api_client.reschedule_delivery(
            delivery_id, ctx["slot_b"]["id"], DISPATCH))
        get_success_data(api_client.reconfirm_delivery(delivery_id, DISPATCH))
        en_route = validate_success(
            api_client.dispatch_delivery(delivery_id, DISPATCH))
        assert en_route["status"] == "EN_ROUTE"
        assert en_route["attempt_count"] == 2

    def test_reschedule_shifts_slot_booking_and_reprices(self, api):
        """PRD §3.5: "success moves the delivery to `RESCHEDULED`, updates
        `delivery_slot_id`, shifts `booked_count` from the old slot to the new
        (down one, up one), and reprices: `fee_cents` is recomputed under the
        fee rule, the order's `delivery_fee_cents` is updated, and
        `total_cents` recomputes."

        Design: Difficulty/non_linear_state_machine/delivery_fail_reschedule_cycle
        """
        ctx = self._failed_delivery()
        rescheduled = validate_success(api_client.reschedule_delivery(
            ctx["delivery"]["id"], ctx["slot_b"]["id"], DISPATCH))
        assert rescheduled["status"] == "RESCHEDULED"
        assert rescheduled["delivery_slot_id"] == ctx["slot_b"]["id"]
        old_slot = get_success_data(
            api_client.get_delivery_slot(ctx["slot_a"]["id"], DISPATCH))
        new_slot = get_success_data(
            api_client.get_delivery_slot(ctx["slot_b"]["id"], DISPATCH))
        assert old_slot["booked_count"] == 0
        assert new_slot["booked_count"] == 1
        reconfirmed = validate_success(
            api_client.reconfirm_delivery(ctx["delivery"]["id"], DISPATCH))
        assert reconfirmed["status"] == "SCHEDULED"


class TestInventoryConservedAcrossDispatchThenFail:
    def _lot_after_confirm(self):
        ctx = setup_order_scenario(branch_code="BR-I1", sku="SH-I1",
                                   price=2000, roof_squares=10.0, on_hand=100,
                                   lot_code="LOT-I", company_name="Inv Co")
        _slot, delivery = schedule_delivery(
            ctx["order"]["id"], ctx["branch"]["id"], slot_date="2026-08-16",
            equipment_type="GROUND")
        ctx["delivery"] = delivery
        return ctx

    def test_fail_restores_on_hand_and_reserved_exactly(self, api):
        """PRD §3.5: "Marking an en-route delivery failed — again only from
        `EN_ROUTE`, else `ERR_DELIVERY_NOT_EN_ROUTE` — moves it to `FAILED`
        and restores inventory: the attempted quantity is added back to the
        lot's `on_hand_bundles` and `reserved_bundles`."

        Lot starts at on_hand 100; confirm reserves 30; dispatch draws both
        down (70 / 0); fail restores both to 100 / 30.

        Design: Difficulty/compensating_invariant/inventory_conserved_across_dispatch_then_fail
        """
        ctx = self._lot_after_confirm()
        lot_id = ctx["lot"]["id"]
        get_success_data(api_client.dispatch_delivery(ctx["delivery"]["id"],
                                                      DISPATCH))
        mid = get_success_data(api_client.get_inventory_lot(lot_id, WAREHOUSE))
        assert mid["on_hand_bundles"] == 70
        assert mid["reserved_bundles"] == 0
        get_success_data(api_client.fail_delivery(ctx["delivery"]["id"],
                                                  DISPATCH))
        after = get_success_data(api_client.get_inventory_lot(lot_id,
                                                              WAREHOUSE))
        assert after["on_hand_bundles"] == 100
        assert after["reserved_bundles"] == 30
        assert after["on_hand_bundles"] + after["reserved_bundles"] == 130

    def test_available_bundles_floored_view_at_each_step(self, api):
        """PRD §2.7: "The read-only `available_bundles` figure is the on-hand
        count minus the reserved count, floored at zero so a lot never reports
        negative availability. Receiving stock raises on-hand; confirming an
        order raises reserved; dispatching a delivery converts reservation
        into physical draw by decrementing both; a failed delivery restores
        both; a received return restocks the unopened bundles."

        available_bundles reads 70 after confirm, 70 mid-flight, 70 after the
        restore — the conserved sum never exposes phantom stock.

        Design: Difficulty/compensating_invariant/inventory_conserved_across_dispatch_then_fail
        """
        ctx = self._lot_after_confirm()
        lot_id = ctx["lot"]["id"]
        after_confirm = get_success_data(
            api_client.get_inventory_lot(lot_id, WAREHOUSE))
        assert after_confirm["available_bundles"] == 70
        get_success_data(api_client.dispatch_delivery(ctx["delivery"]["id"],
                                                      DISPATCH))
        mid = get_success_data(api_client.get_inventory_lot(lot_id, WAREHOUSE))
        assert mid["available_bundles"] == 70
        get_success_data(api_client.fail_delivery(ctx["delivery"]["id"],
                                                  DISPATCH))
        after = get_success_data(api_client.get_inventory_lot(lot_id,
                                                              WAREHOUSE))
        assert after["available_bundles"] == 70


class TestTerminalDeliveredLockdown:
    def test_fail_and_dispatch_rejected_after_delivered(self, api):
        """PRD §3.5: "Completing the run moves `EN_ROUTE` to the terminal
        `DELIVERED` state (from anywhere else, `ERR_DELIVERY_NOT_EN_ROUTE`),
        stamps `delivered_at` with the current logical clock, adds the
        delivery's quantities into each line's `delivered_bundles`, recomputes
        the order's `fulfillment_status` — `DELIVERED` when every line is
        fully delivered, otherwise `PARTIALLY_DELIVERED` — and releases the
        slot by decrementing `booked_count` by one."
        PRD §3.5: "Sending the truck out moves a delivery from `SCHEDULED` to
        `EN_ROUTE` and is allowed only from `SCHEDULED` (otherwise
        `ERR_DELIVERY_NOT_SCHEDULED`) and only while the parent order is
        `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`); dispatch increments
        `attempt_count` by one and, for each covered order line, decrements
        the lot's `on_hand_bundles` and `reserved_bundles` by the delivered
        quantity — the reservation becomes a physical draw."

        Design: Corner/state_machines/delivery_terminal_delivered_lockdown
        """
        ctx = setup_delivered_order(branch_code="BR-SM4", sku="SH-SM4",
                                    roof_squares=5.0, company_name="SM4 Co")
        delivery_id = ctx["delivery"]["id"]
        assert ctx["delivery"]["status"] == "DELIVERED"
        resp_fail = api_client.fail_delivery(delivery_id, DISPATCH)
        validate_error(resp_fail, ApiErrorId.ERR_DELIVERY_NOT_EN_ROUTE)
        resp_dispatch = api_client.dispatch_delivery(delivery_id, DISPATCH)
        validate_error(resp_dispatch, ApiErrorId.ERR_DELIVERY_NOT_SCHEDULED)
